"""Mumble REST + WebSocket endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, WebSocket
from pydantic import BaseModel

from backend.auth.dependencies import get_current_operator, require_role
from backend.auth.infrastructure.token_service import decode_token
from backend.mumble.monitor import monitor

router = APIRouter(prefix="/mumble", tags=["mumble"])


class MumbleConfig(BaseModel):
    host: str
    port: int = 64738
    username: str = "ArrowBot"
    password: str = ""


# ── REST ─────────────────────────────────────────────────────────────────────


@router.get("/status")
async def get_status(_op=Depends(get_current_operator)):
    return monitor.get_status()


@router.get("/ping")
async def ping_mumble(_op=Depends(get_current_operator)):
    """TCP probe + live bot-status for the configured Mumble server."""
    import asyncio
    import time

    cfg = monitor._config
    if not cfg.get("host"):
        return {"ok": False, "msg": "Bot not configured — set host in ⚙ Bot Config"}

    host = cfg["host"]
    port = int(cfg.get("port", 64738))
    t0 = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=3.0
        )
        tcp_ms = int((time.monotonic() - t0) * 1000)
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=0.5)
        except Exception:
            pass
    except asyncio.TimeoutError:
        return {"ok": False, "msg": f"TCP timeout → {host}:{port} (3 s)"}
    except Exception as exc:
        return {"ok": False, "msg": f"{host}:{port} — {exc}"}

    st = monitor.get_status()
    return {
        "ok": True,
        "tcp_ms": tcp_ms,
        "host": host,
        "port": port,
        "bot_connected": st["connected"],
        "bot_error": st.get("error", ""),
        "channels": len(st.get("channels", [])),
        "users": len(st.get("users", [])),
    }


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
        host = msg.get("host", "")
        port = int(msg.get("port", 64738))
        username = msg.get("username") or callsign
        password = msg.get("password", "")
        if not host:
            await websocket.send_json({"type": "error", "msg": "host required"})
            await websocket.close()
            return
    except Exception:
        await websocket.close()
        return

    from backend.mumble.ws_bridge import MumbleVoiceSession

    session = MumbleVoiceSession(websocket, callsign)
    await session.run(host, port, username, password)
