from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from backend.auth.jwt_auth import decode_token
from backend.storage.database import SessionLocal
from backend.storage.models import Operator
from backend.websocket.manager import broadcaster

router = APIRouter()


def _set_operator_status(callsign: str, online: bool) -> None:
    """Update Operator.status and last_seen in the DB on WS connect/disconnect."""
    try:
        with SessionLocal() as db:
            op = db.query(Operator).filter(
                Operator.callsign.ilike(callsign)
            ).first()
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
    _set_operator_status(callsign, online=True)

    await broadcaster.connect(websocket)
    await broadcaster.broadcast(
        {"channel": "presence", "event": "online", "data": {"callsign": callsign}}
    )
    try:
        while True:
            msg = await websocket.receive_json()
            await broadcaster.broadcast(
                {"channel": msg.get("channel", "chat"), "event": "message", "data": msg, "from": callsign}
            )
    except WebSocketDisconnect:
        pass
    finally:
        _set_operator_status(callsign, online=False)
        await broadcaster.disconnect(websocket)
        await broadcaster.broadcast(
            {"channel": "presence", "event": "offline", "data": {"callsign": callsign}}
        )
