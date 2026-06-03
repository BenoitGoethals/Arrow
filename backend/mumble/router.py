"""Mumble REST + WebSocket endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, WebSocket
from pydantic import BaseModel

from backend.auth.dependencies import get_current_operator, require_role
from backend.auth.infrastructure.token_service import decode_token
from backend.mumble.monitor import monitor

router = APIRouter(prefix="/mumble", tags=["mumble"])


class MumbleConfig(BaseModel):
    host:     str
    port:     int  = 64738
    username: str  = "ArrowBot"
    password: str  = ""


# ── REST ─────────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_status(_op=Depends(get_current_operator)):
    return monitor.get_status()


@router.get("/config")
async def get_config(_op=Depends(require_role("ADMIN", "BATTLE_CAPTAIN"))):
    return monitor.get_config_public()


@router.post("/config", status_code=200)
async def set_config(
    cfg: MumbleConfig,
    _op=Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
):
    monitor.apply_config(cfg.model_dump())
    return {"ok": True}


@router.delete("/config", status_code=200)
async def delete_config(_op=Depends(require_role("ADMIN", "BATTLE_CAPTAIN"))):
    monitor.clear_config()
    return {"ok": True}


# ── WebSocket voice bridge ────────────────────────────────────────────────────

@router.websocket("/voice")
async def mumble_voice_ws(
    websocket: WebSocket,
    token: str = Query(...),
):
    """Personal voice WebSocket.  Browser sends/receives PCM audio + JSON commands."""
    # Authenticate via JWT query param (same pattern as /ws)
    try:
        payload = decode_token(token)
        callsign = payload.get("sub", "WebUser")
    except Exception:
        await websocket.close(code=4001)
        return

    await websocket.accept()

    # First frame must be the connect command
    try:
        msg = await websocket.receive_json()
        if msg.get("type") != "connect":
            await websocket.close(code=4002)
            return
        host     = msg.get("host", "")
        port     = int(msg.get("port", 64738))
        username = msg.get("username") or callsign
        password = msg.get("password", "")
        if not host:
            await websocket.send_json({"type": "error", "msg": "host required"})
            await websocket.close()
            return
    except Exception as exc:
        await websocket.close()
        return

    from backend.mumble.ws_bridge import MumbleVoiceSession
    session = MumbleVoiceSession(websocket, callsign)
    await session.run(host, port, username, password)
