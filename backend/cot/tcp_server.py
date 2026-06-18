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
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

from backend.cot.cot import (
    ALL_CHAT_ROOMS, PHOTO_COT_MAX_BYTES, CotEvent, build_fileshare, build_geochat,
    build_image_cot, cot_type_to_sidc, is_arrow_fileshare, is_arrow_geochat,
    is_arrow_photo, parse_atak_shape, parse_cot, parse_cot_image, parse_emergency,
    parse_fileshare, parse_fileshare_announcement, parse_geochat, parse_medevac,
    parse_spot_report, role_to_cot_type,
)
from backend.storage.database import SessionLocal
from backend.storage.models import (
    Alert, AtakShape, ChatRoom, ChatRoomMember, CotTrack, Message, Operator, Photo,
    Report, TacticalObject,
)
from backend.websocket.manager import broadcaster

log = logging.getLogger("backend.cot.tcp")

_END_TAG  = b"</event>"
_CFG_FILE = Path("data/tak_cot_config.json")


def _stream_frame(data: bytes) -> bytes:
    """Normalise a CoT blob into a bare stream frame for ATAK.

    lxml emits ``<?xml …?>\\n<event>…`` per event. Concatenated into a TCP
    stream those repeated XML prologs are malformed CoT — ATAK parses the first
    event and rejects the rest, so nothing past it shows. Strip any leading
    declaration so the wire carries only ``<event>…</event>`` frames.
    """
    i = data.find(b"<event")
    return data[i:] if i > 0 else data

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
        log.info("ATAK connect: %s %s:%d  (total=%d)", info.uid, info.ip, info.port, cls.count(),
                 extra={"cat": "connections"})

    @classmethod
    def remove(cls, uid: str) -> None:
        cls._writers.pop(uid, None)
        cls._clients.pop(uid, None)
        log.info("ATAK disconnect: %s  (total=%d)", uid, cls.count(),
                 extra={"cat": "connections"})

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
        data = _stream_frame(data)
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

    # Emergency button
    emerg = parse_emergency(raw)
    if emerg is not None:
        await _handle_emergency(emerg)
        await _Pool.broadcast(raw, exclude=sender_uid)
        return

    # Spot/contact report (non-MEDEVAC b-r-f-*)
    spot = parse_spot_report(raw)
    if spot is not None:
        await _handle_spot_report(spot)
        await _Pool.broadcast(raw, exclude=sender_uid)
        return

    # File share announcement (b-f-t-a)
    fsa = parse_fileshare_announcement(raw)
    if fsa is not None:
        sender_ip = _Pool._clients.get(sender_uid)
        ip = sender_ip.ip if sender_ip else ""
        # Resolve relative URL using sender IP if needed
        if not fsa["url"].startswith("http"):
            fsa["url"] = f"http://{ip}:8080/Attachment/{fsa['filename']}"
        asyncio.create_task(_handle_fileshare_announcement(fsa, ip))
        await _Pool.broadcast(raw, exclude=sender_uid)
        return

    # ATAK drawn shape / route
    shape = parse_atak_shape(raw)
    if shape is not None:
        await _handle_atak_shape(shape)
        await _Pool.broadcast(raw, exclude=sender_uid)
        return

    # ATAK 9-line MEDEVAC / CASEVAC request → persist a Report + raise an Alert,
    # then relay the raw frame on to other ATAK clients. It is not a position fix,
    # so skip the operator/track persistence below.
    med = parse_medevac(raw)
    if med is not None:
        await _handle_medevac(med)
        await _Pool.broadcast(raw, exclude=sender_uid)
        return

    # ATAK GeoChat → Arrow chat message. Relay to other ATAK clients too.
    chat = parse_geochat(raw)
    if chat is not None:
        if not is_arrow_geochat(chat):   # ignore our own outbound echoed back
            await _handle_geochat(chat)
        await _Pool.broadcast(raw, exclude=sender_uid)
        return

    # ATAK file-share (binary attachment transfer) → store centrally + pin a POI.
    fs = parse_fileshare(raw)
    if fs is not None:
        if not is_arrow_fileshare(fs):   # ignore our own outbound echoed back
            await _handle_fileshare(fs)
        await _Pool.broadcast(raw, exclude=sender_uid)
        return

    # ATAK photo (point CoT with embedded base64 image — legacy) → store + pin.
    img = parse_cot_image(raw)
    if img is not None:
        if not is_arrow_photo(img):      # ignore our own outbound echoed back
            await _handle_cot_image(img)
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
            track.remarks   = evt.remarks if hasattr(evt, 'remarks') else None
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
                    "team": track.team, "remarks": track.remarks or "",
                    "last_seen": track.last_seen.isoformat(),
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


# ── Chat bridge (ATAK GeoChat ↔ Arrow messaging) ──────────────────────────────

async def _handle_geochat(chat: dict) -> None:
    """Persist an inbound ATAK GeoChat as an Arrow Message + broadcast on `chat`.

    Routing by chatroom name:
      • "All Chat Rooms"            → BROADCAST
      • name matching an operator   → DIRECT to that operator
      • any other named room        → ROOM (get-or-create a ChatRoom, ATAK origin)
    """
    from backend.api.schemas import MessageOut
    from backend.chatrooms.router import add_member, get_or_create_room, room_out

    room_name = (chat.get("chatroom") or ALL_CHAT_ROOMS).strip()
    text = chat["text"]
    created_room: int | None = None

    with SessionLocal() as db:
        sender_id = _resolve_operator_id(db, chat.get("sender_callsign"))
        if sender_id is None:
            log.warning("GeoChat dropped: no operators exist to attribute it to")
            return

        mtype, receiver_id, chatroom_id = "BROADCAST", None, None
        if room_name.lower() != ALL_CHAT_ROOMS.lower():
            target = db.query(Operator).filter(Operator.callsign.ilike(room_name)).first()
            if target is not None:
                mtype, receiver_id = "DIRECT", target.id
            else:
                existing = db.query(ChatRoom).filter(ChatRoom.name.ilike(room_name)).first()
                room = existing or get_or_create_room(db, room_name, sender_id, origin="ATAK")
                add_member(db, room.id, sender_id)
                mtype, chatroom_id = "ROOM", room.id
                if existing is None:
                    created_room = room.id

        msg = Message(sender_id=sender_id, content=text, message_type=mtype,
                      receiver_id=receiver_id, chatroom_id=chatroom_id)
        db.add(msg)
        db.commit()
        db.refresh(msg)
        data = MessageOut.model_validate(msg).model_dump(mode="json")
        mid  = msg.mission_id

    # Surface the original ATAK callsign + source so clients can label it even
    # when the sender isn't a registered operator (sender_id is a fallback then).
    data["sender_callsign"] = chat.get("sender_callsign")
    data["source"] = "ATAK"
    await broadcaster.broadcast({
        "channel": "chat", "event": "message", "mission_id": mid, "data": data,
    })
    if created_room is not None:   # new ATAK room → tell clients to refresh
        with SessionLocal() as db:
            r = db.get(ChatRoom, created_room)
            if r is not None:
                await broadcaster.broadcast({
                    "channel": "chat", "event": "room_created",
                    "mission_id": r.mission_id, "data": room_out(db, r),
                })
    log.info("ATAK GeoChat from %s in '%s': %.40s",
             chat.get("sender_callsign"), room_name, text)


async def broadcast_chat_to_atak(msg: Message, sender: Operator) -> None:
    """Forward an Arrow chat message to connected ATAK clients as GeoChat.

    BROADCAST / group chat goes to the shared "All Chat Rooms"; a DIRECT message
    is routed privately to the recipient's callsign room. Called by the messaging
    router after it persists + broadcasts on the `chat` channel.
    """
    if _Pool.count() == 0:
        return

    import os
    image_url: str | None = None
    if msg.photo_id:
        base = os.environ.get("ARROW_BACKEND_URL", "http://127.0.0.1:6001")
        image_url = f"{base}/photos/{msg.photo_id}"

    room = ALL_CHAT_ROOMS
    recipient_uid: str | None = None
    member_uids: list[str] | None = None
    if msg.message_type == "DIRECT":
        if not msg.receiver_id:
            return  # private message with no addressable recipient
        with SessionLocal() as db:
            rcv = db.get(Operator, msg.receiver_id)
        if rcv is None:
            return
        room = rcv.callsign
        recipient_uid = f"ARROW.{rcv.callsign}"
    elif msg.message_type == "ROOM":
        if not msg.chatroom_id:
            return
        with SessionLocal() as db:
            r = db.get(ChatRoom, msg.chatroom_id)
            if r is None:
                return
            room = r.name
            rows = (db.query(Operator.callsign)
                      .join(ChatRoomMember, ChatRoomMember.operator_id == Operator.id)
                      .filter(ChatRoomMember.chatroom_id == r.id).all())
            member_uids = [f"ARROW.{cs}" for (cs,) in rows if cs]

    cot = build_geochat(
        sender_callsign=sender.callsign, text=msg.content,
        room=room, recipient_uid=recipient_uid, member_uids=member_uids,
        image_url=image_url,
    )
    await _Pool.broadcast(cot)


# ── Emergency / panic button ──────────────────────────────────────────────────

async def _handle_emergency(emerg: dict) -> None:
    """Persist an ATAK emergency alert and broadcast on the alert channel."""
    lat, lon = emerg.get("lat", 0.0), emerg.get("lon", 0.0)
    active   = emerg.get("active", True)
    with SessionLocal() as db:
        op_id = _resolve_operator_id(db, emerg.get("callsign"))
        if op_id is None:
            return
        if active:
            alert = Alert(
                type="ATAK_EMERGENCY", operator_id=op_id,
                latitude=lat, longitude=lon, status="ACTIVE",
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)
            al_id, al_ts, al_mid = alert.id, alert.timestamp, alert.mission_id
        else:
            # Cancel: mark the most recent active emergency for this operator as RESOLVED
            alert = db.query(Alert).filter(
                Alert.operator_id == op_id,
                Alert.type == "ATAK_EMERGENCY",
                Alert.status == "ACTIVE",
            ).order_by(Alert.id.desc()).first()
            if alert:
                alert.status = "RESOLVED"
                db.commit()
                al_id, al_ts, al_mid = alert.id, alert.timestamp, alert.mission_id
            else:
                return

    callsign = emerg.get("callsign","ATAK")
    await broadcaster.broadcast({
        "channel": "alert", "event": "triggered" if active else "ack",
        "mission_id": al_mid,
        "data": {
            "id": al_id, "type": "ATAK_EMERGENCY",
            "operator_id": op_id, "callsign": callsign,
            "latitude": lat, "longitude": lon,
            "status": "ACTIVE" if active else "RESOLVED",
            "timestamp": al_ts.isoformat() if al_ts else None,
        },
    })
    log.info("ATAK emergency %s from %s", "ACTIVE" if active else "RESOLVED", callsign)


# ── Spot / contact report ─────────────────────────────────────────────────────

async def _handle_spot_report(spot: dict) -> None:
    """Persist an ATAK spot/contact report and broadcast on the report channel."""
    with SessionLocal() as db:
        op_id = _resolve_operator_id(db, spot.get("callsign"))
        if op_id is None:
            return
        rep = Report(
            type="CONTACT_REPORT", operator_id=op_id,
            payload=json.dumps(spot), status="RECEIVED",
        )
        db.add(rep)
        db.commit()
        db.refresh(rep)
        rep_id, rep_mid, rep_status = rep.id, rep.mission_id, rep.status

    callsign = spot.get("callsign","ATAK")
    await broadcaster.broadcast({
        "channel": "report", "event": "submitted", "mission_id": rep_mid,
        "data": {
            "id": rep_id, "type": "CONTACT_REPORT", "status": rep_status,
            "operator_id": op_id, "callsign": callsign,
            "source": "ATAK", "payload": json.dumps(spot),
        },
    })
    log.info("ATAK spot report from %s: %.60s", callsign, spot.get("remarks",""))


# ── File share announcement (b-f-t-a) ────────────────────────────────────────

async def _handle_fileshare_announcement(fs: dict, sender_ip: str) -> None:
    """Download an ATAK file-share attachment, store as Photo, post as chat."""
    url = fs.get("url","")
    if not url:
        return
    # Download the file (ATAK serves on port 8080)
    import urllib.request
    import urllib.error
    try:
        loop = asyncio.get_event_loop()
        def _dl():
            req = urllib.request.Request(url, headers={"User-Agent": "ArrowServer/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read()
        raw = await loop.run_in_executor(None, _dl)
    except Exception as exc:
        log.warning("ATAK fileshare announcement download failed (%s): %s", url, exc)
        return

    mime      = fs.get("mime","image/jpeg")
    filename  = fs.get("filename","photo")
    sender_cs = fs.get("sender_callsign","ATAK")

    from backend.photos.router import store_photo_bytes
    with SessionLocal() as db:
        op_id = _resolve_operator_id(db, sender_cs)
        if op_id is None:
            return
        photo = store_photo_bytes(db, raw, mime, op_id, filename)
        msg = Message(
            sender_id=op_id,
            content=f"[ATAK photo from {sender_cs}]",
            message_type="BROADCAST",
            photo_id=photo.id,
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        from backend.api.schemas import MessageOut
        data     = MessageOut.model_validate(msg).model_dump(mode="json")
        mid      = msg.mission_id
        photo_id = photo.id   # capture before session closes

    data["sender_callsign"] = sender_cs
    data["source"] = "ATAK"
    await broadcaster.broadcast({
        "channel": "chat", "event": "message", "mission_id": mid, "data": data,
    })
    log.info("ATAK fileshare announcement from %s stored as photo#%s", sender_cs, photo_id)


# ── ATAK drawn shapes ─────────────────────────────────────────────────────────

async def _handle_atak_shape(shape: dict) -> None:
    """Upsert an ATAK drawn shape and broadcast on the atak-shape channel."""
    with SessionLocal() as db:
        obj = db.query(AtakShape).filter(AtakShape.uid == shape["uid"]).first()
        if obj is None:
            obj = AtakShape(uid=shape["uid"])
            db.add(obj)
        obj.cot_type      = shape["cot_type"]
        obj.shape_type    = shape["shape_type"]
        obj.title         = shape["title"]
        obj.callsign      = shape["callsign"]
        obj.geometry_json = shape["geometry_json"]
        obj.last_seen     = datetime.now(timezone.utc)
        db.commit()
        db.refresh(obj)
        shape_id = obj.id

    await broadcaster.broadcast({
        "channel": "atak-shape", "event": "upsert",
        "data": {
            "id": shape_id, "uid": shape["uid"],
            "cot_type": shape["cot_type"], "shape_type": shape["shape_type"],
            "title": shape["title"], "callsign": shape["callsign"],
            "geometry_json": shape["geometry_json"],
        },
    })
    log.info("ATAK shape %s (%s) from %s", shape["uid"], shape["shape_type"], shape["callsign"])


# ── Photo bridge (geo-pinned images, ATAK ↔ Arrow) ────────────────────────────

def _guess_mime(filename: str | None) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "gif": "image/gif", "webp": "image/webp", "mp4": "video/mp4"}.get(ext, "image/jpeg")


def _create_photo_poi(db, photo: Photo, lat: float, lon: float, caption: str, op_id: int):
    """Create a POI tactical object pinned to a stored photo. Returns (data, mid, ids)."""
    from backend.api.schemas import TacticalObjectOut
    obj = TacticalObject(
        type="POI", symbol_code="", created_by=op_id,
        latitude=lat, longitude=lon, notes=caption or "ATAK photo",
        photo_id=photo.id, affiliation="FRIENDLY",
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return (TacticalObjectOut.model_validate(obj).model_dump(mode="json"),
            obj.mission_id, photo.id, obj.id)


async def _handle_cot_image(img: dict) -> None:
    """Inbound ATAK photo embedded as base64 (legacy) → store binary + pin a POI."""
    from backend.photos.router import store_photo_bytes
    with SessionLocal() as db:
        op_id = _resolve_operator_id(db, img.get("callsign"))
        if op_id is None:
            log.warning("ATAK photo dropped: no operators exist to attribute it to")
            return
        photo = store_photo_bytes(db, img["image_bytes"], img.get("mime") or "image/jpeg",
                                  uploaded_by=op_id, original_name=img.get("caption") or "atak-photo")
        data, mid, pid, oid = _create_photo_poi(db, photo, img["lat"], img["lon"],
                                                img.get("caption"), op_id)
    await broadcaster.broadcast({
        "channel": "tactical-object", "event": "created", "mission_id": mid, "data": data,
    })
    log.info("ATAK photo (base64) from %s → photo#%s poi#%s", img.get("callsign"), pid, oid)


def _fetch_binary(url: str) -> bytes | None:
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=15) as r:  # noqa: S310 — TAK file fetch
            return r.read()
    except Exception as exc:
        log.debug("fileshare fetch failed (%s): %s", url, exc)
        return None


async def _handle_fileshare(fs: dict) -> None:
    """Inbound TAK file-share → ensure the binary is stored centrally + pin a POI.

    The file is normally already in our store (ATAK POSTed it to /Marti/sync/upload
    before sending the CoT); otherwise we fetch it from senderUrl. Either way the
    photo ends up in the server's central store.
    """
    from backend.photos.router import find_photo_by_hash, store_photo_bytes
    sha = fs.get("sha256") or ""
    with SessionLocal() as db:
        op_id = _resolve_operator_id(db, fs.get("sender_callsign"))
        if op_id is None:
            return
        photo = find_photo_by_hash(db, sha) if sha else None
        if photo is None:
            raw = _fetch_binary(fs.get("url"))
            if not raw:
                log.info("ATAK fileshare %s: binary not in store and senderUrl unfetchable",
                         sha[:12] or "?")
                return
            photo = store_photo_bytes(db, raw, _guess_mime(fs.get("filename")),
                                      uploaded_by=op_id, original_name=fs.get("filename") or "atak-file")
        # Only pin a POI when the share carries a real location.
        lat, lon = fs.get("lat") or 0.0, fs.get("lon") or 0.0
        if lat or lon:
            data, mid, pid, oid = _create_photo_poi(db, photo, lat, lon, fs.get("filename"), op_id)
        else:
            data = mid = pid = oid = None
        photo_id_v = photo.id
    if data is not None:
        await broadcaster.broadcast({
            "channel": "tactical-object", "event": "created", "mission_id": mid, "data": data,
        })
    log.info("ATAK fileshare from %s → stored photo#%s (poi=%s)",
             fs.get("sender_callsign"), photo_id_v, oid)


async def broadcast_photo_to_atak(obj: TacticalObject, sender: Operator) -> None:
    """Forward an Arrow geo-pinned photo to ATAK as a binary TAK file-share."""
    from backend.marti.router import content_url
    from backend.photos.router import ensure_photo_hash, read_photo_bytes
    if _Pool.count() == 0 or not obj.photo_id:
        return
    lat, lon, notes = obj.latitude, obj.longitude, obj.notes or ""
    with SessionLocal() as db:
        photo = db.get(Photo, obj.photo_id)
        if photo is None:
            return
        sha   = ensure_photo_hash(db, photo)
        raw   = read_photo_bytes(photo)
        fname = photo.original_name or f"photo_{photo.id}.jpg"
    if not sha or raw is None:
        return
    cot = build_fileshare(
        filename=fname, sha256=sha, size_bytes=len(raw), url=content_url(sha),
        sender_callsign=sender.callsign, lat=lat, lon=lon, caption=notes,
    )
    await _Pool.broadcast(cot)


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
        writer.write(_stream_frame(presence.to_xml()))
        await writer.drain()
    except Exception:
        _Pool.remove(uid)
        return

    # Push current operator snapshot
    asyncio.create_task(_push_snapshot(writer))
    asyncio.create_task(broadcaster.broadcast({
        "channel": "cot-presence", "event": "connected",
        "data": info.to_dict(),
    }))

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
            writer.write(_stream_frame(presence.to_xml()))
            await writer.drain()
        except Exception:
            pass
    except Exception as exc:
        log.debug("client %s error: %s", uid, exc)
    finally:
        _Pool.remove(uid)
        asyncio.create_task(broadcaster.broadcast({
            "channel": "cot-presence", "event": "disconnected",
            "data": {"uid": uid},
        }))
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _push_snapshot(writer: asyncio.StreamWriter) -> None:
    """On ATAK connect, replay the current picture: operator positions AND every
    tactical object (enemies, POIs, objectives, markers) placed from the web/app —
    otherwise a freshly-connected device shows none of the existing map elements."""
    try:
        with SessionLocal() as db:
            for op in db.query(Operator).all():
                writer.write(_stream_frame(CotEvent(
                    uid=f"ARROW.{op.callsign}",
                    cot_type=role_to_cot_type(op.role),
                    lat=op.latitude or 0.0, lon=op.longitude or 0.0,
                    hae=op.altitude or 0.0,
                    callsign=op.callsign, role=op.role, platform="Arrow",
                ).to_xml()))
            # Replay existing tactical objects so the web map picture appears in ATAK.
            for obj in db.query(TacticalObject).all():
                if obj.latitude is None or obj.longitude is None:
                    continue
                try:
                    writer.write(_stream_frame(_tactical_object_to_cot(obj)))
                except Exception as exc:
                    log.debug("snapshot TO #%s skipped: %s", obj.id, exc)
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


# ── Tactical-object ↔ ATAK bridge ────────────────────────────────────────────
# Tactical objects placed from the web map (enemies, POIs, objectives, friendly
# markers, etc.) are forwarded to connected ATAK clients as standard CoT
# events so the radio operator sees them in ATAK alongside the operators'
# positions.  We pick a CoT type from the SIDC if present, otherwise infer it
# from the type+affiliation.

from backend.cot.cot import sidc_to_cot_type   # noqa: E402  (late import to avoid cycle)

_TO_TYPE_FALLBACK = {
    # type-name        affiliation → cot type
    "ENEMY":      {"HOSTILE": "a-h-G-U-C-I", "FRIENDLY": "a-f-G-U-C",
                   "UNKNOWN": "a-u-G",       "NEUTRAL":  "a-n-G"},
    "POI":        {"FRIENDLY": "a-n-G-I-N",  "HOSTILE":  "a-h-G",
                   "UNKNOWN":  "a-u-G",      "NEUTRAL":  "a-n-G"},
    "OBJECTIVE":  {"FRIENDLY": "a-f-G-U-C-O","HOSTILE":  "a-h-G-U-C",
                   "UNKNOWN":  "a-u-G",      "NEUTRAL":  "a-n-G"},
    "MARKER":     {"FRIENDLY": "a-f-G",      "HOSTILE":  "a-h-G",
                   "UNKNOWN":  "a-u-G",      "NEUTRAL":  "a-n-G"},
}


_AFF_CHAR = {"FRIENDLY": "f", "ASSUMED_FRIEND": "f", "HOSTILE": "h",
             "ENEMY": "h", "NEUTRAL": "n", "UNKNOWN": "u"}


def _tactical_object_cot_type(obj: "TacticalObject") -> str:
    """Pick the best CoT type for a TacticalObject row.

    The affiliation must always survive the trip to ATAK: an object marked
    HOSTILE has to arrive hostile (red), never unknown (yellow). So when there's
    no exact symbol/type match we fall back to a generic ground type carrying the
    object's affiliation (a-h-G), not 'a-u-G'.
    """
    aff = (obj.affiliation or "FRIENDLY").upper()
    if obj.symbol_code:
        return sidc_to_cot_type(obj.symbol_code)
    explicit = _TO_TYPE_FALLBACK.get(obj.type, {}).get(aff)
    if explicit:
        return explicit
    return f"a-{_AFF_CHAR.get(aff, 'u')}-G"


def _tactical_object_to_cot(obj: "TacticalObject", *, stale: bool = False) -> bytes:
    """Build a CoT XML frame for a TacticalObject.  When `stale=True`, sets the
    stale timestamp to NOW so ATAK drops the marker (used for delete)."""
    from datetime import timedelta as _td
    now = datetime.now(timezone.utc)
    evt = CotEvent(
        uid      = f"ARROW.TO.{obj.id}",
        cot_type = _tactical_object_cot_type(obj),
        lat      = obj.latitude or 0.0,
        lon      = obj.longitude or 0.0,
        callsign = (obj.notes or obj.type or "")[:60] or f"TO-{obj.id}",
        platform = "Arrow",
        time     = now,
    )
    xml = evt.to_xml()
    if stale:
        # Rewrite stale=now so ATAK immediately considers the event expired
        from lxml import etree as _et
        root = _et.fromstring(xml)
        ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        root.set("stale", ts)
        xml = _et.tostring(root, xml_declaration=True, encoding="UTF-8")
    return xml


async def broadcast_tactical_object_to_atak(obj: "TacticalObject") -> None:
    """Forward a created/updated TacticalObject to all ATAK clients as CoT."""
    if _Pool.count() == 0:
        return
    try:
        await _Pool.broadcast(_tactical_object_to_cot(obj))
    except Exception as exc:
        log.warning("tactical-object CoT broadcast failed: %s", exc)


async def broadcast_tactical_object_delete_to_atak(obj: "TacticalObject") -> None:
    """Tell ATAK to drop a marker by sending the same UID with stale=now."""
    if _Pool.count() == 0:
        return
    try:
        await _Pool.broadcast(_tactical_object_to_cot(obj, stale=True))
    except Exception as exc:
        log.warning("tactical-object stale-CoT broadcast failed: %s", exc)


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
