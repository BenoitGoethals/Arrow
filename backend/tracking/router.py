from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.api.schemas import OperatorOut, PositionHistoryOut, PositionIn
from backend.auth.jwt_auth import get_current_operator
from backend.cot.cot import CotEvent, role_to_cot_type
from backend.missions.dependencies import get_active_mission
from backend.storage.database import get_db
from backend.storage.models import Mission, Operator, OperatorPosition
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/tracking", tags=["tracking"])


@router.post("/position", response_model=OperatorOut)
async def update_position(
    payload: PositionIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> OperatorOut:
    current.latitude = payload.latitude
    current.longitude = payload.longitude
    current.altitude = payload.altitude
    current.last_seen = datetime.now(timezone.utc)
    current.status = "ONLINE"
    # Tag the reporting client so the COP can filter devices by source. ATAK is
    # set on the CoT/TCP path; here we only accept the known app clients and fall
    # back to the generic "APP" for anything unrecognised or unspecified.
    _client = (payload.client or "").strip().upper()
    current.position_source = _client if _client in {"FRONT", "ANDROID"} else "APP"

    # Persist every fix for track history and behaviour analytics.
    db.add(
        OperatorPosition(
            operator_id=current.id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            altitude=payload.altitude,
            recorded_at=current.last_seen,
        )
    )
    db.commit()
    db.refresh(current)

    cot_type = role_to_cot_type(current.role)
    cot_xml = CotEvent(
        uid=f"ARROW.{current.callsign}",
        cot_type=cot_type,
        lat=current.latitude,
        lon=current.longitude,
        hae=current.altitude or 0.0,
        callsign=current.callsign,
        role=current.role,
    ).to_xml_str()

    # Snapshot the response and hand the DB connection back to the pool *before*
    # the fan-out awaits below. broadcast()/ATAK/JDSS can take a while under load
    # (many WS clients, slow gateway); holding the session open across them ties
    # up a pooled connection for no reason. current's scalar columns stay readable
    # after close() since they're already loaded (refresh above).
    result = OperatorOut.model_validate(current)
    db.close()

    await broadcaster.broadcast(
        {
            "channel": "tracking",
            "event": "position",
            "cot_xml": cot_xml,
            "data": {
                "operator_id": current.id,
                "callsign": current.callsign,
                "latitude": current.latitude,
                "longitude": current.longitude,
                "altitude": current.altitude,
                "team_id": current.team_id,
                "mission_id": current.mission_id,
                "cot_type": cot_type,
                "position_source": current.position_source,
            },
        }
    )

    # Push live position to all connected ATAK devices over TCP CoT
    from backend.cot.tcp_server import broadcast_operator_cot

    await broadcast_operator_cot(current)

    # Push live position to an external JDSSArrow gateway as a Presence message.
    from backend.jdss import bridge as _jdss

    await _jdss.publish_operator_presence(current)

    return result


@router.get("/live", response_model=list[OperatorOut])
def live_operators(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> list[Operator]:
    q = db.query(Operator).filter(
        Operator.latitude.is_not(None), Operator.longitude.is_not(None)
    )
    if mission:
        q = q.filter(Operator.mission_id == mission.id)
    return q.all()


@router.get("/{operator_id}/history", response_model=list[PositionHistoryOut])
def operator_history(
    operator_id: int,
    since: datetime | None = Query(
        default=None, description="ISO-8601 start time (inclusive)"
    ),
    until: datetime | None = Query(
        default=None, description="ISO-8601 end time (inclusive)"
    ),
    limit: int = Query(default=5000, le=20000),
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> list[OperatorPosition]:
    q = db.query(OperatorPosition).filter(OperatorPosition.operator_id == operator_id)
    if since:
        q = q.filter(OperatorPosition.recorded_at >= since)
    if until:
        q = q.filter(OperatorPosition.recorded_at <= until)
    return q.order_by(OperatorPosition.recorded_at.asc()).limit(limit).all()
