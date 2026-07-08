"""Bidirectional bridge to an external JDSSArrow gateway.

Mirrors the shape of :mod:`backend.cot.tcp_server`: a module-level config dict
persisted to ``data/jdss_config.json``, ``start``/``stop``/``restart`` lifecycle
called from the FastAPI lifespan, a ``get_status`` for the admin UI, and outbound
publisher helpers called explicitly from the tracking/tactical-object/messaging
routers.

Inbound
    A background task consumes the gateway's ``/ws/events`` live feed (falling
    back to polling ``/api/messages`` when the socket is down) and renders each
    JDSS message onto the Arrow map by reusing the existing create+broadcast
    paths. Only ``direction == "in"`` events (messages the gateway received from
    coalition peers) are ingested — Arrow's own published data comes back as
    ``"out"`` and is skipped, so nothing echoes.

Outbound
    ``publish_operator_presence`` / ``publish_tactical_object`` / ``publish_chat``
    POST to the gateway's ``/api/publish/*`` endpoints. Ingestion writes rows
    directly via ``SessionLocal`` (never through the API routes), so it never
    re-triggers these hooks — no loop guard beyond the inbound direction filter
    is required.

Wire shapes (fixed external contract):
  * ``/ws/events`` event  →  flat: ``{direction, type, originator_id, callsign,
    message_id, classification, releasable_to, body}`` (``body`` is the typed
    message body). ``direction`` is ``"received"`` for coalition traffic and
    ``"sent"`` for messages this node originated; plus ``{direction:"snapshot",
    snapshot:{...}}`` on connect and ``{direction:"heartbeat"}`` every 15 s.
  * ``/api/messages``     →  nested: ``{header:{message_id, originator_id, ...},
    body:{type, ...}}``.
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from backend.websocket.manager import broadcaster

log = logging.getLogger("backend.jdss")

_CFG_FILE = Path("data/jdss_config.json")

# JDSS ContactSighting.identity is an APP-6D StandardIdentity IntEnum
# (PENDING=0, UNKNOWN=1, ASSUMED_FRIEND=2, FRIEND=3, NEUTRAL=4, SUSPECT=5, HOSTILE=6).
_IDENTITY_TO_AFFILIATION = {
    0: "UNKNOWN",
    1: "UNKNOWN",
    2: "FRIENDLY",
    3: "FRIENDLY",
    4: "NEUTRAL",
    5: "HOSTILE",
    6: "HOSTILE",
}

# Inverse: Arrow affiliation → APP-6D standard-identity digit. Sent on every
# outbound message so the receiving JDSS client renders the correct symbol
# frame/colour instead of defaulting a contact to HOSTILE.
_AFFILIATION_TO_IDENTITY = {
    "FRIENDLY": 3,
    "FRIEND": 3,
    "ASSUMED_FRIEND": 2,
    "NEUTRAL": 4,
    "SUSPECT": 5,
    "HOSTILE": 6,
    "ENEMY": 6,
    "UNKNOWN": 1,
    "PENDING": 0,
}

#: StandardIdentity digit for a friendly own-force element.
_IDENTITY_FRIEND = 3


def _object_identity(obj: Any) -> int:
    """APP-6D standard-identity digit for a tactical object, from its affiliation.

    Falls back to the object type (an ``ENEMY`` object is hostile) and finally to
    UNKNOWN, so a symbol is never silently mis-framed as hostile.
    """
    aff = (getattr(obj, "affiliation", "") or "").upper()
    if aff in _AFFILIATION_TO_IDENTITY:
        return _AFFILIATION_TO_IDENTITY[aff]
    if (getattr(obj, "type", "") or "").upper() == "ENEMY":
        return _AFFILIATION_TO_IDENTITY["HOSTILE"]
    return _AFFILIATION_TO_IDENTITY["UNKNOWN"]


# ── Persistent config ─────────────────────────────────────────────────────────

_cfg: dict = {
    "enabled": True,
    "base_url": os.environ.get("ARROW_JDSS_URL", "http://192.168.0.202:8000"),
    "publish_presence": True,  # Arrow operator GPS  → JDSS presence
    "publish_contacts": True,  # Arrow tactical obj  → JDSS contact
    "publish_chat": True,  # Arrow chat          → JDSS chat
    "poll_fallback_secs": 5,  # used only while the WebSocket is down
    "note": "Bridge to a JDSSArrow gateway. base_url is its HTTP root, e.g. http://192.168.0.202:8000.",
}


def load_config() -> None:
    global _cfg
    try:
        _cfg.update(json.loads(_CFG_FILE.read_text()))
    except Exception:
        pass


def save_config() -> None:
    _CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CFG_FILE.write_text(json.dumps(_cfg, indent=2))


def get_config() -> dict:
    return dict(_cfg)


def update_config(patch: dict) -> dict:
    for k, v in patch.items():
        if k in _cfg:
            _cfg[k] = v
    save_config()
    return get_config()


# ── Runtime state ─────────────────────────────────────────────────────────────


@dataclass
class _State:
    ws_connected: bool = False
    last_event_at: float = 0.0
    last_error: str = ""
    rx_messages: int = 0  # JDSS → Arrow ingested
    tx_presence: int = 0  # Arrow → JDSS pushed
    tx_contacts: int = 0
    tx_chat: int = 0
    snapshot: dict = field(default_factory=dict)  # last /api/monitor/snapshot
    peers: list = field(default_factory=list)  # last /api/monitor/peers


_state = _State()


def get_status() -> dict:
    """Full bridge status for the admin UI."""
    return {
        "enabled": _cfg.get("enabled", True),
        "base_url": _cfg.get("base_url", ""),
        "running": _task is not None and not _task.done(),
        "ws_connected": _state.ws_connected,
        "last_event_ago_s": (
            int(time.time() - _state.last_event_at) if _state.last_event_at else None
        ),
        "last_error": _state.last_error,
        "rx_messages": _state.rx_messages,
        "tx_presence": _state.tx_presence,
        "tx_contacts": _state.tx_contacts,
        "tx_chat": _state.tx_chat,
        "publish_presence": _cfg.get("publish_presence", True),
        "publish_contacts": _cfg.get("publish_contacts", True),
        "publish_chat": _cfg.get("publish_chat", True),
        "snapshot": _state.snapshot,
        "peers": _state.peers,
    }


# ── Lifecycle ─────────────────────────────────────────────────────────────────

_task: asyncio.Task | None = None
_poller: asyncio.Task | None = None
_client: httpx.AsyncClient | None = None
_seen: collections.deque[str] = collections.deque(maxlen=2000)
_seen_set: set[str] = set()


def _mark_seen(message_id: str | None) -> bool:
    """Record a message_id; return True if it was already seen (a duplicate)."""
    if not message_id:
        return False
    if message_id in _seen_set:
        return True
    if len(_seen) == _seen.maxlen:
        _seen_set.discard(_seen[0])
    _seen.append(message_id)
    _seen_set.add(message_id)
    return False


async def start() -> None:
    global _task, _poller, _client
    load_config()
    if not _cfg.get("enabled", True):
        log.info("JDSS bridge disabled in config")
        return
    base_url = _cfg.get("base_url", "").rstrip("/")
    if not base_url:
        log.warning("JDSS bridge enabled but base_url is empty — not starting")
        return
    _client = httpx.AsyncClient(base_url=base_url, timeout=10.0)
    _task = asyncio.create_task(_run_loop())
    _poller = asyncio.create_task(_status_poll_loop())
    log.info("JDSS bridge started → %s", base_url)


async def _cancel(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def stop() -> None:
    global _task, _poller, _client
    await _cancel(_task)
    await _cancel(_poller)
    if _client is not None:
        await _client.aclose()
    _task = None
    _poller = None
    _client = None
    _state.ws_connected = False
    log.info("JDSS bridge stopped")


async def restart() -> None:
    await stop()
    await start()


def _ready() -> bool:
    return _client is not None and _cfg.get("enabled", True)


# ── Inbound consumer ──────────────────────────────────────────────────────────


async def _run_loop() -> None:
    """Prefer the live ``/ws/events`` stream; fall back to polling on failure."""
    while True:
        try:
            await _consume_ws()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _state.ws_connected = False
            _state.last_error = str(exc)
            log.warning("JDSS WS unavailable (%s) — polling fallback", exc)
            try:
                await _poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as poll_exc:
                _state.last_error = str(poll_exc)
                log.debug("JDSS poll failed: %s", poll_exc)
            await asyncio.sleep(int(_cfg.get("poll_fallback_secs", 5)))


async def _consume_ws() -> None:
    import websockets

    base = _cfg.get("base_url", "").rstrip("/")
    ws_url = base.replace("http", "ws", 1) + "/ws/events"
    async with websockets.connect(ws_url, ping_interval=20) as ws:
        _state.ws_connected = True
        _state.last_error = ""
        log.info("JDSS WS connected → %s", ws_url)
        async for raw in ws:
            try:
                await _handle_event(json.loads(raw))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("JDSS event handling error: %s", exc)


#: JDSSArrow emits ``direction="received"`` for coalition traffic and ``"sent"``
#: for messages this gateway node originated (which includes Arrow's own
#: ``/api/publish/*`` calls). Older/other builds may use ``"in"``/``"out"`` — accept
#: both spellings for the inbound side.
_INBOUND_DIRECTIONS = frozenset({"received", "in"})


async def _handle_event(evt: dict) -> None:
    """Dispatch one live ``/ws/events`` frame."""
    _state.last_event_at = time.time()
    direction = evt.get("direction")
    if direction == "snapshot":
        _state.snapshot = evt.get("snapshot") or {}
        return
    if direction == "heartbeat":
        return
    if direction not in _INBOUND_DIRECTIONS:
        # "sent"/"out" (or any non-message frame) — skip. These include the
        # messages this node originated via Arrow's own publish calls.
        return
    # Never re-ingest a message this gateway node itself originated (e.g. an
    # Arrow-published contact that loops back over multicast) — that would echo
    # Arrow data onto its own map. Real coalition peers carry their own ids.
    own = (_state.snapshot or {}).get("node_id")
    if own and evt.get("originator_id") == own:
        return
    await _ingest_message(evt)


async def _status_poll_loop() -> None:
    """Keep ``_state.peers`` / ``_state.snapshot`` fresh for the admin panel.

    The WebSocket stream carries message events but not the peer roster, so the
    "Coalition peers" panel would otherwise stay empty while the WS is connected.
    Poll the monitor endpoints on a slow cadence, independent of the WS loop.
    """
    while True:
        try:
            if _client is not None:
                _state.peers = (await _client.get("/api/monitor/peers")).json()
                _state.snapshot = (await _client.get("/api/monitor/snapshot")).json()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("JDSS status poll failed: %s", exc)
        await asyncio.sleep(15)


async def _poll_once() -> None:
    if _client is None:
        return
    r = await _client.get("/api/messages", params={"limit": 100})
    r.raise_for_status()
    for msg in r.json():
        await _ingest_message(msg)
    # Refresh the status panel data while we're here.
    try:
        _state.snapshot = (await _client.get("/api/monitor/snapshot")).json()
        _state.peers = (await _client.get("/api/monitor/peers")).json()
    except Exception:
        pass


# ── Message normalisation + routing ───────────────────────────────────────────


def _normalise(obj: dict) -> dict:
    """Flatten either wire shape into a common view.

    Returns ``{message_id, mtype, originator_id, callsign, classification, body}``.
    """
    if "header" in obj:  # /api/messages JdssMessage shape
        header = obj.get("header") or {}
        body = obj.get("body") or {}
        return {
            "message_id": header.get("message_id"),
            "mtype": body.get("type"),
            "originator_id": header.get("originator_id"),
            "callsign": body.get("callsign"),
            "classification": header.get("classification", 0),
            "body": body,
        }
    # /ws/events _emit shape (flat)
    return {
        "message_id": obj.get("message_id"),
        "mtype": obj.get("type"),
        "originator_id": obj.get("originator_id"),
        "callsign": obj.get("callsign"),
        "classification": obj.get("classification", 0),
        "body": obj.get("body") or {},
    }


async def _ingest_message(obj: dict) -> None:
    m = _normalise(obj)
    if _mark_seen(m["message_id"]):  # deduplicate WS/poll overlap
        return
    _state.rx_messages += 1
    mtype = m["mtype"]
    if mtype == "Presence":
        await _ingest_presence(m)
    elif mtype == "Identification":
        await _ingest_presence(m)  # treat as a position/identity update
    elif mtype == "ContactSighting":
        await _ingest_contact(m)
    elif mtype == "Chat":
        await _ingest_chat(m)
    elif mtype == "CasevacRequest":
        await _ingest_casevac(m)
    elif mtype == "Sketch":
        await _ingest_sketch(m)
    elif mtype == "Overlay":
        await _ingest_overlay(m)
    else:
        log.info("JDSS %s from %s (not mapped)", mtype, m["originator_id"])


def _fallback_operator_id(db: Any) -> int | None:
    """Lowest-id operator, so an inbound message is never dropped for lack of FK."""
    from backend.storage.models import Operator

    op = db.query(Operator).order_by(Operator.id.asc()).first()
    return op.id if op else None


async def _ingest_presence(m: dict) -> None:
    """JDSS Presence/Identification → upsert a foreign CoT track."""
    import backend.storage.database as _db
    from backend.cot.cot import cot_type_to_sidc
    from backend.storage.models import CotTrack

    from backend.classification import jdss_inbound

    body = m["body"]
    loc = body.get("location") or {}
    lat, lon = loc.get("lat"), loc.get("lon")
    cot_uid = f"JDSS.{m['originator_id']}"
    callsign = m.get("callsign") or body.get("callsign") or m["originator_id"]
    cot_type = "a-f-G-U-C-I"  # friendly ground combat infantry (blue)
    level = jdss_inbound(m.get("classification"))
    battery = body.get("battery_pct")
    remarks = f"JDSS {body.get('type', '')}"
    if battery is not None:
        remarks += f" · battery {battery}%"

    with _db.SessionLocal() as db:
        track = db.query(CotTrack).filter(CotTrack.cot_uid == cot_uid).first()
        if track is None:
            track = CotTrack(cot_uid=cot_uid)
            db.add(track)
        track.cot_type = cot_type
        track.callsign = callsign
        if lat is not None:
            track.latitude = lat
        if lon is not None:
            track.longitude = lon
        track.hae = loc.get("alt_m") or 0.0
        track.remarks = remarks
        track.classification = level
        track.last_seen = datetime.now(timezone.utc)
        db.commit()
        db.refresh(track)
        payload = {
            "id": track.id,
            "cot_uid": track.cot_uid,
            "cot_type": track.cot_type,
            "sidc": cot_type_to_sidc(track.cot_type),
            "callsign": track.callsign,
            "latitude": track.latitude,
            "longitude": track.longitude,
            "hae": track.hae,
            "speed": track.speed,
            "course": track.course,
            "team": track.team,
            "remarks": track.remarks or "",
            "classification": track.classification,
            "last_seen": track.last_seen.isoformat(),
        }

    await broadcaster.broadcast(
        {"channel": "cot-track", "event": "update", "data": payload}
    )
    log.info("JDSS presence %s @ %s,%s", callsign, lat, lon)


async def _ingest_contact(m: dict) -> None:
    """JDSS ContactSighting → create an enemy/contact TacticalObject."""
    import backend.storage.database as _db
    from backend.api.schemas import TacticalObjectOut
    from backend.classification import jdss_inbound
    from backend.storage.models import TacticalObject

    body = m["body"]
    loc = body.get("location") or {}
    lat, lon = loc.get("lat"), loc.get("lon")
    if lat is None or lon is None:
        log.debug("JDSS contact dropped: no location")
        return
    affiliation = _IDENTITY_TO_AFFILIATION.get(body.get("identity"), "UNKNOWN")
    notes = body.get("description") or "JDSS contact"

    with _db.SessionLocal() as db:
        op_id = _fallback_operator_id(db)
        if op_id is None:
            log.warning("JDSS contact dropped: no operators exist to attribute it to")
            return
        obj = TacticalObject(
            type="ENEMY",
            created_by=op_id,
            latitude=lat,
            longitude=lon,
            notes=notes,
            affiliation=affiliation,
            classification=jdss_inbound(m.get("classification")),
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        data = TacticalObjectOut.model_validate(obj).model_dump(mode="json")
        mid = obj.mission_id

    await broadcaster.broadcast(
        {
            "channel": "tactical-object",
            "event": "created",
            "mission_id": mid,
            "data": data,
        }
    )
    log.info("JDSS contact (%s) @ %s,%s: %.40s", affiliation, lat, lon, notes)


async def _ingest_chat(m: dict) -> None:
    """JDSS Chat → Arrow Message on the chat channel."""
    import backend.storage.database as _db
    from backend.api.schemas import MessageOut
    from backend.storage.models import Message, Operator

    body = m["body"]
    text = body.get("text") or ""
    recipient = (body.get("recipient") or "all").strip()

    with _db.SessionLocal() as db:
        sender_id = _fallback_operator_id(db)
        if sender_id is None:
            log.warning("JDSS chat dropped: no operators exist to attribute it to")
            return
        mtype, receiver_id = "BROADCAST", None
        if recipient.lower() not in ("", "all"):
            target = (
                db.query(Operator).filter(Operator.callsign.ilike(recipient)).first()
            )
            if target is not None:
                mtype, receiver_id = "DIRECT", target.id
        from backend.classification import jdss_inbound

        msg = Message(
            sender_id=sender_id,
            content=text,
            message_type=mtype,
            receiver_id=receiver_id,
            classification=jdss_inbound(m.get("classification")),
            source="JDSS",
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        data = MessageOut.model_validate(msg).model_dump(mode="json")
        mid = msg.mission_id

    data["sender_callsign"] = m.get("callsign") or m["originator_id"]
    data["source"] = "JDSS"
    await broadcaster.broadcast(
        {"channel": "chat", "event": "message", "mission_id": mid, "data": data}
    )
    log.info("JDSS chat from %s: %.40s", data["sender_callsign"], text)


async def _ingest_casevac(m: dict) -> None:
    """JDSS CasevacRequest → a CASEVAC Report + a MEDEVAC Alert."""
    import backend.storage.database as _db
    from backend.storage.models import Alert, Report

    body = m["body"]
    loc = body.get("location") or {}
    lat, lon = loc.get("lat"), loc.get("lon")
    callsign = m.get("callsign") or m["originator_id"]

    with _db.SessionLocal() as db:
        op_id = _fallback_operator_id(db)
        if op_id is None:
            log.warning("JDSS casevac dropped: no operators exist to attribute it to")
            return
        from backend.classification import jdss_inbound

        level = jdss_inbound(m.get("classification"))
        rep = Report(
            type="CASEVAC",
            operator_id=op_id,
            payload=json.dumps(body),
            status="RECEIVED",
            classification=level,
        )
        db.add(rep)
        alert = Alert(
            type="MEDEVAC",
            operator_id=op_id,
            latitude=lat,
            longitude=lon,
            status="ACTIVE",
            classification=level,
        )
        db.add(alert)
        db.commit()
        db.refresh(rep)
        db.refresh(alert)
        rep_id, rep_mid, rep_status = rep.id, rep.mission_id, rep.status
        al_id, al_mid, al_ts = alert.id, alert.mission_id, alert.timestamp

    await broadcaster.broadcast(
        {
            "channel": "report",
            "event": "submitted",
            "mission_id": rep_mid,
            "data": {
                "id": rep_id,
                "type": "CASEVAC",
                "status": rep_status,
                "operator_id": op_id,
                "callsign": callsign,
                "sender": callsign,
                "source": "JDSS",
                "payload": json.dumps(body),
                "classification": level,
            },
        }
    )
    await broadcaster.broadcast(
        {
            "channel": "alert",
            "event": "triggered",
            "mission_id": al_mid,
            "data": {
                "id": al_id,
                "type": "MEDEVAC",
                "operator_id": op_id,
                "callsign": callsign,
                "latitude": lat,
                "longitude": lon,
                "status": "ACTIVE",
                "timestamp": al_ts.isoformat() if al_ts else None,
                "classification": level,
            },
        }
    )
    log.info(
        "JDSS casevac from %s @ %s,%s → report#%s alert#%s",
        callsign,
        lat,
        lon,
        rep_id,
        al_id,
    )


async def _upsert_shape(
    *,
    uid: str,
    cot_type: str,
    shape_type: str,
    title: str,
    callsign: str,
    geometry: dict,
    classification: int,
) -> None:
    """Upsert a JDSS-sourced drawing as an AtakShape and broadcast it.

    Reuses the existing ``atak-shape`` channel + ``AtakShape`` table so the web map
    renders JDSS Sketch/Overlay graphics through the same path as ATAK CoT drawings.
    """
    import backend.storage.database as _db
    from backend.api.schemas import AtakShapeOut
    from backend.storage.models import AtakShape

    with _db.SessionLocal() as db:
        obj = db.query(AtakShape).filter(AtakShape.uid == uid).first()
        if obj is None:
            obj = AtakShape(uid=uid)
            db.add(obj)
        obj.cot_type = cot_type
        obj.shape_type = shape_type
        obj.title = title
        obj.callsign = callsign
        obj.geometry_json = json.dumps(geometry)
        obj.classification = classification
        obj.last_seen = datetime.now(timezone.utc)
        db.commit()
        db.refresh(obj)
        data = AtakShapeOut.model_validate(obj).model_dump(mode="json")

    await broadcaster.broadcast(
        {"channel": "atak-shape", "event": "upsert", "data": data}
    )


async def _ingest_sketch(m: dict) -> None:
    """JDSS Sketch → freehand polyline AtakShape (GeoJSON LineString)."""
    from backend.classification import jdss_inbound

    body = m["body"]
    coords: list[list[float]] = []
    for p in body.get("points") or []:
        loc = p.get("location") or {}
        if loc.get("lat") is not None and loc.get("lon") is not None:
            coords.append([loc["lon"], loc["lat"]])
    if len(coords) < 2:
        log.debug("JDSS sketch dropped: fewer than 2 located points")
        return

    await _upsert_shape(
        uid=f"jdss-sketch:{m['message_id']}",
        cot_type="u-d-f",
        shape_type="LINE",
        title=body.get("title") or "sketch",
        callsign=m["originator_id"],
        geometry={"type": "LineString", "coordinates": coords},
        classification=jdss_inbound(m.get("classification")),
    )
    log.info(
        "JDSS sketch '%s' (%d pts) from %s",
        body.get("title"),
        len(coords),
        m["originator_id"],
    )


async def _ingest_overlay(m: dict) -> None:
    """JDSS Overlay → per-point SIDC symbols (custom ``SymbolSet`` geometry).

    Each ``OverlayGraphic`` keeps its own SIDC + label; the web map renders one
    milsymbol marker per point (see ``_renderAtakShape`` in ``map.html``).
    """
    from backend.classification import jdss_inbound

    body = m["body"]
    points: list[dict] = []
    for g in body.get("graphics") or []:
        loc = g.get("location") or {}
        if loc.get("lat") is None or loc.get("lon") is None:
            continue
        points.append(
            {
                "lat": loc["lat"],
                "lon": loc["lon"],
                "sidc": g.get("sidc") or "",
                "label": g.get("label") or "",
            }
        )
    if not points:
        log.debug("JDSS overlay dropped: no located graphics")
        return

    await _upsert_shape(
        uid=f"jdss-overlay:{m['message_id']}",
        cot_type="u-d-*",
        shape_type="GRAPHICS",
        title=body.get("name") or "overlay",
        callsign=m["originator_id"],
        geometry={"type": "SymbolSet", "points": points},
        classification=jdss_inbound(m.get("classification")),
    )
    log.info(
        "JDSS overlay '%s' (%d graphics) from %s",
        body.get("name"),
        len(points),
        m["originator_id"],
    )


# ── Outbound publishers (Arrow → JDSS) ────────────────────────────────────────


async def publish_operator_presence(op: Any) -> None:
    """Push an operator's position to JDSS as a Presence message."""
    if not _ready() or not _cfg.get("publish_presence", True):
        return
    if op.latitude is None or op.longitude is None:
        return
    try:
        assert _client is not None
        await _client.post(
            "/api/publish/presence",
            json={
                "lat": op.latitude,
                "lon": op.longitude,
                "callsign": op.callsign,
                "battery_pct": None,
                # Own forces are friendly — carry the affiliation so the receiving
                # client frames the symbol as friendly (blue), not the default.
                "identity": _IDENTITY_FRIEND,
            },
        )
        _state.tx_presence += 1
    except Exception as exc:
        log.debug("JDSS presence publish failed: %s", exc)


async def publish_tactical_object(obj: Any) -> None:
    """Push a tactical object to JDSS as a ContactSighting."""
    if not _ready() or not _cfg.get("publish_contacts", True):
        return
    if obj.latitude is None or obj.longitude is None:
        return
    try:
        assert _client is not None
        label = (obj.notes or obj.type or "")[:200]
        await _client.post(
            "/api/publish/contact",
            json={
                "lat": obj.latitude,
                "lon": obj.longitude,
                "description": label,
                # Structured APP-6D attributes so JDSS renders the right symbol:
                # affiliation drives the frame/colour; symbol_code is a hint the
                # gateway uses only if it is a valid 20-digit 2525D SIDC (Arrow's
                # 2525C letter codes are ignored, and JDSS builds one from identity).
                "identity": _object_identity(obj),
                "callsign": ((getattr(obj, "notes", "") or obj.type or "")[:60])
                or None,
                "sidc": getattr(obj, "symbol_code", "") or None,
            },
        )
        _state.tx_contacts += 1
    except Exception as exc:
        log.debug("JDSS contact publish failed: %s", exc)


async def publish_chat(msg: Any, sender: Any) -> None:
    """Push an Arrow chat message to JDSS as a Chat message."""
    if not _ready() or not _cfg.get("publish_chat", True):
        return
    recipient = "all"
    if msg.message_type == "DIRECT" and msg.receiver_id:
        import backend.storage.database as _db
        from backend.storage.models import Operator

        with _db.SessionLocal() as db:
            rcv = db.get(Operator, msg.receiver_id)
            if rcv is not None:
                recipient = rcv.callsign
    try:
        assert _client is not None
        await _client.post(
            "/api/publish/chat",
            json={"text": msg.content, "recipient": recipient},
        )
        _state.tx_chat += 1
    except Exception as exc:
        log.debug("JDSS chat publish failed: %s", exc)
