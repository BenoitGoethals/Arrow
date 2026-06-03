"""Mumble REST endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth.dependencies import get_current_operator, require_role
from backend.mumble.monitor import monitor

router = APIRouter(prefix="/mumble", tags=["mumble"])


class MumbleConfig(BaseModel):
    host:     str
    port:     int  = 64738
    username: str  = "ArrowBot"
    password: str  = ""


@router.get("/status")
async def get_status(_op=Depends(get_current_operator)):
    """Return current Mumble presence state (channels + users)."""
    return monitor.get_status()


@router.get("/config")
async def get_config(_op=Depends(require_role("ADMIN", "BATTLE_CAPTAIN"))):
    """Return current Mumble config (password masked)."""
    return monitor.get_config_public()


@router.post("/config", status_code=200)
async def set_config(
    cfg: MumbleConfig,
    _op=Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
):
    """Save Mumble config and (re-)connect the monitor bot."""
    monitor.apply_config(cfg.model_dump())
    return {"ok": True}


@router.delete("/config", status_code=200)
async def delete_config(_op=Depends(require_role("ADMIN", "BATTLE_CAPTAIN"))):
    """Disconnect and clear Mumble config."""
    monitor.clear_config()
    return {"ok": True}
