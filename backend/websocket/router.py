from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from backend.auth.jwt_auth import decode_token
from backend.websocket.manager import broadcaster

router = APIRouter()


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

    await broadcaster.connect(websocket)
    callsign = payload.get("sub", "unknown")
    await broadcaster.broadcast(
        {"channel": "presence", "event": "online", "data": {"callsign": callsign}}
    )
    try:
        while True:
            msg = await websocket.receive_json()
            # Echo back on a generic chat channel; real routing happens via REST endpoints.
            await broadcaster.broadcast(
                {"channel": msg.get("channel", "chat"), "event": "message", "data": msg, "from": callsign}
            )
    except WebSocketDisconnect:
        pass
    finally:
        await broadcaster.disconnect(websocket)
        await broadcaster.broadcast(
            {"channel": "presence", "event": "offline", "data": {"callsign": callsign}}
        )
