"""Live video stream relay.

Android producers push MJPEG frames (compressed JPEG bytes) over WebSocket.
The backend relays each frame to all connected web consumers.

Flow:
  1. Android  → WS /streams/{id}/produce?token=...  (binary frames)
  2. Backend  → broadcasts JSON {channel:"stream", event:"started"} to all /ws clients
  3. Browser  → WS /streams/{id}/consume?token=...  (receives binary frames)
  4. Android disconnects → broadcasts {channel:"stream", event:"ended"}

Each frame is raw JPEG bytes; no additional framing/headers.
Compression target: JPEG quality 40, 640×480 px, ~5 FPS → ≈150 kbps.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from backend.auth.jwt_auth import _cfg as _auth_cfg, get_current_operator  # re-use JWT config
from backend.storage.models import Operator
from backend.websocket.manager import broadcaster

log = logging.getLogger(__name__)
router = APIRouter(prefix="/streams", tags=["streams"])


# ── In-memory stream registry ─────────────────────────────────────────────────

@dataclass
class ActiveStream:
    stream_id:   str
    callsign:    str
    operator_id: int
    started_at:  datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    consumers:   list[WebSocket] = field(default_factory=list)


_registry: dict[str, ActiveStream] = {}   # stream_id → ActiveStream


def list_streams() -> list[dict]:
    return [
        {
            "id":          s.stream_id,
            "callsign":    s.callsign,
            "operator_id": s.operator_id,
            "started_at":  s.started_at.isoformat(),
            "viewers":     len(s.consumers),
        }
        for s in _registry.values()
    ]


# ── Auth helper ───────────────────────────────────────────────────────────────

def _verify_token(token: str) -> dict | None:
    """Return JWT payload or None."""
    from jose import JWTError, jwt
    try:
        return jwt.decode(token, _auth_cfg.secret, algorithms=[_auth_cfg.algorithm])
    except JWTError:
        return None


# ── REST: list active streams ─────────────────────────────────────────────────

@router.get("")
def get_streams(_: Operator = Depends(get_current_operator)) -> list[dict]:
    return list_streams()


# ── WebSocket: Android producer ───────────────────────────────────────────────

@router.websocket("/{stream_id}/produce")
async def produce(websocket: WebSocket, stream_id: str, token: str = Query(...)):
    payload = _verify_token(token)
    if not payload:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    await websocket.accept()
    callsign    = payload.get("sub", "unknown")
    operator_id = payload.get("id", 0)

    stream = ActiveStream(stream_id=stream_id, callsign=callsign, operator_id=operator_id)
    _registry[stream_id] = stream
    log.info("Stream started: %s by %s", stream_id, callsign)

    await broadcaster.broadcast({
        "channel": "stream",
        "event":   "started",
        "data": {
            "id":          stream_id,
            "callsign":    callsign,
            "operator_id": operator_id,
        },
    })

    try:
        while True:
            # Receive a JPEG frame (binary)
            frame = await websocket.receive_bytes()
            if not frame:
                continue
            # Relay to all connected consumers in parallel
            if stream.consumers:
                dead: list[WebSocket] = []
                results = await asyncio.gather(
                    *[c.send_bytes(frame) for c in stream.consumers],
                    return_exceptions=True,
                )
                for ws, exc in zip(stream.consumers, results):
                    if isinstance(exc, Exception):
                        dead.append(ws)
                for ws in dead:
                    stream.consumers.remove(ws)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("Producer error: %s", exc)
    finally:
        _registry.pop(stream_id, None)
        log.info("Stream ended: %s", stream_id)
        await broadcaster.broadcast({
            "channel": "stream",
            "event":   "ended",
            "data":    {"id": stream_id, "callsign": callsign},
        })
        # Notify all consumers the stream is over
        for c in stream.consumers:
            try:
                await c.send_json({"event": "ended"})
                await c.close()
            except Exception:
                pass


# ── WebSocket: web consumer ───────────────────────────────────────────────────

@router.websocket("/{stream_id}/consume")
async def consume(websocket: WebSocket, stream_id: str, token: str = Query(...)):
    payload = _verify_token(token)
    if not payload:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    stream = _registry.get(stream_id)
    if not stream:
        await websocket.close(code=4404, reason="Stream not found")
        return

    await websocket.accept()
    stream.consumers.append(websocket)
    log.info("Consumer joined: %s for stream %s", payload.get("sub"), stream_id)

    try:
        # Keep alive — consumer is passive (only receives frames)
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if websocket in stream.consumers:
            stream.consumers.remove(websocket)
