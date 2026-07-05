"""Strike Package — composite tactical plan for a kinetic operation."""

from __future__ import annotations

import io
import json
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from fastapi.responses import JSONResponse

from backend.auth.jwt_auth import get_current_operator, require_role
from backend.cot.cot import CotEvent
from backend.missions.dependencies import get_active_mission
from backend.storage.database import get_db
from backend.storage.models import (
    FireMission,
    Mission,
    Operator,
    Report,
    StrikePackage,
    TacticalObject,
    Vehicle,
)
from backend.vehicles.service import derived_position
from backend.strike_packages.schemas import (
    StrikePackageIn,
    StrikePackageOut,
    StrikePackageUpdate,
)
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/strike-packages", tags=["strike-packages"])

VALID_STATUSES = {"PLANNING", "ACTIVE", "COMPLETE", "ABORTED"}


# ── helpers ───────────────────────────────────────────────────────────────────


def _get_or_404(db: Session, pkg_id: int) -> StrikePackage:
    pkg = db.get(StrikePackage, pkg_id)
    if not pkg:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strike package not found")
    return pkg


async def _broadcast(event: str, pkg: StrikePackage, extra: dict | None = None) -> None:
    data: dict = {"id": pkg.id, "name": pkg.name, "status": pkg.status}
    if extra:
        data.update(extra)
    await broadcaster.broadcast(
        {
            "channel": "strike-package",
            "event": event,
            "mission_id": pkg.mission_id,
            "data": data,
        }
    )


# ── list / get ────────────────────────────────────────────────────────────────


@router.get("", response_model=list[StrikePackageOut])
def list_packages(
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> list[StrikePackage]:
    q = db.query(StrikePackage).order_by(StrikePackage.created_at.desc())
    if mission:
        q = q.filter(StrikePackage.mission_id == mission.id)
    q = q.filter(StrikePackage.classification <= current.clearance)
    return q.limit(100).all()


@router.get("/{pkg_id}", response_model=StrikePackageOut)
def get_package(
    pkg_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> StrikePackage:
    return _get_or_404(db, pkg_id)


# ── create / update / delete ──────────────────────────────────────────────────


@router.post("", response_model=StrikePackageOut, status_code=status.HTTP_201_CREATED)
async def create_package(
    payload: StrikePackageIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
    mission: Mission | None = Depends(get_active_mission),
) -> StrikePackage:
    from backend.classification import resolve_default_and_cap

    pkg = StrikePackage(
        name=payload.name,
        mission_id=payload.mission_id or (mission.id if mission else None),
        created_by=current.id,
        classification=resolve_default_and_cap(mission, current, None),
        target_lat=payload.target_lat,
        target_lon=payload.target_lon,
        target_description=payload.target_description,
        operator_ids=json.dumps(payload.operator_ids),
        tactical_object_ids=json.dumps(payload.tactical_object_ids),
        fire_mission_ids=json.dumps(payload.fire_mission_ids),
        report_ids=json.dumps(payload.report_ids),
        vehicle_ids=json.dumps(payload.vehicle_ids),
        assets=payload.assets.model_dump_json(),
    )
    db.add(pkg)
    db.commit()
    db.refresh(pkg)
    await _broadcast("created", pkg, {"created_by": current.callsign})
    return pkg


@router.patch("/{pkg_id}", response_model=StrikePackageOut)
async def update_package(
    pkg_id: int,
    payload: StrikePackageUpdate,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> StrikePackage:
    pkg = _get_or_404(db, pkg_id)

    if payload.name is not None:
        pkg.name = payload.name
    if payload.target_lat is not None:
        pkg.target_lat = payload.target_lat
    if payload.target_lon is not None:
        pkg.target_lon = payload.target_lon
    if payload.target_description is not None:
        pkg.target_description = payload.target_description
    if payload.operator_ids is not None:
        pkg.operator_ids = json.dumps(payload.operator_ids)
    if payload.tactical_object_ids is not None:
        pkg.tactical_object_ids = json.dumps(payload.tactical_object_ids)
    if payload.fire_mission_ids is not None:
        pkg.fire_mission_ids = json.dumps(payload.fire_mission_ids)
    if payload.report_ids is not None:
        pkg.report_ids = json.dumps(payload.report_ids)
    if payload.vehicle_ids is not None:
        pkg.vehicle_ids = json.dumps(payload.vehicle_ids)
    if payload.assets is not None:
        pkg.assets = payload.assets.model_dump_json()

    db.commit()
    db.refresh(pkg)
    await _broadcast("updated", pkg)
    return pkg


@router.delete("/{pkg_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_package(
    pkg_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> None:
    pkg = _get_or_404(db, pkg_id)
    mid = pkg.mission_id
    db.delete(pkg)
    db.commit()
    await broadcaster.broadcast(
        {
            "channel": "strike-package",
            "event": "deleted",
            "mission_id": mid,
            "data": {"id": pkg_id},
        }
    )


# ── lifecycle ─────────────────────────────────────────────────────────────────


@router.post("/{pkg_id}/activate", response_model=StrikePackageOut)
async def activate_package(
    pkg_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> StrikePackage:
    pkg = _get_or_404(db, pkg_id)
    if pkg.status not in ("PLANNING",):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Cannot activate package in status {pkg.status}"
        )
    pkg.status = "ACTIVE"
    db.commit()
    db.refresh(pkg)
    await _broadcast("activated", pkg)
    return pkg


@router.post("/{pkg_id}/complete", response_model=StrikePackageOut)
async def complete_package(
    pkg_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> StrikePackage:
    pkg = _get_or_404(db, pkg_id)
    pkg.status = "COMPLETE"
    db.commit()
    db.refresh(pkg)
    await _broadcast("completed", pkg)
    return pkg


@router.post("/{pkg_id}/abort", response_model=StrikePackageOut)
async def abort_package(
    pkg_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> StrikePackage:
    pkg = _get_or_404(db, pkg_id)
    pkg.status = "ABORTED"
    db.commit()
    db.refresh(pkg)
    await _broadcast("aborted", pkg)
    return pkg


# ── TAK / ATAK CoT data-package export ───────────────────────────────────────


@router.get("/{pkg_id}/bundle")
def bundle(
    pkg_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> JSONResponse:
    """Fully-resolved bundle for Android offline storage.

    Expands all id-lists into their full objects so the app can display
    everything on the map without further network calls.
    """
    pkg = _get_or_404(db, pkg_id)

    op_ids = json.loads(pkg.operator_ids or "[]")
    to_ids = json.loads(pkg.tactical_object_ids or "[]")
    fm_ids = json.loads(pkg.fire_mission_ids or "[]")
    rep_ids = json.loads(pkg.report_ids or "[]")
    veh_ids = json.loads(pkg.vehicle_ids or "[]")
    assets = json.loads(pkg.assets or "{}")

    def _op(op: Operator) -> dict:
        return {
            "id": op.id,
            "callsign": op.callsign,
            "rank": op.rank,
            "role": op.role,
            "status": op.status,
            "latitude": op.latitude,
            "longitude": op.longitude,
        }

    def _to(t: TacticalObject) -> dict:
        return {
            "id": t.id,
            "type": t.type,
            "symbol_code": t.symbol_code,
            "latitude": t.latitude,
            "longitude": t.longitude,
            "notes": t.notes,
            "geometry": t.geometry,
            "affiliation": t.affiliation,
            "echelon": t.echelon,
            "rotation": t.rotation,
        }

    def _fm(f: FireMission) -> dict:
        return {
            "id": f.id,
            "latitude": f.latitude,
            "longitude": f.longitude,
            "mission_type": f.mission_type,
            "ammunition": f.ammunition,
            "status": f.status,
            "quantity": f.quantity,
        }

    def _rep(r: Report) -> dict:
        return {
            "id": r.id,
            "type": r.type,
            "status": r.status,
            "payload": json.loads(r.payload or "{}"),
        }

    def _veh(v: Vehicle) -> dict:
        lat, lon, _online = derived_position(db, v)
        return {
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
        }

    ops = [_op(db.get(Operator, oid)) for oid in op_ids if db.get(Operator, oid)]  # type: ignore[arg-type]
    tos = [
        _to(db.get(TacticalObject, tid))  # type: ignore[arg-type]
        for tid in to_ids
        if db.get(TacticalObject, tid)
    ]
    fms = [_fm(db.get(FireMission, fid)) for fid in fm_ids if db.get(FireMission, fid)]  # type: ignore[arg-type]
    reps = [_rep(db.get(Report, rid)) for rid in rep_ids if db.get(Report, rid)]  # type: ignore[arg-type]
    vehs = [_veh(db.get(Vehicle, vid)) for vid in veh_ids if db.get(Vehicle, vid)]  # type: ignore[arg-type]

    return JSONResponse(
        {
            "id": pkg.id,
            "name": pkg.name,
            "status": pkg.status,
            "mission_id": pkg.mission_id,
            "created_at": pkg.created_at.isoformat(),
            "updated_at": pkg.updated_at.isoformat(),
            "target_lat": pkg.target_lat,
            "target_lon": pkg.target_lon,
            "target_description": pkg.target_description,
            "assets": assets,
            "operators": ops,
            "tactical_objects": tos,
            "fire_missions": fms,
            "reports": reps,
            "vehicles": vehs,
        }
    )


@router.get("/{pkg_id}/cot-export")
def export_cot(
    pkg_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> Response:
    """Export as a TAK Data Package (.zip) for direct ATAK/WinTAK import.

    Produces a CoT event for every geo-located element in the package:
    - Primary target (hostile marker)
    - Assigned operators (friendly ground units)
    - Drones at their loiter areas (friendly UAS)
    - Air support callsigns at target coords (friendly fixed-wing)
    - Sniper hides (friendly ground sniper)
    - Linked tactical objects re-encoded as CoT points
    - Exfil route anchors (friendly route marker)
    """
    pkg = _get_or_404(db, pkg_id)
    assets = json.loads(pkg.assets or "{}")
    op_ids = json.loads(pkg.operator_ids or "[]")
    to_ids = json.loads(pkg.tactical_object_ids or "[]")

    events: list[bytes] = []

    # Target
    if pkg.target_lat is not None and pkg.target_lon is not None:
        events.append(
            CotEvent(
                uid=f"ARROW.SP-{pkg.id}.TARGET",
                cot_type="a-h-G-U-C",
                lat=pkg.target_lat,
                lon=pkg.target_lon,
                callsign=pkg.target_description or pkg.name,
            ).to_xml()
        )

    # Operators
    for op_id in op_ids:
        op = db.get(Operator, op_id)
        if op and op.latitude is not None and op.longitude is not None:
            events.append(
                CotEvent(
                    uid=f"ARROW.{op.callsign}",
                    cot_type="a-f-G-U-C",
                    lat=op.latitude,
                    lon=op.longitude,
                    callsign=op.callsign,
                    role=op.role,
                ).to_xml()
            )

    # Drones
    for i, drone in enumerate(assets.get("drones", [])):
        if drone.get("loiter_lat") and drone.get("loiter_lon"):
            events.append(
                CotEvent(
                    uid=f"ARROW.SP-{pkg.id}.DRONE-{i}",
                    cot_type="a-f-A-M-F-Q",  # friendly fixed-wing UAS
                    lat=float(drone["loiter_lat"]),
                    lon=float(drone["loiter_lon"]),
                    callsign=drone.get("callsign") or f"DRONE-{i+1}",
                ).to_xml()
            )

    # Air support — placed at target coords as CAS marker
    for i, cas in enumerate(assets.get("air_support", [])):
        if pkg.target_lat is not None:
            events.append(
                CotEvent(
                    uid=f"ARROW.SP-{pkg.id}.CAS-{i}",
                    cot_type="a-f-A-M-F",  # friendly fixed-wing
                    lat=pkg.target_lat,
                    lon=pkg.target_lon or 0.0,
                    callsign=cas.get("callsign") or f"CAS-{i+1}",
                ).to_xml()
            )

    # Sniper overwatch
    for i, sn in enumerate(assets.get("sniper_overwatch", [])):
        if sn.get("position_lat") and sn.get("position_lon"):
            events.append(
                CotEvent(
                    uid=f"ARROW.SP-{pkg.id}.SNIPER-{i}",
                    cot_type="a-f-G-U-C-S",  # friendly sniper
                    lat=float(sn["position_lat"]),
                    lon=float(sn["position_lon"]),
                    callsign=sn.get("callsign") or f"SNIPER-{i+1}",
                ).to_xml()
            )

    # EW assets — placed at target area
    for i, ew in enumerate(assets.get("electronic_warfare", [])):
        if pkg.target_lat is not None:
            events.append(
                CotEvent(
                    uid=f"ARROW.SP-{pkg.id}.EW-{i}",
                    cot_type="a-f-G-E-W",  # friendly ground EW
                    lat=pkg.target_lat,
                    lon=pkg.target_lon or 0.0,
                    callsign=ew.get("callsign") or f"EW-{i+1}",
                ).to_xml()
            )

    # Tactical objects (routes, objectives)
    for to_id in to_ids:
        tobj = db.get(TacticalObject, to_id)
        if tobj:
            events.append(
                CotEvent(
                    uid=f"ARROW.TO-{tobj.id}",
                    cot_type="a-f-G-U-C",
                    lat=tobj.latitude,
                    lon=tobj.longitude,
                    callsign=(
                        f"{tobj.type}: {tobj.notes[:40]}" if tobj.notes else tobj.type
                    ),
                ).to_xml()
            )

    # Build TAK Data Package zip
    buf = io.BytesIO()
    manifest_entries: list[str] = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, xml_bytes in enumerate(events):
            fname = f"cot/event_{i:03d}.cot"
            zf.writestr(fname, xml_bytes)
            manifest_entries.append(f'    <Content zipEntry="{fname}" ignore="false"/>')

        manifest = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<MissionPackageManifest version="2">\n'
            "  <Configuration>\n"
            f'    <Parameter name="uid" value="ARROW-SP-{pkg.id}"/>\n'
            f'    <Parameter name="name" value="{pkg.name}"/>\n'
            "  </Configuration>\n"
            "  <Contents>\n"
            + "\n".join(manifest_entries)
            + "\n  </Contents>\n</MissionPackageManifest>"
        )
        zf.writestr("MANIFEST/manifest.xml", manifest)

    buf.seek(0)
    safe_name = pkg.name.replace(" ", "_").replace("/", "-")
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="SP_{safe_name}.zip"'},
    )
