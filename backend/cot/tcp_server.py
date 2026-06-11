"""Native CoT TCP server — ATAK devices connect directly on port 8087.

Each ATAK connection is tracked with metadata (IP, callsign, last CoT type,
message counts) exposed via ``get_status()`` for the admin UI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

from backend.cot.cot import CotEvent, cot_type_to_sidc, parse_cot, parse_medevac, role_to_cot_type
from backend.storage.database import SessionLocal
from backend.storage.models import Alert, CotTrack, Operator, Report
from backend.websocket.manager import broadcaster

log = logging.getLogger("backend.cot.tcp")

_END_TAG  = b"</event>"
_CFG_FILE = Path("data/tak_cot_config.json")

# ── Persistent config ─────────────────────────────────────────────────────────

_cfg: dict = {
    "enabled":   True,
    "host":      "0.0.0.0",
    "port":      int(os.environ.get("ARROW_COT_TCP_PORT", "8087")),
    "tak_host":  "",          # upstream TAK server (optional)
    "tak_port":  8087,
    "tak_ssl":   False,
    "note":      "ATAK devices connect to this server's IP on the configured port.",
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


# ── Connected client record ───────────────────────────────────────────────────

@dataclass
class ClientInfo:
    uid:          str
    ip:           str
    port:         int
    callsign:     str  = ""
    cot_type:     str  = ""
    last_lat:     float = 0.0
    last_lon:     float = 0.0
    platform:     str  = ""
    connected_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    rx_count:     int  = 0
    tx_count:     int  = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["connected_ago_s"] = int(time.time() - self.connected_at)
        d["last_seen_ago_s"] = int(time.time() - self.last_seen_at)
        return d


# ── Connection pool ───────────────────────────────────────────────────────────

class _Pool:
    _writers: dict[str, asyncio.StreamWriter] = {}
    _clients: dict[str, ClientInfo]           = {}
    _total_rx: int = 0
    _total_tx: int = 0
    _total_conns: int = 0

    @classmethod
    def add(cls, info: ClientInfo, writer: asyncio.StreamWriter) -> None:
        cls._writers[info.uid] = writer
        cls._clients[info.uid] = info
        cls._total_conns += 1
        log.info("ATAK connect: %s %s:%d  (total=%d)", info.uid, info.ip, info.port, cls.count())

    @classmethod
    def remove(cls, uid: str) -> None:
        cls._writers.pop(uid, None)
        cls._clients.pop(uid, None)
        log.info("ATAK disconnect: %s  (total=%d)", uid, cls.count())

    @classmethod
    def update(cls, uid: str, evt: "CotEvent") -> None:
        c = cls._clients.get(uid)
        if c:
            c.callsign    = evt.callsign or c.callsign
            c.cot_type    = evt.cot_type
            c.last_lat    = evt.lat
            c.last_lon    = evt.lon
            c.platform    = evt.platform
            c.last_seen_at = time.time()
            c.rx_count    += 1
        cls._total_rx += 1

    @classmethod
    async def broadcast(cls, data: bytes, exclude: str = "") -> int:
        dead: list[str] = []
        sent = 0
        for uid, w in list(cls._writers.items()):
            if uid == exclude:
                continue
            try:
                w.write(data)
                await w.drain()
                sent += 1
                c = cls._clients.get(uid)
                if c:
                    c.tx_count += 1
            except Exception:
                dead.append(uid)
        cls._total_tx += sent
        for uid in dead:
            cls.remove(uid)
        return sent

    @classmethod
    def count(cls) -> int:
        return len(cls._writers)

    @classmethod
    def client_list(cls) -> list[dict]:
        return [c.to_dict() for c in cls._clients.values()]

    @classmethod
    def stats(cls) -> dict:
        return {
            "connected": cls.count(),
            "total_connections": cls._total_conns,
            "total_rx": cls._total_rx,
            "total_tx": cls._total_tx,
        }


# ── Frame buffer ──────────────────────────────────────────────────────────────

class _FrameBuf:
    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self._buf += data
        frames: list[bytes] = []
        while True:
            idx = self._buf.find(_END_TAG)
            if idx == -1:
                break
            end  = idx + len(_END_TAG)
            raw  = bytes(self._buf[:end])
            self._buf = self._buf[end:]
            start = raw.find(b"<event")
            if start == -1:
                start = raw.find(b"<?xml")
            if start > 0:
                raw = raw[start:]
            if raw:
                frames.append(raw)
        return frames


# ── CoT routing ───────────────────────────────────────────────────────────────

async def _handle_frame(raw: bytes, sender_uid: str) -> None:
    try:
        evt = parse_cot(raw)
    except Exception as exc:
        log.debug("parse error: %s", exc)
        return

    _Pool.update(sender_uid, evt)

    # ATAK 9-line MEDEVAC / CASEVAC request → persist a Report + raise an Alert,
    # then relay the raw frame on to other ATAK clients. It is not a position fix,
    # so skip the operator/track persistence below.
    med = parse_medevac(raw)
    if med is not None:
        await _handle_medevac(med)
        await _Pool.broadcast(raw, exclude=sender_uid)
        return

    with SessionLocal() as db:
        op: Operator | None = None
        if evt.callsign:
            op = db.query(Operator).filter(
                Operator.callsign.ilike(evt.callsign)
            ).first()

        if op:
            # ── Own-position path ────────────────────────────────────────
            op.latitude  = evt.lat
            op.longitude = evt.lon
            op.altitude  = evt.hae
            op.last_seen = datetime.now(timezone.utc)
            op.status    = "ONLINE"
            op.position_source = "ATAK"   # fix arrived from an ATAK device over CoT TCP
            db.commit()
            db.refresh(op)
            cot_type = role_to_cot_type(op.role)
            await broadcaster.broadcast({
                "channel": "tracking", "event": "position",
                "cot_xml": CotEvent(
                    uid=f"ARROW.{op.callsign}", cot_type=cot_type,
                    lat=op.latitude, lon=op.longitude, hae=op.altitude or 0.0,
                    callsign=op.callsign, role=op.role,
                    speed=evt.speed, course=evt.course,
                ).to_xml_str(),
                "data": {
                    "operator_id": op.id, "callsign": op.callsign,
                    "latitude": op.latitude, "longitude": op.longitude,
                    "altitude": op.altitude, "team_id": op.team_id,
                    "cot_type": cot_type, "position_source": "ATAK",
                },
            })
        else:
            # ── Foreign entity path ──────────────────────────────────────
            track = db.query(CotTrack).filter(CotTrack.cot_uid == evt.uid).first()
            if track is None:
                track = CotTrack(cot_uid=evt.uid)
                db.add(track)
            track.cot_type  = evt.cot_type
            track.callsign  = evt.callsign or evt.uid
            track.latitude  = evt.lat
            track.longitude = evt.lon
            track.hae       = evt.hae
            track.speed     = evt.speed
            track.course    = evt.course
            track.team      = evt.team
            track.last_seen = datetime.now(timezone.utc)
            db.commit()
            db.refresh(track)
            await broadcaster.broadcast({
                "channel": "cot-track", "event": "update",
                "data": {
                    "id": track.id, "cot_uid": track.cot_uid,
                    "cot_type": track.cot_type,
                    "sidc": cot_type_to_sidc(track.cot_type),
                    "callsign": track.callsign,
                    "latitude": track.latitude, "longitude": track.longitude,
                    "hae": track.hae, "speed": track.speed, "course": track.course,
                    "team": track.team, "last_seen": track.last_seen.isoformat(),
                },
            })

    # Relay to other ATAK clients
    await _Pool.broadcast(raw, exclude=sender_uid)


# ── MEDEVAC handling ──────────────────────────────────────────────────────────

def _resolve_operator_id(db, callsign: str | None) -> int | None:
    """Map an ATAK callsign to an Operator row (Report/Alert need a valid FK).

    Falls back to the lowest-id operator so an inbound MEDEVAC is never dropped
    just because the requesting device isn't a registered operator.
    """
    op = None
    if callsign:
        op = db.query(Operator).filter(Operator.callsign.ilike(callsign)).first()
    if op is None:
        op = db.query(Operator).order_by(Operator.id.asc()).first()
    return op.id if op else None


async def _handle_medevac(med: dict) -> None:
    """Persist an ATAK MEDEVAC/CASEVAC as a Report + Alert and broadcast both."""
    rtype = med.get("type", "MEDEVAC")
    lat   = med.get("latitude")
    lon   = med.get("longitude")

    with SessionLocal() as db:
        op_id = _resolve_operator_id(db, med.get("callsign"))
        if op_id is None:
            log.warning("MEDEVAC dropped: no operators exist to attribute it to")
            return
        rep = Report(type=rtype, operator_id=op_id,
                     payload=json.dumps(med), status="RECEIVED")
        db.add(rep)
        alert = Alert(type="MEDEVAC", operator_id=op_id,
                      latitude=lat, longitude=lon, status="ACTIVE")
        db.add(alert)
        db.commit()
        db.refresh(rep)
        db.refresh(alert)
        callsign  = med.get("callsign") or "ATAK"
        rep_id, rep_mid, rep_status = rep.id, rep.mission_id, rep.status
        al_id, al_mid, al_ts = alert.id, alert.mission_id, alert.timestamp

    await broadcaster.broadcast({
        "channel": "report", "event": "submitted", "mission_id": rep_mid,
        "data": {
            "id": rep_id, "type": rtype, "status": rep_status,
            "operator_id": op_id, "callsign": callsign, "sender": callsign,
            "source": "ATAK", "payload": json.dumps(med),
        },
    })
    await broadcaster.broadcast({
        "channel": "alert", "event": "triggered", "mission_id": al_mid,
        "data": {
            "id": al_id, "type": "MEDEVAC", "operator_id": op_id,
            "callsign": callsign, "latitude": lat, "longitude": lon,
            "status": "ACTIVE", "timestamp": al_ts.isoformat() if al_ts else None,
        },
    })
    log.info("ATAK %s from %s at %s,%s → report#%s alert#%s",
             rtype, callsign, lat, lon, rep_id, al_id)


# ── Per-client handler ────────────────────────────────────────────────────────

async def _client_handler(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
) -> None:
    peer = writer.get_extra_info("peername", ("?", 0))
    uid  = f"atak-{peer[0]}-{peer[1]}"
    info = ClientInfo(uid=uid, ip=str(peer[0]), port=int(peer[1]))
    _Pool.add(info, writer)

    # Welcome presence
    presence = CotEvent(
        uid="ARROW.SERVER", cot_type="a-f-G-U-C-O",
        lat=0.0, lon=0.0, callsign="ARROW", platform="Arrow",
    )
    try:
        writer.write(presence.to_xml())
        await writer.drain()
    except Exception:
        _Pool.remove(uid)
        return

    # Push current operator snapshot
    asyncio.create_task(_push_snapshot(writer))

    buf = _FrameBuf()
    try:
        while True:
            data = await asyncio.wait_for(reader.read(8192), timeout=120)
            if not data:
                break
            for frame in buf.feed(data):
                await _handle_frame(frame, uid)
    except asyncio.TimeoutError:
        try:
            writer.write(presence.to_xml())
            await writer.drain()
        except Exception:
            pass
    except Exception as exc:
        log.debug("client %s error: %s", uid, exc)
    finally:
        _Pool.remove(uid)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _push_snapshot(writer: asyncio.StreamWriter) -> None:
    try:
        with SessionLocal() as db:
            ops = db.query(Operator).filter(
                Operator.latitude.isnot(None),
                Operator.longitude.isnot(None),
            ).all()
            for op in ops:
                writer.write(CotEvent(
                    uid=f"ARROW.{op.callsign}",
                    cot_type=role_to_cot_type(op.role),
                    lat=op.latitude, lon=op.longitude,
                    hae=op.altitude or 0.0,
                    callsign=op.callsign, role=op.role, platform="Arrow",
                ).to_xml())
            await writer.drain()
    except Exception as exc:
        log.debug("snapshot error: %s", exc)


# ── Public helpers ────────────────────────────────────────────────────────────

async def broadcast_operator_cot(op: Operator) -> None:
    """Push an operator's position to all connected ATAK clients (called by tracking router)."""
    if _Pool.count() == 0:
        return
    await _Pool.broadcast(CotEvent(
        uid=f"ARROW.{op.callsign}",
        cot_type=role_to_cot_type(op.role),
        lat=op.latitude or 0.0, lon=op.longitude or 0.0,
        hae=op.altitude or 0.0,
        callsign=op.callsign, role=op.role, platform="Arrow",
    ).to_xml())


def get_status() -> dict:
    """Return full TAK server status for the admin UI."""
    return {
        "enabled":  _cfg.get("enabled", True),
        "host":     _cfg.get("host", "0.0.0.0"),
        "port":     _cfg.get("port", 8087),
        "running":  _server is not None,
        "tak_host": _cfg.get("tak_host", ""),
        "tak_port": _cfg.get("tak_port", 8087),
        "tak_ssl":  _cfg.get("tak_ssl", False),
        **_Pool.stats(),
        "clients": _Pool.client_list(),
    }


# ── Lifecycle ─────────────────────────────────────────────────────────────────

_server: asyncio.Server | None = None


async def start() -> None:
    global _server
    load_config()
    if not _cfg.get("enabled", True):
        log.info("CoT TCP server disabled in config")
        return
    host = _cfg.get("host", "0.0.0.0")
    port = int(_cfg.get("port", 8087))
    _server = await asyncio.start_server(_client_handler, host, port)
    log.info("CoT TCP server listening on %s:%d — ATAK devices connect here", host, port)


async def stop() -> None:
    global _server
    if _server:
        _server.close()
        await _server.wait_closed()
        _server = None
        log.info("CoT TCP server stopped")


def connected_clients() -> int:
    return _Pool.count()
