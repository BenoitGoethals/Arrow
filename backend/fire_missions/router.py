"""Call-for-Fire / Artillery Fire Mission endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.schemas import FireMissionIn, FireMissionOut, FireMissionUpdate
from backend.auth.jwt_auth import get_current_operator, require_role
from backend.fire_missions.ballistics import solve_mortar_plan
from backend.storage.database import get_db
from backend.storage.models import FireMission, Operator
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/fire-missions", tags=["fire-missions"])

VALID_TYPES = {"ADJUST_FIRE", "FIRE_FOR_EFFECT", "SUPPRESSION", "ILLUMINATION", "IMMEDIATE_SUPPRESSION"}
VALID_AMMO  = {"HE", "ILLUM", "SMOKE", "WP", "ICM", "MIXED", "AP", "FRAG"}
VALID_PATTERNS = {"POINT", "LINE", "ZONE"}
MORTAR_AMMO    = {"HE", "ILLUM", "SMOKE", "WP"}


# ── Mortar plan schemas ──────────────────────────────────────────────────────

class GunIn(BaseModel):
    callsign:           str   = ""
    latitude:           float
    longitude:          float
    altitude:           float = 0.0
    reference_az_mils:  float = 0.0


class MortarPlanIn(BaseModel):
    guns:            list[GunIn]   = Field(min_length=1, max_length=4)
    pattern:         str           = "POINT"
    target:          dict
    rounds_per_gun:  int           = 1
    target_alt_m:    float         = 0.0
    ammunition:      str           = "HE"
    charge_override: int | None    = None
    description:     str           = ""


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


# ── L16 81 mm mortar plan: solve + submit ───────────────────────────────────

def _validate_mortar_plan(plan: MortarPlanIn) -> tuple[str, str]:
    pattern = plan.pattern.upper()
    if pattern not in VALID_PATTERNS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"pattern must be one of {sorted(VALID_PATTERNS)}")
    ammo = plan.ammunition.upper()
    if ammo not in MORTAR_AMMO:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"ammunition must be one of {sorted(MORTAR_AMMO)} for the L16 81mm")
    return pattern, ammo


@router.post("/solve")
def solve_mortar(
    plan: MortarPlanIn,
    _:    Operator = Depends(get_current_operator),
) -> dict:
    """Compute L16 81mm firing solutions for 1..4 guns over a POINT/LINE/ZONE
    target pattern. Does NOT persist or broadcast — for the gun-line preview."""
    pattern, ammo = _validate_mortar_plan(plan)
    try:
        result = solve_mortar_plan(
            guns=[g.model_dump() for g in plan.guns],
            pattern=pattern, target=plan.target,
            rounds_per_gun=plan.rounds_per_gun,
            target_alt_m=plan.target_alt_m,
            charge_override=plan.charge_override,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    result["summary"]["ammunition"] = ammo
    return result


@router.post("/mortar", response_model=FireMissionOut, status_code=status.HTTP_201_CREATED)
async def submit_mortar(
    plan:    MortarPlanIn,
    db:      Session  = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> FireMission:
    """Persist a mortar plan as a FireMission and broadcast it. The full plan
    (per-gun firing solutions and impact points) is stored as JSON in `notes`
    so the web map can render the impact pattern.
    """
    pattern, ammo = _validate_mortar_plan(plan)
    try:
        result = solve_mortar_plan(
            guns=[g.model_dump() for g in plan.guns],
            pattern=pattern, target=plan.target,
            rounds_per_gun=plan.rounds_per_gun,
            target_alt_m=plan.target_alt_m,
            charge_override=plan.charge_override,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

    # Centroid of impacts → mission target point
    impacts = result["impacts"]
    if not impacts:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "no impact points produced")
    clat = sum(p["latitude"]  for p in impacts) / len(impacts)
    clon = sum(p["longitude"] for p in impacts) / len(impacts)

    # Use first gun's bearing-to-centroid as nominal direction
    g0 = result["guns"][0]
    direction = (g0["solutions"][0]["azimuth_mils"] * 360.0 / 6400.0) if g0["solutions"] else 0.0

    notes_blob = json.dumps({
        "weapon":    "L16_81MM",
        "ammunition": ammo,
        "pattern":   pattern,
        "target":    plan.target,
        "summary":   result["summary"],
        "guns":      result["guns"],
        "impacts":   impacts,
    }, separators=(",", ":"))

    fm = FireMission(
        operator_id  = current.id,
        latitude     = clat,
        longitude    = clon,
        altitude     = plan.target_alt_m,
        direction    = direction,
        mission_type = "FIRE_FOR_EFFECT",
        ammunition   = ammo,
        quantity     = result["summary"]["total_rounds"],
        description  = plan.description or f"L16 81mm — {pattern} sheaf",
        notes        = notes_blob,
    )
    db.add(fm); db.commit(); db.refresh(fm)

    out = FireMissionOut.model_validate(fm).model_dump(mode="json")
    await broadcaster.broadcast({
        "channel": "fire-mission",
        "event":   "submitted",
        "data": {
            **out,
            "callsign": current.callsign,
            "weapon":   "L16_81MM",
            "pattern":  pattern,
            "impacts":  impacts,
            "guns":     result["guns"],
        },
    })
    return fm


@router.patch("/{fm_id}", response_model=FireMissionOut)
async def update_mission(
    fm_id:   int,
    payload: FireMissionUpdate,
    db:      Session  = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> FireMission:
    """Acknowledge, assign to FDC, change status, or add notes. Requires BATTLE_CAPTAIN or ADMIN."""
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
