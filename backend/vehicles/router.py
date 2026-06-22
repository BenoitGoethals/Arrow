"""Vehicles — generic per-unit materiel shown on the tactical map.

A vehicle is assigned to a single operator or a whole team and inherits its
map position from that operator (see ``vehicles.service.derived_position``).
Reads are open to any authenticated operator; writes are BC/ADMIN only and
broadcast on the ``vehicle`` channel so every connected map updates live.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.audit import log_event
from backend.auth.jwt_auth import get_current_operator, require_role
from backend.missions.dependencies import get_active_mission
from backend.storage.database import get_db
from backend.storage.models import Mission, Operator, Vehicle
from backend.vehicles.schemas import VehicleIn, VehicleOut, VehicleUpdate
from backend.vehicles.service import derived_position
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/vehicles", tags=["vehicles"])

VALID_OPS_STATUS = {"OPS", "INOPS", "KIA", "MIA"}
VALID_AFFILIATION = {"FRIENDLY", "ENEMY", "UNKNOWN", "NEUTRAL"}


def _out(db: Session, v: Vehicle) -> VehicleOut:
    out = VehicleOut.model_validate(v)
    out.latitude, out.longitude, out.online = derived_position(db, v)
    return out


def _validate(affiliation: str | None, ops_status: str | None) -> None:
    if affiliation is not None and affiliation.upper() not in VALID_AFFILIATION:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"affiliation must be one of {sorted(VALID_AFFILIATION)}",
        )
    if ops_status is not None and ops_status.upper() not in VALID_OPS_STATUS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"ops_status must be one of {sorted(VALID_OPS_STATUS)}",
        )


async def _broadcast(event: str, v: Vehicle, db: Session) -> None:
    lat, lon, online = derived_position(db, v)
    await broadcaster.broadcast(
        {
            "channel": "vehicle",
            "event": event,
            "mission_id": v.mission_id,
            "data": {
                "id": v.id,
                "callsign": v.callsign,
                "vehicle_type": v.vehicle_type,
                "symbol_code": v.symbol_code,
                "affiliation": v.affiliation,
                "ops_status": v.ops_status,
                "team_id": v.team_id,
                "operator_id": v.operator_id,
                "latitude": lat,
                "longitude": lon,
                "online": online,
            },
        }
    )


@router.get("", response_model=list[VehicleOut])
def list_vehicles(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> list[VehicleOut]:
    q = db.query(Vehicle)
    if mission:
        q = q.filter(
            (Vehicle.mission_id == mission.id) | (Vehicle.mission_id.is_(None))
        )
    return [_out(db, v) for v in q.all()]


@router.get("/{vehicle_id}", response_model=VehicleOut)
def get_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> VehicleOut:
    v = db.get(Vehicle, vehicle_id)
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return _out(db, v)


@router.post("", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    payload: VehicleIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
    mission: Mission | None = Depends(get_active_mission),
) -> VehicleOut:
    _validate(payload.affiliation, payload.ops_status)
    v = Vehicle(
        callsign=payload.callsign,
        vehicle_type=payload.vehicle_type,
        symbol_code=payload.symbol_code,
        affiliation=payload.affiliation.upper(),
        ops_status=payload.ops_status.upper(),
        team_id=payload.team_id,
        operator_id=payload.operator_id,
        mission_id=payload.mission_id or (mission.id if mission else None),
        notes=payload.notes,
        created_by=current.id,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    log_event(
        db,
        "VEHICLE_CREATE",
        operator_id=current.id,
        resource=f"vehicle:{v.id}",
        detail=v.callsign,
    )
    await _broadcast("created", v, db)
    return _out(db, v)


@router.patch("/{vehicle_id}", response_model=VehicleOut)
async def update_vehicle(
    vehicle_id: int,
    payload: VehicleUpdate,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> VehicleOut:
    v = db.get(Vehicle, vehicle_id)
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    _validate(payload.affiliation, payload.ops_status)
    changes = payload.model_dump(exclude_unset=True)
    if "affiliation" in changes and changes["affiliation"]:
        changes["affiliation"] = changes["affiliation"].upper()
    if "ops_status" in changes and changes["ops_status"]:
        changes["ops_status"] = changes["ops_status"].upper()
    for field, value in changes.items():
        setattr(v, field, value)
    db.commit()
    db.refresh(v)
    log_event(
        db,
        "VEHICLE_UPDATE",
        operator_id=current.id,
        resource=f"vehicle:{vehicle_id}",
        detail=str(changes),
    )
    await _broadcast("updated", v, db)
    return _out(db, v)


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> None:
    v = db.get(Vehicle, vehicle_id)
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    mid, callsign = v.mission_id, v.callsign
    db.delete(v)
    db.commit()
    log_event(
        db,
        "VEHICLE_DELETE",
        operator_id=current.id,
        resource=f"vehicle:{vehicle_id}",
        detail=callsign,
    )
    await broadcaster.broadcast(
        {
            "channel": "vehicle",
            "event": "deleted",
            "mission_id": mid,
            "data": {"id": vehicle_id},
        }
    )
