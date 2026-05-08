"""CoT endpoint — accepts Cursor-on-Target XML position updates from ATAK/Arrow clients.

POST /cot          application/xml body → updates operator position, broadcasts CoT.
GET  /cot/{uid}    returns the latest CoT snapshot for one operator as XML.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.auth.jwt_auth import get_current_operator
from backend.cot.cot import CotEvent, parse_cot, role_to_cot_type
from backend.storage.database import get_db
from backend.storage.models import Operator
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/cot", tags=["cot"])


@router.post(
    "",
    status_code=status.HTTP_200_OK,
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}}},
)
async def receive_cot(
    request: Request,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> Response:
    """Accept a CoT XML position event from an Arrow/ATAK client.

    The JWT in the Authorization header identifies the operator; the CoT uid
    and callsign are used for validation only.  Returns an acknowledgement CoT
    (the operator's current server-side snapshot).
    """
    body = await request.body()
    if not body:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty body")

    try:
        evt = parse_cot(body)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("CoT parse error: %s", exc)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Invalid CoT XML") from exc

    # Update operator position
    current.latitude  = evt.lat
    current.longitude = evt.lon
    current.altitude  = evt.hae
    current.last_seen = datetime.now(timezone.utc)
    current.status    = "ONLINE"
    db.commit()
    db.refresh(current)

    # Broadcast CoT XML (and JSON shadow) to all WS subscribers
    cot_type = role_to_cot_type(current.role)
    ack = CotEvent(
        uid      = f"ARROW.{current.callsign}",
        cot_type = cot_type,
        lat      = current.latitude,
        lon      = current.longitude,
        hae      = current.altitude or 0.0,
        callsign = current.callsign,
        role     = current.role,
        speed    = evt.speed,
        course   = evt.course,
        team     = evt.team,
    )
    await broadcaster.broadcast({
        "channel":    "tracking",
        "event":      "position",
        "cot_xml":    ack.to_xml_str(),   # ← CoT XML string for Android/ATAK consumers
        "data": {
            "operator_id": current.id,
            "callsign":    current.callsign,
            "latitude":    current.latitude,
            "longitude":   current.longitude,
            "altitude":    current.altitude,
            "team_id":     current.team_id,
            "cot_type":    cot_type,
        },
    })

    return Response(content=ack.to_xml(), media_type="application/xml")


@router.get(
    "/{uid}",
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}}},
)
def get_cot_snapshot(
    uid: str,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> Response:
    """Return the latest CoT position snapshot for an operator by ARROW.{callsign} uid."""
    callsign = uid.removeprefix("ARROW.")
    op = db.query(Operator).filter(Operator.callsign == callsign).first()
    if not op or op.latitude is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    evt = CotEvent(
        uid      = uid,
        cot_type = role_to_cot_type(op.role),
        lat      = op.latitude,
        lon      = op.longitude,
        hae      = op.altitude or 0.0,
        callsign = op.callsign,
        role     = op.role,
    )
    return Response(content=evt.to_xml(), media_type="application/xml")
