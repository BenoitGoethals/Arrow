"""Mortar COP — ephemeral firing-state events broadcast to all web/front clients.

Front calls POST /mortar-cop/event whenever MortarCalc transitions to SHOT or
IN_EFFECT (and back). The backend re-broadcasts the payload on the ``mortar-cop``
WebSocket channel so the web map and any other listener can show a firing toast.
No DB writes — purely a broadcast relay.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth.jwt_auth import get_current_operator
from backend.storage.models import Operator
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/mortar-cop", tags=["mortar-cop"])


class MortarCopEvent(BaseModel):
    event: str  # "firing" | "ceased"
    group: str = ""
    target: str = ""
    state: str = ""  # "shot" | "in_effect" | ""


@router.post("/event")
async def mortar_cop_event(
    payload: MortarCopEvent,
    _: Operator = Depends(get_current_operator),
) -> dict:
    """Broadcast a mortar firing/ceased event to all connected clients."""
    await broadcaster.broadcast(
        {
            "channel": "mortar-cop",
            "event": payload.event,
            "data": payload.model_dump(),
        }
    )
    return {"ok": True}
