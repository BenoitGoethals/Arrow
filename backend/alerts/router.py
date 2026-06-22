from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from backend.api.schemas import AlertIn, AlertOut
from backend.auth.jwt_auth import get_current_operator, require_role
from backend.missions.dependencies import get_active_mission
from backend.storage.database import get_db
from backend.storage.models import Alert, Mission, Operator
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> list[Alert]:
    q = (
        db.query(Alert)
        .options(selectinload(Alert.operator))
        .order_by(Alert.timestamp.desc())
    )
    if mission:
        q = q.filter(Alert.mission_id == mission.id)
    return q.limit(200).all()


@router.post("", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
async def trigger_alert(
    payload: AlertIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> Alert:
    alert = Alert(
        type=payload.type,
        operator_id=current.id,
        latitude=payload.latitude if payload.latitude is not None else current.latitude,
        longitude=(
            payload.longitude if payload.longitude is not None else current.longitude
        ),
        mission_id=mission.id if mission else current.mission_id,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    data = AlertOut.model_validate(alert).model_dump(mode="json")
    data["callsign"] = current.callsign
    await broadcaster.broadcast(
        {
            "channel": "alert",
            "event": "triggered",
            "mission_id": alert.mission_id,
            "data": data,
        }
    )
    return alert


@router.post("/{alert_id}/ack", response_model=AlertOut)
async def acknowledge(
    alert_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> Alert:
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    alert.status = "ACKNOWLEDGED"
    db.commit()
    db.refresh(alert)
    await broadcaster.broadcast(
        {
            "channel": "alert",
            "event": "ack",
            "mission_id": alert.mission_id,
            "data": AlertOut.model_validate(alert).model_dump(mode="json"),
        }
    )
    return alert
