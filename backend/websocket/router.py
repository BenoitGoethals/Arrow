from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from backend.auth.jwt_auth import decode_token
from backend.storage.database import SessionLocal
from backend.storage.models import Operator
from backend.websocket.manager import broadcaster

router = APIRouter()

_HEARTBEAT_INTERVAL = 60  # seconds — must be < the 90 s online window


def _touch_operator(callsign: str, online: bool) -> None:
    """Set status + last_seen (when online) for the operator in the DB."""
    try:
        with SessionLocal() as db:
            op = db.query(Operator).filter(Operator.callsign.ilike(callsign)).first()
            if op:
                op.status = "ONLINE" if online else "OFFLINE"
                if online:
                    op.last_seen = datetime.now(timezone.utc)
                db.commit()
    except Exception:
        pass


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
) -> None:
    try:
        payload = decode_token(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    callsign = payload.get("sub", "unknown")
    _touch_operator(callsign, online=True)

    await broadcaster.connect(websocket)
    await broadcaster.broadcast(
        {"channel": "presence", "event": "online", "data": {"callsign": callsign}}
    )

    async def _heartbeat():
        """Refresh last_seen every 60 s so the 90 s online window stays open."""
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            _touch_operator(callsign, online=True)

    hb_task = asyncio.create_task(_heartbeat())
    try:
        while True:
            msg = await websocket.receive_json()
            await broadcaster.broadcast(
                {
                    "channel": msg.get("channel", "chat"),
                    "event": "message",
                    "data": msg,
                    "from": callsign,
                }
            )
    except WebSocketDisconnect:
        pass
    finally:
        hb_task.cancel()
        _touch_operator(callsign, online=False)
        await broadcaster.disconnect(websocket)
        await broadcaster.broadcast(
            {"channel": "presence", "event": "offline", "data": {"callsign": callsign}}
        )
