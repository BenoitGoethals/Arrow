"""CAS (Close Air Support) — 9-liner requests and asset capacity management."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas import (
    CasAssetIn,
    CasAssetOut,
    CasAssetUpdate,
    CasNineLinerIn,
    ReportOut,
)
from backend.audit import log_event
from backend.auth.jwt_auth import get_current_operator, require_role
from backend.missions.dependencies import get_active_mission
from backend.storage.database import get_db
from backend.storage.models import CasAsset, Mission, Operator, Report
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/cas", tags=["cas"])

_VALID_ASSET_STATUSES = {"AVAILABLE", "ON_STATION", "TASKED", "RTB", "UNAVAILABLE"}

# ── CAS Assets (capacity management) ────────────────────────────────────────


@router.get("/assets", response_model=list[CasAssetOut])
def list_assets(
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> list[CasAsset]:
    q = db.query(CasAsset).order_by(
        CasAsset.available_from.nulls_last(), CasAsset.callsign
    )
    if mission:
        q = q.filter(
            (CasAsset.mission_id == mission.id) | (CasAsset.mission_id.is_(None))
        )
    return q.all()


@router.post("/assets", response_model=CasAssetOut, status_code=status.HTTP_201_CREATED)
async def create_asset(
    body: CasAssetIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
    mission: Mission | None = Depends(get_active_mission),
) -> CasAsset:
    if body.status not in _VALID_ASSET_STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"status must be one of {sorted(_VALID_ASSET_STATUSES)}",
        )
    asset = CasAsset(
        callsign=body.callsign,
        aircraft_type=body.aircraft_type,
        ordnance=body.ordnance,
        frequency=body.frequency,
        status=body.status,
        available_from=body.available_from,
        available_to=body.available_to,
        notes=body.notes,
        mission_id=body.mission_id or (mission.id if mission else None),
        created_by=current.id,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    await broadcaster.broadcast(
        {
            "channel": "cas",
            "event": "asset_created",
            "data": _asset_dict(asset),
        }
    )
    log_event(
        db,
        "CAS_ASSET_CREATED",
        operator_id=current.id,
        resource=f"cas_asset:{asset.id}",
        detail=f"callsign={asset.callsign} type={asset.aircraft_type}",
    )
    return asset


@router.patch("/assets/{asset_id}", response_model=CasAssetOut)
async def update_asset(
    asset_id: int,
    body: CasAssetUpdate,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> CasAsset:
    asset = db.get(CasAsset, asset_id)
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CAS asset not found")

    if body.callsign is not None:
        asset.callsign = body.callsign
    if body.aircraft_type is not None:
        asset.aircraft_type = body.aircraft_type
    if body.ordnance is not None:
        asset.ordnance = body.ordnance
    if body.frequency is not None:
        asset.frequency = body.frequency
    if body.notes is not None:
        asset.notes = body.notes
    if body.available_from is not None:
        asset.available_from = body.available_from
    if body.available_to is not None:
        asset.available_to = body.available_to
    if body.status is not None:
        if body.status not in _VALID_ASSET_STATUSES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"status must be one of {sorted(_VALID_ASSET_STATUSES)}",
            )
        asset.status = body.status

    db.commit()
    db.refresh(asset)

    await broadcaster.broadcast(
        {
            "channel": "cas",
            "event": "asset_updated",
            "data": _asset_dict(asset),
        }
    )
    log_event(
        db,
        "CAS_ASSET_UPDATED",
        operator_id=current.id,
        resource=f"cas_asset:{asset_id}",
        detail=f"status={asset.status}",
    )
    return asset


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> None:
    asset = db.get(CasAsset, asset_id)
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CAS asset not found")
    db.delete(asset)
    db.commit()
    await broadcaster.broadcast(
        {
            "channel": "cas",
            "event": "asset_deleted",
            "data": {"id": asset_id},
        }
    )
    log_event(
        db,
        "CAS_ASSET_DELETED",
        operator_id=current.id,
        resource=f"cas_asset:{asset_id}",
    )


# ── CAS 9-liner request ──────────────────────────────────────────────────────


@router.post("/requests", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def submit_cas_request(
    body: CasNineLinerIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> Report:
    """Submit a CAS 9-liner.

    Persisted as a ``Report`` with type ``CAS`` so the existing reports
    pipeline (status lifecycle, web table, history, strike package bundle)
    all work without changes.  Extra CAS fields (TIC flag, FO assignment,
    asset nomination) are stored both in the payload JSON and as proper
    columns so the backend can query them.
    """
    # Validate FO operator exists if provided
    if body.fo_operator_id is not None:
        fo = db.get(Operator, body.fo_operator_id)
        if not fo:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "FO operator not found"
            )

    # Build structured payload
    payload = {
        "line_1": body.line_1,
        "label_1": "IP (Initial Point)",
        "line_2": body.line_2,
        "label_2": "Heading / Distance",
        "line_3": body.line_3,
        "label_3": "Target elevation MSL",
        "line_4": body.line_4,
        "label_4": "Target description",
        "line_5": body.line_5_mgrs,
        "label_5": "Target location",
        "line_5_mgrs": body.line_5_mgrs,
        "line_5_lat": body.line_5_lat,
        "line_5_lon": body.line_5_lon,
        "line_6": body.line_6,
        "label_6": "Type of mark",
        "line_7": body.line_7,
        "label_7": "Friendly location",
        "line_8": body.line_8,
        "label_8": "Egress direction",
        "line_9": body.line_9,
        "label_9": "Remarks / Threats",
        "tic": body.tic,
        "fo_operator_id": body.fo_operator_id,
        "asset_id": body.asset_id,
        "dtg": datetime.now(timezone.utc).isoformat(),
    }

    rep = Report(
        type="CAS",
        operator_id=current.id,
        payload=json.dumps(payload),
        status="RECEIVED",
        fo_operator_id=body.fo_operator_id,
        tic=body.tic,
        mission_id=mission.id if mission else current.mission_id,
    )
    db.add(rep)

    # Mark nominated asset as TASKED
    if body.asset_id is not None:
        asset = db.get(CasAsset, body.asset_id)
        if asset:
            asset.status = "TASKED"

    db.commit()
    db.refresh(rep)

    # Resolve FO callsign for the broadcast
    fo_callsign = None
    if body.fo_operator_id:
        fo = db.get(Operator, body.fo_operator_id)
        fo_callsign = fo.callsign if fo else None

    await broadcaster.broadcast(
        {
            "channel": "cas",
            "event": "request",
            "mission_id": rep.mission_id,
            "data": {
                "id": rep.id,
                "type": "CAS",
                "status": rep.status,
                "operator_id": rep.operator_id,
                "operator_callsign": current.callsign,
                "tic": rep.tic,
                "fo_operator_id": rep.fo_operator_id,
                "fo_callsign": fo_callsign,
                "asset_id": body.asset_id,
                "target_location": body.line_5_mgrs,
                "target_lat": body.line_5_lat,
                "target_lon": body.line_5_lon,
                "target_desc": body.line_4,
                "payload": payload,
            },
        }
    )

    log_event(
        db,
        "CAS_REQUEST_SUBMITTED",
        operator_id=current.id,
        resource=f"report:{rep.id}",
        detail=f"tic={rep.tic} fo={body.fo_operator_id} asset={body.asset_id}",
    )
    return rep


# ── Helpers ──────────────────────────────────────────────────────────────────


def _asset_dict(a: CasAsset) -> dict:
    return {
        "id": a.id,
        "callsign": a.callsign,
        "aircraft_type": a.aircraft_type,
        "ordnance": a.ordnance,
        "frequency": a.frequency,
        "status": a.status,
        "available_from": a.available_from.isoformat() if a.available_from else None,
        "available_to": a.available_to.isoformat() if a.available_to else None,
        "notes": a.notes,
        "mission_id": a.mission_id,
    }
