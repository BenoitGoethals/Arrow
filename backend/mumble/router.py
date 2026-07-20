"""Mumble REST + WebSocket endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, status
from pydantic import BaseModel
from sqlalchemy import false, or_
from sqlalchemy.orm import Session

from backend.api.schemas import VoiceChannelIn, VoiceChannelOut, VoiceChannelUpdate
from backend.auth.dependencies import get_current_operator, require_role
from backend.auth.infrastructure.token_service import decode_token
from backend.mumble.monitor import monitor
from backend.storage.database import get_db
from backend.storage.models import Operator, VoiceChannel

router = APIRouter(prefix="/mumble", tags=["mumble"])


class MumbleConfig(BaseModel):
    host: str
    port: int = 64738
    username: str = "ArrowBot"
    password: str = ""


# ── Voice-channel access helpers ───────────────────────────────────────────────

# Only these three roles form the min_role ladder; every other operator role
# (LOG, FO, CAS, …) is treated as OPERATOR-level.
_ROLE_RANK = {"OPERATOR": 0, "BATTLE_CAPTAIN": 1, "ADMIN": 2}


def _role_rank(role: str) -> int:
    return _ROLE_RANK.get(role, 0)


def _can_access(op: Operator, vc: VoiceChannel) -> bool:
    """Same gate as the rest of Arrow: active + clearance + role + mission."""
    if not vc.is_active:
        return False
    if vc.classification > op.clearance:
        return False
    if _role_rank(op.role) < _role_rank(vc.min_role):
        return False
    if vc.mission_id is not None and vc.mission_id != op.mission_id:
        return False
    return True


def _vc_out(vc: VoiceChannel) -> VoiceChannelOut:
    out = VoiceChannelOut.model_validate(vc)
    out.has_password = bool(vc.password)
    return out


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


# ── Voice channels (admin-defined, curated) ────────────────────────────────────


@router.get("/channels", response_model=list[VoiceChannelOut])
def list_channels(
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> list[VoiceChannelOut]:
    """Curated voice channels visible to the caller.

    ADMIN / BATTLE_CAPTAIN see every channel (incl. inactive) for management;
    everyone else sees only the channels they may join (active + clearance +
    min_role + mission gate).
    """
    if current.role in ("ADMIN", "BATTLE_CAPTAIN"):
        rows = (
            db.query(VoiceChannel)
            .order_by(VoiceChannel.sort_order, VoiceChannel.name)
            .all()
        )
        return [_vc_out(vc) for vc in rows]

    mission_cond = or_(
        VoiceChannel.mission_id.is_(None),
        (
            VoiceChannel.mission_id == current.mission_id
            if current.mission_id is not None
            else false()
        ),
    )
    rows = (
        db.query(VoiceChannel)
        .filter(
            VoiceChannel.is_active.is_(True),
            VoiceChannel.classification <= current.clearance,
            mission_cond,
        )
        .order_by(VoiceChannel.sort_order, VoiceChannel.name)
        .all()
    )
    # min_role ladder is easier to express in Python than SQL.
    return [
        _vc_out(vc)
        for vc in rows
        if _role_rank(current.role) >= _role_rank(vc.min_role)
    ]


@router.post(
    "/channels", response_model=VoiceChannelOut, status_code=status.HTTP_201_CREATED
)
def create_channel(
    payload: VoiceChannelIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> VoiceChannelOut:
    vc = VoiceChannel(**payload.model_dump(), created_by=current.id)
    db.add(vc)
    db.commit()
    db.refresh(vc)
    return _vc_out(vc)


@router.patch("/channels/{channel_id}", response_model=VoiceChannelOut)
def update_channel(
    channel_id: int,
    payload: VoiceChannelUpdate,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> VoiceChannelOut:
    vc = db.get(VoiceChannel, channel_id)
    if not vc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Voice channel not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        # An empty password in a PATCH means "leave unchanged".
        if field == "password" and not value:
            continue
        setattr(vc, field, value)
    db.commit()
    db.refresh(vc)
    return _vc_out(vc)


@router.get("/channels/{channel_id}/connect")
def channel_connect_info(
    channel_id: int,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> dict:
    """Full connect credentials for a channel — for clients (Front) that connect
    directly to Mumble rather than via the server-side voice bridge.

    Returns the password only to an operator who passes the access gate; the
    list endpoint never exposes it.
    """
    vc = db.get(VoiceChannel, channel_id)
    if not vc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Voice channel not found")
    if not _can_access(current, vc):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Not authorised for this channel"
        )
    host = vc.host or monitor._config.get("host", "")
    port = vc.port or int(monitor._config.get("port", 64738))
    if not host:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No server configured for this channel"
        )
    return {
        "id": vc.id,
        "name": vc.name,
        "host": host,
        "port": int(port),
        "password": vc.password,
        "channel": vc.mumble_channel,
    }


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> None:
    vc = db.get(VoiceChannel, channel_id)
    if not vc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Voice channel not found")
    db.delete(vc)
    db.commit()


# ── WebSocket voice bridge ────────────────────────────────────────────────────


def _resolve_channel(callsign: str, channel_id: int) -> dict:
    """Resolve a curated VoiceChannel to connect params, enforcing access.

    Opens its own short-lived session via the module (not a captured
    ``SessionLocal``) so the test StaticPool override applies. Returns a dict
    with either ``error`` or the resolved ``host/port/password/channel``.
    """
    import backend.storage.database as _dbmod

    db = _dbmod.SessionLocal()
    try:
        op = db.query(Operator).filter(Operator.callsign == callsign).first()
        if not op:
            return {"error": "operator not found"}
        vc = db.get(VoiceChannel, channel_id)
        if not vc:
            return {"error": "voice channel not found"}
        if not _can_access(op, vc):
            return {"error": "not authorised for this voice channel"}
        host = vc.host or monitor._config.get("host", "")
        port = vc.port or int(monitor._config.get("port", 64738))
        if not host:
            return {"error": "no server configured for this channel"}
        return {
            "host": host,
            "port": int(port),
            "password": vc.password,
            "channel": vc.mumble_channel,
        }
    finally:
        db.close()


@router.websocket("/voice")
async def mumble_voice_ws(
    websocket: WebSocket,
    token: str = Query(...),
):
    """Personal voice WebSocket.  Browser sends/receives PCM audio + JSON commands.

    The connect frame may reference a curated channel by ``channel_id`` (server
    resolves host/port/password/target channel and enforces access) or supply a
    raw ``host`` directly (legacy / advanced).
    """
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
        username = msg.get("username") or callsign
        channel = ""
        if msg.get("channel_id") is not None:
            resolved = _resolve_channel(callsign, int(msg["channel_id"]))
            if "error" in resolved:
                await websocket.send_json(
                    {"type": "state", "state": "error", "msg": resolved["error"]}
                )
                await websocket.close(code=4003)
                return
            host = resolved["host"]
            port = resolved["port"]
            password = resolved["password"]
            channel = resolved["channel"]
        else:
            host = msg.get("host", "")
            port = int(msg.get("port", 64738))
            password = msg.get("password", "")
            channel = msg.get("channel", "")
        if not host:
            await websocket.send_json({"type": "error", "msg": "host required"})
            await websocket.close()
            return
    except Exception:
        await websocket.close()
        return

    from backend.mumble.ws_bridge import MumbleVoiceSession

    session = MumbleVoiceSession(websocket, callsign)
    await session.run(host, port, username, password, channel)
