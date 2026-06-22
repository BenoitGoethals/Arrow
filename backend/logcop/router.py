"""LOGCOP — Logistics Common Operational Picture API.

All endpoints are mission-scoped via the X-Mission-ID header.
Supply, vehicles, convoys, and supply-point CRUD.
ADMIN / BATTLE_CAPTAIN can write; all authenticated operators can read.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.jwt_auth import get_current_operator, require_role
from backend.missions.dependencies import get_active_mission
from backend.storage.database import get_db
from backend.storage.models import (
    LogcopConvoy,
    LogcopSupply,
    LogcopSupplyPoint,
    LogcopVehicle,
    Mission,
    Operator,
)
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/logcop", tags=["logcop"])

_SUPPLY_DEFAULTS = [
    ("I", "Food & Rations", 3.0, 2.0, 1.0, "DOS"),
    ("II", "Clothing & Equipment", 5.0, 3.0, 1.5, "DOS"),
    ("III", "POL — Fuel & Lubricants", 4.0, 2.0, 1.0, "DOS"),
    ("IIIA", "Aviation Fuel (Jet A-1/JP8)", 3.0, 2.0, 0.5, "DOS"),
    ("IV", "Construction Material", 7.0, 4.0, 2.0, "DOS"),
    ("V", "Ammunition", 3.0, 2.0, 1.0, "DOS"),
    ("VI", "Personal Demand Items", 7.0, 5.0, 2.0, "DOS"),
    ("VII", "Major End Items", 0.0, 0.0, 0.0, "units"),
    ("VIII", "Medical Supplies", 5.0, 3.0, 1.0, "DOS"),
    ("IX", "Repair Parts & Equip", 4.0, 2.0, 1.0, "DOS"),
    ("X", "Non-military Programs", 0.0, 0.0, 0.0, "units"),
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mission_id(mission: Mission | None) -> int | None:
    return mission.id if mission else None


async def _broadcast(event: str, data: dict) -> None:
    await broadcaster.broadcast({"channel": "logcop", "event": event, "data": data})


# ── Supply ────────────────────────────────────────────────────────────────────


class SupplyOut(BaseModel):
    id: int
    class_code: str
    label: str
    current_qty: float
    unit: str
    threshold_amber: float
    threshold_red: float
    notes: str
    updated_at: datetime

    class Config:
        from_attributes = True


class SupplyIn(BaseModel):
    current_qty: float
    notes: str = ""
    threshold_amber: float | None = None
    threshold_red: float | None = None


@router.get("/supply", response_model=list[SupplyOut])
def list_supply(
    db: Session = Depends(get_db),
    mission: Mission | None = Depends(get_active_mission),
    _: Operator = Depends(get_current_operator),
) -> list[LogcopSupply]:
    rows = (
        db.query(LogcopSupply)
        .filter(LogcopSupply.mission_id == _mission_id(mission))
        .order_by(LogcopSupply.id)
        .all()
    )
    if not rows:
        # Seed defaults on first access
        for code, label, qty, amber, red, unit in _SUPPLY_DEFAULTS:
            rows.append(
                LogcopSupply(
                    mission_id=_mission_id(mission),
                    class_code=code,
                    label=label,
                    current_qty=qty,
                    unit=unit,
                    threshold_amber=amber,
                    threshold_red=red,
                )
            )
        db.add_all(rows)
        db.commit()
        for r in rows:
            db.refresh(r)
    return rows


@router.patch("/supply/{supply_id}", response_model=SupplyOut)
async def update_supply(
    supply_id: int,
    payload: SupplyIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
    mission: Mission | None = Depends(get_active_mission),
) -> LogcopSupply:
    row = db.get(LogcopSupply, supply_id)
    if not row or row.mission_id != _mission_id(mission):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    row.current_qty = payload.current_qty
    row.notes = payload.notes
    if payload.threshold_amber is not None:
        row.threshold_amber = payload.threshold_amber
    if payload.threshold_red is not None:
        row.threshold_red = payload.threshold_red
    row.updated_by = current.id
    db.commit()
    db.refresh(row)
    await _broadcast(
        "supply_updated",
        {
            "id": row.id,
            "class_code": row.class_code,
            "current_qty": row.current_qty,
            "unit": row.unit,
        },
    )
    return row


# ── Vehicles ──────────────────────────────────────────────────────────────────


class VehicleOut(BaseModel):
    id: int
    unit_name: str
    vehicle_type: str
    total: int
    fmc: int
    pmc: int
    notes: str
    updated_at: datetime

    class Config:
        from_attributes = True


class VehicleIn(BaseModel):
    unit_name: str
    vehicle_type: str
    total: int
    fmc: int
    pmc: int
    notes: str = ""


@router.get("/vehicles", response_model=list[VehicleOut])
def list_vehicles(
    db: Session = Depends(get_db),
    mission: Mission | None = Depends(get_active_mission),
    _: Operator = Depends(get_current_operator),
) -> list[LogcopVehicle]:
    return (
        db.query(LogcopVehicle)
        .filter(LogcopVehicle.mission_id == _mission_id(mission))
        .order_by(LogcopVehicle.unit_name)
        .all()
    )


@router.post(
    "/vehicles", response_model=VehicleOut, status_code=status.HTTP_201_CREATED
)
async def create_vehicle(
    payload: VehicleIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
    mission: Mission | None = Depends(get_active_mission),
) -> LogcopVehicle:
    row = LogcopVehicle(
        mission_id=_mission_id(mission),
        unit_name=payload.unit_name,
        vehicle_type=payload.vehicle_type,
        total=payload.total,
        fmc=payload.fmc,
        pmc=payload.pmc,
        notes=payload.notes,
        updated_by=current.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    await _broadcast("vehicle_created", {"id": row.id})
    return row


@router.patch("/vehicles/{vid}", response_model=VehicleOut)
async def update_vehicle(
    vid: int,
    payload: VehicleIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
    mission: Mission | None = Depends(get_active_mission),
) -> LogcopVehicle:
    row = db.get(LogcopVehicle, vid)
    if not row or row.mission_id != _mission_id(mission):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    for k, v in payload.model_dump().items():
        setattr(row, k, v)
    row.updated_by = current.id
    db.commit()
    db.refresh(row)
    await _broadcast("vehicle_updated", {"id": row.id})
    return row


@router.delete("/vehicles/{vid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle(
    vid: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
    mission: Mission | None = Depends(get_active_mission),
) -> None:
    row = db.get(LogcopVehicle, vid)
    if not row or row.mission_id != _mission_id(mission):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    db.delete(row)
    db.commit()
    await _broadcast("vehicle_deleted", {"id": vid})


# ── Convoys ───────────────────────────────────────────────────────────────────


class ConvoyOut(BaseModel):
    id: int
    callsign: str
    status: str
    cargo: str
    origin: str
    destination: str
    eta: str
    lat: float | None
    lng: float | None
    notes: str
    updated_at: datetime

    class Config:
        from_attributes = True


class ConvoyIn(BaseModel):
    callsign: str
    status: str = "LOADING"
    cargo: str = ""
    origin: str = ""
    destination: str = ""
    eta: str = ""
    lat: float | None = None
    lng: float | None = None
    notes: str = ""


@router.get("/convoys", response_model=list[ConvoyOut])
def list_convoys(
    db: Session = Depends(get_db),
    mission: Mission | None = Depends(get_active_mission),
    _: Operator = Depends(get_current_operator),
) -> list[LogcopConvoy]:
    return (
        db.query(LogcopConvoy)
        .filter(LogcopConvoy.mission_id == _mission_id(mission))
        .order_by(LogcopConvoy.updated_at.desc())
        .all()
    )


@router.post("/convoys", response_model=ConvoyOut, status_code=status.HTTP_201_CREATED)
async def create_convoy(
    payload: ConvoyIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
    mission: Mission | None = Depends(get_active_mission),
) -> LogcopConvoy:
    row = LogcopConvoy(
        mission_id=_mission_id(mission),
        created_by=current.id,
        **payload.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    await _broadcast("convoy_created", {"id": row.id, "callsign": row.callsign})
    return row


@router.patch("/convoys/{cid}", response_model=ConvoyOut)
async def update_convoy(
    cid: int,
    payload: ConvoyIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
    mission: Mission | None = Depends(get_active_mission),
) -> LogcopConvoy:
    row = db.get(LogcopConvoy, cid)
    if not row or row.mission_id != _mission_id(mission):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    for k, v in payload.model_dump().items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    await _broadcast("convoy_updated", {"id": row.id, "status": row.status})
    return row


@router.delete("/convoys/{cid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_convoy(
    cid: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
    mission: Mission | None = Depends(get_active_mission),
) -> None:
    row = db.get(LogcopConvoy, cid)
    if not row or row.mission_id != _mission_id(mission):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    db.delete(row)
    db.commit()
    await _broadcast("convoy_deleted", {"id": cid})


# ── Supply points ─────────────────────────────────────────────────────────────


class SupplyPointOut(BaseModel):
    id: int
    name: str
    point_type: str
    lat: float
    lng: float
    notes: str
    created_at: datetime

    class Config:
        from_attributes = True


class SupplyPointIn(BaseModel):
    name: str
    point_type: str
    lat: float
    lng: float
    notes: str = ""


@router.get("/supply-points", response_model=list[SupplyPointOut])
def list_supply_points(
    db: Session = Depends(get_db),
    mission: Mission | None = Depends(get_active_mission),
    _: Operator = Depends(get_current_operator),
) -> list[LogcopSupplyPoint]:
    return (
        db.query(LogcopSupplyPoint)
        .filter(LogcopSupplyPoint.mission_id == _mission_id(mission))
        .all()
    )


@router.post(
    "/supply-points", response_model=SupplyPointOut, status_code=status.HTTP_201_CREATED
)
async def create_supply_point(
    payload: SupplyPointIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
    mission: Mission | None = Depends(get_active_mission),
) -> LogcopSupplyPoint:
    row = LogcopSupplyPoint(
        mission_id=_mission_id(mission),
        created_by=current.id,
        **payload.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    await _broadcast("supply_point_created", {"id": row.id, "name": row.name})
    return row


@router.delete("/supply-points/{pid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_supply_point(
    pid: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
    mission: Mission | None = Depends(get_active_mission),
) -> None:
    row = db.get(LogcopSupplyPoint, pid)
    if not row or row.mission_id != _mission_id(mission):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    db.delete(row)
    db.commit()
    await _broadcast("supply_point_deleted", {"id": pid})
