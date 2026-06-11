"""Native TCP CoT server — ATAK devices connect here directly on port 8087.

Architecture
------------
Arrow's FastAPI lifespan starts an asyncio TCP server alongside uvicorn.
ATAK (and any TAK-compatible client) connects on port 8087 using the standard
CoT streaming protocol (raw XML over persistent TCP, ``</event>`` delimited).

Per-connection lifecycle
------------------------
1. Client connects → server sends a welcome/presence CoT back.
2. Client streams CoT events:
     • uid == ARROW.{callsign}   → update Operator row + broadcast tracking
     • any other uid             → upsert CotTrack + broadcast cot-track
3. Server continuously pushes all operator positions to the client (sync loop).
4. On disconnect → clean up.

The server matches incoming CoT callsigns to Arrow operators.  If a callsign
matches, the CoT is treated as an authenticated position update for that
operator (password-free — ATAK does not carry JWT tokens).  Unknown callsigns
become foreign CotTrack entities visible on the tactical map.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import ClassVar

from lxml import etree

from backend.cot.cot import CotEvent, parse_cot, role_to_cot_type, cot_type_to_sidc
from backend.storage.database import SessionLocal
from backend.storage.models import CotTrack, Operator
from backend.websocket.manager import broadcaster

log = logging.getLogger("backend.cot.tcp")

_END_TAG    = b"</event>"
_SAFE_XML   = etree.XMLParser(resolve_entities=False, no_network=True)

COT_TCP_HOST = os.environ.get("ARROW_COT_TCP_HOST", "0.0.0.0")
COT_TCP_PORT = int(os.environ.get("ARROW_COT_TCP_PORT", "8087"))


# ── Connection pool ────────────────────────────────────────────────────────────

class _Pool:
    """Thread-safe set of active ATAK TCP writers."""
    _writers: ClassVar[dict[str, asyncio.StreamWriter]] = {}

    @classmethod
    def add(cls, uid: str, w: asyncio.StreamWriter) -> None:
        cls._writers[uid] = w
        log.info("ATAK connected: %s  (total=%d)", uid, len(cls._writers))

    @classmethod
    def remove(cls, uid: str) -> None:
        cls._writers.pop(uid, None)
        log.info("ATAK disconnected: %s  (total=%d)", uid, len(cls._writers))

    @classmethod
    async def broadcast(cls, data: bytes, exclude: str = "") -> None:
        """Push CoT bytes to all connected ATAK clients."""
        dead: list[str] = []
        for uid, w in list(cls._writers.items()):
            if uid == exclude:
                continue
            try:
                w.write(data)
                await w.drain()
            except Exception:
                dead.append(uid)
        for uid in dead:
            cls.remove(uid)

    @classmethod
    def count(cls) -> int:
        return len(cls._writers)


# ── Frame buffer ───────────────────────────────────────────────────────────────

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


# ── CoT → Arrow persistence ────────────────────────────────────────────────────

async def _handle_cot_event(raw: bytes, sender_uid: str) -> None:
    """Parse one CoT frame and persist it into Arrow."""
    try:
        evt = parse_cot(raw)
    except Exception as exc:
        log.debug("CoT parse error from %s: %s", sender_uid, exc)
        return

    # Match callsign to an Arrow operator (case-insensitive)
    with SessionLocal() as db:
        op: Operator | None = None
        if evt.callsign:
            op = (
                db.query(Operator)
                .filter(Operator.callsign.ilike(evt.callsign))
                .first()
            )

        if op:
            # ── Path A: recognised operator — update position ──────────────
            op.latitude  = evt.lat
            op.longitude = evt.lon
            op.altitude  = evt.hae
            op.last_seen = datetime.now(timezone.utc)
            op.status    = "ONLINE"
            db.commit()
            db.refresh(op)

            cot_type = role_to_cot_type(op.role)
            ack = CotEvent(
                uid=f"ARROW.{op.callsign}", cot_type=cot_type,
                lat=op.latitude, lon=op.longitude, hae=op.altitude or 0.0,
                callsign=op.callsign, role=op.role,
                speed=evt.speed, course=evt.course, team=evt.team,
            )
            await broadcaster.broadcast({
                "channel": "tracking", "event": "position",
                "cot_xml": ack.to_xml_str(),
                "data": {
                    "operator_id": op.id,    "callsign": op.callsign,
                    "latitude":    op.latitude, "longitude": op.longitude,
                    "altitude":    op.altitude, "team_id":  op.team_id,
                    "cot_type":    cot_type,
                },
            })
            log.debug("position updated: %s  lat=%.4f lon=%.4f", op.callsign, op.latitude, op.longitude)

        else:
            # ── Path B: foreign entity — upsert CotTrack ──────────────────
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
                    "id":        track.id,       "cot_uid":  track.cot_uid,
                    "cot_type":  track.cot_type, "sidc":     cot_type_to_sidc(track.cot_type),
                    "callsign":  track.callsign, "latitude": track.latitude,
                    "longitude": track.longitude,"hae":      track.hae,
                    "speed":     track.speed,    "course":   track.course,
                    "team":      track.team,     "last_seen":track.last_seen.isoformat(),
                },
            })
            log.debug("CotTrack upsert: %s  type=%s", evt.uid, evt.cot_type)

    # Relay to all other connected ATAK clients (peer awareness)
    await _Pool.broadcast(raw, exclude=sender_uid)


# ── Per-client handler ─────────────────────────────────────────────────────────

async def _client_handler(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
) -> None:
    peer    = writer.get_extra_info("peername", ("?", 0))
    cli_uid = f"atak-{peer[0]}-{peer[1]}"
    _Pool.add(cli_uid, writer)

    # Send a server-presence CoT so ATAK knows it's connected
    presence = CotEvent(
        uid="ARROW.SERVER", cot_type="a-f-G-U-C-O",
        lat=0.0, lon=0.0,
        callsign="ARROW", platform="Arrow",
    )
    try:
        writer.write(presence.to_xml())
        await writer.drain()
    except Exception:
        _Pool.remove(cli_uid)
        return

    # Push current operator snapshot so ATAK has immediate picture
    asyncio.create_task(_push_snapshot(writer))

    buf = _FrameBuf()
    try:
        while True:
            data = await asyncio.wait_for(reader.read(8192), timeout=120)
            if not data:
                break
            for frame in buf.feed(data):
                await _handle_cot_event(frame, cli_uid)
    except asyncio.TimeoutError:
        # Keepalive: re-send server presence; ATAK will reconnect if truly stale
        try:
            writer.write(presence.to_xml())
            await writer.drain()
        except Exception:
            pass
    except Exception as exc:
        log.debug("ATAK client %s error: %s", cli_uid, exc)
    finally:
        _Pool.remove(cli_uid)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _push_snapshot(writer: asyncio.StreamWriter) -> None:
    """Send current operator positions to a newly connected ATAK client."""
    try:
        with SessionLocal() as db:
            ops = db.query(Operator).filter(
                Operator.latitude.isnot(None),
                Operator.longitude.isnot(None),
            ).all()
            for op in ops:
                evt = CotEvent(
                    uid=f"ARROW.{op.callsign}",
                    cot_type=role_to_cot_type(op.role),
                    lat=op.latitude, lon=op.longitude,
                    hae=op.altitude or 0.0,
                    callsign=op.callsign, role=op.role,
                    platform="Arrow",
                )
                writer.write(evt.to_xml())
            await writer.drain()
            log.debug("snapshot sent: %d operators to new ATAK client", len(ops))
    except Exception as exc:
        log.debug("snapshot error: %s", exc)


# ── Public broadcast helpers (called by tracking router) ──────────────────────

async def broadcast_operator_cot(op: Operator) -> None:
    """Push an operator's updated position to all connected ATAK clients.

    Call this from the tracking router after saving a position update so
    ATAK devices always have live positions even if they don't poll.
    """
    if _Pool.count() == 0:
        return
    evt = CotEvent(
        uid=f"ARROW.{op.callsign}",
        cot_type=role_to_cot_type(op.role),
        lat=op.latitude or 0.0,
        lon=op.longitude or 0.0,
        hae=op.altitude or 0.0,
        callsign=op.callsign, role=op.role,
        platform="Arrow",
    )
    await _Pool.broadcast(evt.to_xml())


# ── Server lifecycle ───────────────────────────────────────────────────────────

_server: asyncio.Server | None = None


async def start() -> None:
    global _server
    _server = await asyncio.start_server(
        _client_handler, COT_TCP_HOST, COT_TCP_PORT,
    )
    log.info("CoT TCP server listening on %s:%d  (ATAK port)", COT_TCP_HOST, COT_TCP_PORT)


async def stop() -> None:
    global _server
    if _server:
        _server.close()
        await _server.wait_closed()
        _server = None
        log.info("CoT TCP server stopped")


def connected_clients() -> int:
    return _Pool.count()
