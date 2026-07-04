"""JDSS bridge admin endpoints — status, config, restart.

Mirrors the ``/cot/tcp/*`` endpoints in :mod:`backend.cot.router`. The Flask
admin UI reaches these through the ``/api`` reverse proxy.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth.jwt_auth import get_current_operator, require_role
from backend.storage.models import Operator

router = APIRouter(prefix="/jdss", tags=["jdss"])


@router.get("/status")
def jdss_status(_: Operator = Depends(get_current_operator)) -> dict:
    """Return JDSS bridge status (connection, counters, last snapshot/peers)."""
    from backend.jdss import bridge

    return bridge.get_status()


@router.get("/config")
def jdss_get_config(
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> dict:
    """Return the current JDSS bridge configuration."""
    from backend.jdss import bridge

    return bridge.get_config()


@router.put("/config")
async def jdss_update_config(
    patch: dict,
    _: Operator = Depends(require_role("ADMIN")),
) -> dict:
    """Update the JDSS bridge configuration (persisted to data/jdss_config.json).

    Changes to ``base_url`` or ``enabled`` take effect after POST /jdss/restart.
    """
    from backend.jdss import bridge

    return bridge.update_config(patch)


@router.post("/restart")
async def jdss_restart(_: Operator = Depends(require_role("ADMIN"))) -> dict:
    """Restart the JDSS bridge so it picks up new base_url / enabled config."""
    from backend.jdss import bridge

    await bridge.restart()
    return {"status": "restarted", **bridge.get_status()}
