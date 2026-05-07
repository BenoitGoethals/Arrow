"""Call-for-Fire / Artillery Fire Mission endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas import FireMissionIn, FireMissionOut, FireMissionUpdate
from backend.auth.jwt_auth import get_current_operator, require_role
from backend.storage.database import get_db
from backend.storage.models import FireMission, Operator
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/fire-missions", tags=["fire-missions"])

VALID_TYPES = {"ADJUST_FIRE", "FIRE_FOR_EFFECT", "SUPPRESSION", "ILLUMINATION", "IMMEDIATE_SUPPRESSION"}
VALID_AMMO  = {"HE", "ILLUM", "SMOKE", "WP", "ICM", "MIXED", "AP", "FRAG"}


@router.get("", response_model=list[FireMissionOut])
def list_missions(
    db: Session = Depends(get_db),
    _: Operator  = Depends(get_current_operator),
) -> list[FireMission]:
    return db.query(FireMission).order_by(FireMission.timestamp.desc()).limit(200).all()


@router.post("", response_model=FireMissionOut, status_code=status.HTTP_201_CREATED)
async def submit_mission(
    payload: FireMissionIn,
    db:      Session  = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> FireMission:
    mtype = payload.mission_type.upper()
    ammo  = payload.ammunition.upper()
    if mtype not in VALID_TYPES:
        mtype = "ADJUST_FIRE"
    if ammo not in VALID_AMMO:
        ammo = "HE"

    fm = FireMission(
        operator_id  = current.id,
        latitude     = payload.latitude,
        longitude    = payload.longitude,
        altitude     = payload.altitude,
        direction    = payload.direction,
        mission_type = mtype,
        ammunition   = ammo,
        quantity     = payload.quantity,
        description  = payload.description,
    )
    db.add(fm)
    db.commit()
    db.refresh(fm)

    out = FireMissionOut.model_validate(fm).model_dump(mode="json")
    await broadcaster.broadcast({
        "channel": "fire-mission",
        "event":   "submitted",
        "data":    {**out, "callsign": current.callsign},
    })
    return fm


@router.patch("/{fm_id}", response_model=FireMissionOut)
async def update_mission(
    fm_id:   int,
    payload: FireMissionUpdate,
    db:      Session  = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> FireMission:
    """Acknowledge, assign to FDC, change status, or add notes."""
    fm = db.get(FireMission, fm_id)
    if not fm:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(fm, field, value)
    db.commit()
    db.refresh(fm)

    out = FireMissionOut.model_validate(fm).model_dump(mode="json")
    await broadcaster.broadcast({
        "channel": "fire-mission",
        "event":   "updated",
        "data":    {**out, "updated_by": current.callsign},
    })
    return fm


@router.delete("/{fm_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_mission(
    fm_id: int,
    db:    Session  = Depends(get_db),
    _:     Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> None:
    fm = db.get(FireMission, fm_id)
    if not fm:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    fm.status = "CANCELLED"
    db.commit()
