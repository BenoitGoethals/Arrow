from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.schemas import OperatorOut, PositionIn
from backend.auth.jwt_auth import get_current_operator
from backend.storage.database import get_db
from backend.storage.models import Operator
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/tracking", tags=["tracking"])


@router.post("/position", response_model=OperatorOut)
async def update_position(
    payload: PositionIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> Operator:
    current.latitude = payload.latitude
    current.longitude = payload.longitude
    current.altitude = payload.altitude
    current.last_seen = datetime.now(timezone.utc)
    current.status = "ONLINE"
    db.commit()
    db.refresh(current)

    await broadcaster.broadcast(
        {
            "channel": "tracking",
            "event": "position",
            "data": {
                "operator_id": current.id,
                "callsign": current.callsign,
                "latitude": current.latitude,
                "longitude": current.longitude,
                "altitude": current.altitude,
                "team_id": current.team_id,
            },
        }
    )
    return current


@router.get("/live", response_model=list[OperatorOut])
def live_operators(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> list[Operator]:
    return (
        db.query(Operator)
        .filter(Operator.latitude.is_not(None), Operator.longitude.is_not(None))
        .all()
    )
