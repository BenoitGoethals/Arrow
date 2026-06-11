"""Mission CRUD, lifecycle (start / end / reset), and operator assignment."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas import OperatorOut, TacticalObjectOut
from backend.auth.jwt_auth import get_current_operator, require_role
from backend.missions.schemas import (
    AssignOperatorsIn, MissionCreate, MissionOut, MissionSnapshotOut,
    MissionUpdate,
)
from backend.storage.database import get_db
from backend.storage.models import (
    Alert, FireMission, Message, Mission, Operator,
    Report, TacticalObject,
)
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/missions", tags=["missions"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── helpers ──────────────────────────────────────────────────────────────────

def _snapshot_mission(db: Session, mission: Mission) -> str:
    """Serialise all current tactical objects in this mission to a JSON string."""
    objects = db.query(TacticalObject).filter(
        TacticalObject.mission_id == mission.id
    ).all()
    return json.dumps([
        TacticalObjectOut.model_validate(o).model_dump(mode="json")
        for o in objects
    ])


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[MissionOut])
def list_missions(
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> list[Mission]:
    if current.role in {"ADMIN", "BATTLE_CAPTAIN"}:
        return db.query(Mission).order_by(Mission.created_at.desc()).all()
    # Regular operators only see their assigned mission
    if current.mission_id:
        m = db.get(Mission, current.mission_id)
        return [m] if m else []
    return []


@router.post("", response_model=MissionOut, status_code=status.HTTP_201_CREATED)
async def create_mission(
    payload: MissionCreate,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> Mission:
    m = Mission(
        name=payload.name,
        description=payload.description,
        created_by=current.id,
        map_center_lat=payload.map_center_lat,
        map_center_lng=payload.map_center_lng,
        map_zoom=payload.map_zoom,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    await broadcaster.broadcast({"channel": "mission", "event": "created",
                                  "data": MissionOut.model_validate(m).model_dump(mode="json")})
    return m


@router.get("/{mission_id}", response_model=MissionOut)
def get_mission(
    mission_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> Mission:
    m = db.get(Mission, mission_id)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return m


@router.patch("/{mission_id}", response_model=MissionOut)
async def update_mission(
    mission_id: int,
    payload: MissionUpdate,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> Mission:
    m = db.get(Mission, mission_id)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if payload.name is not None:
        m.name = payload.name
    if payload.description is not None:
        m.description = payload.description
    if payload.map_center_lat is not None:
        m.map_center_lat = payload.map_center_lat
    if payload.map_center_lng is not None:
        m.map_center_lng = payload.map_center_lng
    if payload.map_zoom is not None:
        m.map_zoom = payload.map_zoom
    db.commit()
    db.refresh(m)
    await broadcaster.broadcast({"channel": "mission", "event": "updated",
                                  "data": MissionOut.model_validate(m).model_dump(mode="json")})
    return m


@router.delete("/{mission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mission(
    mission_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN")),
) -> None:
    m = db.get(Mission, mission_id)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if m.status == "ACTIVE":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Cannot delete an ACTIVE mission — end it first")
    db.delete(m)
    db.commit()
    await broadcaster.broadcast({"channel": "mission", "event": "deleted",
                                  "data": {"id": mission_id}})


# ── Lifecycle ─────────────────────────────────────────────────────────────────

@router.post("/{mission_id}/start", response_model=MissionOut)
async def start_mission(
    mission_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> Mission:
    m = db.get(Mission, mission_id)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if m.status == "ACTIVE":
        return m
    if m.status == "ENDED":
        raise HTTPException(status.HTTP_409_CONFLICT, "Mission already ended")
    m.status = "ACTIVE"
    m.started_at = _utcnow()
    db.commit()
    db.refresh(m)
    await broadcaster.broadcast({"channel": "mission", "event": "started",
                                  "data": MissionOut.model_validate(m).model_dump(mode="json")})
    return m


@router.post("/{mission_id}/end", response_model=MissionOut)
async def end_mission(
    mission_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> Mission:
    m = db.get(Mission, mission_id)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if m.status == "ENDED":
        return m

    # Save full snapshot before ending
    m.snapshot    = _snapshot_mission(db, m)
    m.snapshot_at = _utcnow()
    m.status      = "ENDED"
    m.ended_at    = _utcnow()
    db.commit()
    db.refresh(m)
    await broadcaster.broadcast({"channel": "mission", "event": "ended",
                                  "data": MissionOut.model_validate(m).model_dump(mode="json")})
    return m


@router.post("/{mission_id}/reset", response_model=MissionOut)
async def reset_mission(
    mission_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> Mission:
    """Save a snapshot, then delete all mission-scoped objects.

    The mission stays ACTIVE so operators can continue; the map is wiped clean.
    Broadcasts a ``mission-reset`` event so every connected client can clear
    their local state.
    """
    m = db.get(Mission, mission_id)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    # Snapshot before wipe
    m.snapshot    = _snapshot_mission(db, m)
    m.snapshot_at = _utcnow()
    db.commit()

    # Wipe mission data (keep operators assigned)
    for cls in (TacticalObject, Alert, FireMission, Message, Report):
        db.query(cls).filter(cls.mission_id == mission_id).delete(synchronize_session=False)
    db.commit()
    db.refresh(m)

    await broadcaster.broadcast({
        "channel": "mission", "event": "reset",
        "mission_id": mission_id,
        "data": MissionOut.model_validate(m).model_dump(mode="json"),
    })
    return m


@router.get("/{mission_id}/snapshot", response_model=MissionSnapshotOut)
def get_snapshot(
    mission_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> Mission:
    m = db.get(Mission, mission_id)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not m.snapshot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No snapshot saved yet")
    return m


# ── Operator assignment ───────────────────────────────────────────────────────

@router.get("/{mission_id}/operators", response_model=list[OperatorOut])
def list_mission_operators(
    mission_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> list[Operator]:
    return db.query(Operator).filter(Operator.mission_id == mission_id).all()


@router.post("/{mission_id}/operators", status_code=status.HTTP_204_NO_CONTENT)
async def assign_operators(
    mission_id: int,
    payload: AssignOperatorsIn,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> None:
    m = db.get(Mission, mission_id)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    # Reject if any operator is already assigned to a different mission
    conflicts = []
    for op_id in payload.operator_ids:
        op = db.get(Operator, op_id)
        if op and op.mission_id is not None and op.mission_id != mission_id:
            other = db.get(Mission, op.mission_id)
            conflicts.append({
                "callsign": op.callsign,
                "mission_id": op.mission_id,
                "mission_name": other.name if other else f"#{op.mission_id}",
            })
    if conflicts:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": "Operators already assigned to another mission",
                "conflicts": conflicts,
            },
        )

    for op_id in payload.operator_ids:
        op = db.get(Operator, op_id)
        if op:
            op.mission_id = mission_id
    db.commit()
    await broadcaster.broadcast({
        "channel": "mission", "event": "operators-updated",
        "mission_id": mission_id,
        "data": {"operator_ids": payload.operator_ids},
    })


@router.delete("/{mission_id}/operators/{operator_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def remove_operator(
    mission_id: int,
    operator_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> None:
    op = db.get(Operator, operator_id)
    if op and op.mission_id == mission_id:
        op.mission_id = None
        db.commit()
