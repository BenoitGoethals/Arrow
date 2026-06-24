"""Save/load van peloton-configuratie + missie-historiek als JSON.

JSON-formaat (versie 1):

    {
      "version": 1,
      "peloton": {
        "pieces": [{"name", "easting", "northing", "zone", "hemisphere", "altitude_m", "is_base"}],
        "groups": [{"name", "pdf_mils", "member_names": [...], "left_limit_mils", "right_limit_mils"}],
        "aiming_points": [{"name", "easting", "northing", "zone", "hemisphere", "altitude_m"}]
      },
      "missions": [...]   # alleen historiek, geen actieve FMs
    }
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .battery import AimingPoint, Group, Peloton, Piece, PlannedTarget
from .firemission import (
    FireMission, MissionState, Observer,
    TargetByGrid, TargetByPolar, TargetByShift,
    MethodOfFire, Sheaf, TargetType, Fuze, FireControl,
)
from .firemission.solution import PieceSolution
from .geo import Position

VERSION = 5
SUPPORTED_VERSIONS = {1, 2, 3, 4, 5}


# ---------- Position helpers ----------
def _pos_to_dict(p: Position) -> dict[str, Any]:
    return {
        "easting": p.easting, "northing": p.northing,
        "zone": p.zone, "hemisphere": p.hemisphere,
        "altitude_m": p.altitude_m,
    }


def _pos_from_dict(d: dict[str, Any]) -> Position:
    return Position(
        easting=float(d["easting"]), northing=float(d["northing"]),
        zone=int(d["zone"]), hemisphere=str(d["hemisphere"]),
        altitude_m=float(d.get("altitude_m", 0.0)),
    )


# ---------- TargetSpec discriminator ----------
def _target_to_dict(t) -> dict[str, Any]:
    if isinstance(t, TargetByGrid):
        return {"kind": "grid", "position": _pos_to_dict(t.position)}
    if isinstance(t, TargetByPolar):
        return {"kind": "polar", "azimuth_mils": t.azimuth_mils,
                "range_m": t.range_m, "delta_height_m": t.delta_height_m}
    if isinstance(t, TargetByShift):
        return {"kind": "shift", "reference_name": t.reference_name,
                "right_m": t.right_m, "add_m": t.add_m, "delta_height_m": t.delta_height_m}
    raise TypeError(f"Onbekend target-type: {type(t).__name__}")


def _target_from_dict(d: dict[str, Any]):
    kind = d["kind"]
    if kind == "grid":
        return TargetByGrid(position=_pos_from_dict(d["position"]))
    if kind == "polar":
        return TargetByPolar(azimuth_mils=d["azimuth_mils"], range_m=d["range_m"],
                             delta_height_m=d.get("delta_height_m", 0.0))
    if kind == "shift":
        return TargetByShift(reference_name=d["reference_name"],
                             right_m=d.get("right_m", 0.0), add_m=d.get("add_m", 0.0),
                             delta_height_m=d.get("delta_height_m", 0.0))
    raise ValueError(f"Onbekend target-kind: {kind}")


# ---------- FireMission ----------
def _solution_to_dict(s: PieceSolution) -> dict[str, Any]:
    return asdict(s)


def _solution_from_dict(d: dict[str, Any]) -> PieceSolution:
    return PieceSolution(**d)


def _mission_to_dict(fm: FireMission) -> dict[str, Any]:
    return {
        "id": fm.id,
        "group_name": fm.group_name,
        "observer": {
            "call_sign": fm.observer.call_sign,
            "position": _pos_to_dict(fm.observer.position),
        },
        "target_spec": _target_to_dict(fm.target_spec),
        "target_description": fm.target_description,
        "target_type": fm.target_type.value,
        "shell": fm.shell,
        "fuze": fm.fuze.value,
        "method_of_fire": fm.method_of_fire.value,
        "sheaf": fm.sheaf.value,
        "rounds_per_piece": fm.rounds_per_piece,
        "line_azimuth_mils": fm.line_azimuth_mils,
        "line_length_m": fm.line_length_m,
        "control": fm.control.value,
        "state": fm.state.value,
        "target_position": _pos_to_dict(fm.target_position) if fm.target_position else None,
        "received_at": fm.received_at.isoformat(),
        "log": list(fm.log),
        "final_solutions": (
            [_solution_to_dict(s) for s in (fm.final_solutions or [])]
            if getattr(fm, "final_solutions", None) else None
        ),
        "rounds_fired": dict(fm.rounds_fired),
    }


def _mission_from_dict(d: dict[str, Any]) -> FireMission:
    fm = FireMission(
        id=d["id"],
        group_name=d["group_name"],
        observer=Observer(call_sign=d["observer"]["call_sign"],
                          position=_pos_from_dict(d["observer"]["position"])),
        target_spec=_target_from_dict(d["target_spec"]),
        target_description=d.get("target_description", ""),
        target_type=TargetType(d.get("target_type", "point")),
        shell=d.get("shell", "HE"),
        fuze=Fuze(d.get("fuze", "quick")),
        method_of_fire=MethodOfFire(d.get("method_of_fire", "AF")),
        sheaf=Sheaf(d.get("sheaf", "converged")),
        rounds_per_piece=int(d.get("rounds_per_piece", 1)),
        line_azimuth_mils=float(d.get("line_azimuth_mils", 0.0)),
        line_length_m=float(d.get("line_length_m", 200.0)),
        control=FireControl(d.get("control", "when_ready")),
        state=MissionState(d.get("state", "received")),
        target_position=_pos_from_dict(d["target_position"]) if d.get("target_position") else None,
        received_at=datetime.fromisoformat(d["received_at"]) if d.get("received_at") else datetime.now(timezone.utc),
        log=list(d.get("log", [])),
        rounds_fired=dict(d.get("rounds_fired", {})),
    )
    fs = d.get("final_solutions")
    if fs:
        fm.final_solutions = [_solution_from_dict(s) for s in fs]
    return fm


# ---------- PlannedTarget ----------
def _planned_to_dict(t: PlannedTarget) -> dict[str, Any]:
    return {
        "name": t.name, **_pos_to_dict(t.position),
        "description": t.description,
        "target_type": t.target_type,
        "shell": t.shell, "fuze": t.fuze, "sheaf": t.sheaf,
        "rounds_per_piece": t.rounds_per_piece,
        "suggested_group": t.suggested_group,
        "is_fpf": t.is_fpf,
        "line_azimuth_mils": t.line_azimuth_mils,
        "line_length_m": t.line_length_m,
        "start_offset_min": t.start_offset_min,
        "duration_min": t.duration_min,
    }


def _planned_from_dict(d: dict[str, Any]) -> PlannedTarget:
    return PlannedTarget(
        name=d["name"], position=_pos_from_dict(d),
        description=d.get("description", ""),
        target_type=d.get("target_type", "point"),
        shell=d.get("shell", "HE"),
        fuze=d.get("fuze", "quick"),
        sheaf=d.get("sheaf", "converged"),
        rounds_per_piece=int(d.get("rounds_per_piece", 1)),
        suggested_group=d.get("suggested_group", ""),
        is_fpf=bool(d.get("is_fpf", False)),
        line_azimuth_mils=float(d.get("line_azimuth_mils", 0.0)),
        line_length_m=float(d.get("line_length_m", 200.0)),
        start_offset_min=d.get("start_offset_min"),
        duration_min=int(d.get("duration_min", 0)),
    )


# ---------- Peloton ----------
def peloton_to_dict(pel: Peloton) -> dict[str, Any]:
    return {
        "pieces": [
            {"name": p.name, **_pos_to_dict(p.position), "is_base": p.is_base}
            for p in pel.pieces
        ],
        "groups": [
            {
                "name": g.name, "pdf_mils": g.pdf_mils,
                "member_names": list(g.member_names),
                "left_limit_mils": g.left_limit_mils,
                "right_limit_mils": g.right_limit_mils,
                "max_range_m": g.max_range_m,
            }
            for g in pel.groups
        ],
        "aiming_points": [
            {"name": ap.name, **_pos_to_dict(ap.position)}
            for ap in pel.aiming_points
        ],
        "observers": [
            {"call_sign": o.call_sign, **_pos_to_dict(o.position)}
            for o in pel.observers
        ],
        "ammo": {pname: dict(shells) for pname, shells in pel.ammo.items()},
        "low_ammo_threshold": pel.low_ammo_threshold,
        "fire_plan": [_planned_to_dict(t) for t in pel.fire_plan],
        "h_hour": pel.h_hour.isoformat() if pel.h_hour else None,
        "next_fm_number": pel.next_fm_number,
    }


def peloton_from_dict(d: dict[str, Any]) -> Peloton:
    pel = Peloton()
    for pd in d.get("pieces", []):
        pel.add_piece(Piece(name=pd["name"], position=_pos_from_dict(pd), is_base=bool(pd.get("is_base", False))))
    for gd in d.get("groups", []):
        pel.add_group(Group(
            name=gd["name"], pdf_mils=float(gd.get("pdf_mils", 0.0)),
            member_names=list(gd.get("member_names", [])),
            left_limit_mils=float(gd.get("left_limit_mils", 0.0)),
            right_limit_mils=float(gd.get("right_limit_mils", 0.0)),
            max_range_m=float(gd.get("max_range_m", 0.0)),
        ))
    for ad in d.get("aiming_points", []):
        pel.add_aiming_point(AimingPoint(name=ad["name"], position=_pos_from_dict(ad)))
    for od in d.get("observers", []):
        pel.add_observer(Observer(call_sign=od["call_sign"], position=_pos_from_dict(od)))
    pel.ammo = {pname: dict(shells) for pname, shells in d.get("ammo", {}).items()}
    pel.low_ammo_threshold = int(d.get("low_ammo_threshold", pel.low_ammo_threshold))
    pel.fire_plan = [_planned_from_dict(t) for t in d.get("fire_plan", [])]
    h = d.get("h_hour")
    pel.h_hour = datetime.fromisoformat(h) if h else None
    pel.next_fm_number = int(d.get("next_fm_number", 1))
    return pel


# ---------- top-level ----------
def save_state(
    path: str | Path,
    peloton: Peloton,
    history: list[FireMission] | None = None,
    active_missions: list[FireMission] | None = None,
) -> None:
    """Save full app state. Atomic write — writes to .tmp then renames."""
    payload = {
        "version": VERSION,
        "peloton": peloton_to_dict(peloton),
        "missions": [_mission_to_dict(m) for m in (history or [])],
        "active_missions": [_mission_to_dict(m) for m in (active_missions or [])],
    }
    target = Path(path)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    tmp.replace(target)  # atomic on POSIX


def load_state(path: str | Path) -> tuple[Peloton, list[FireMission], list[FireMission]]:
    """Load (peloton, history, active_missions). Older versions return [] for active."""
    data = json.loads(Path(path).read_text())
    v = data.get("version", 0)
    if v not in SUPPORTED_VERSIONS:
        raise ValueError(f"Unknown JSON version: {v} (supported: {sorted(SUPPORTED_VERSIONS)})")
    pel = peloton_from_dict(data.get("peloton", {}))
    history = [_mission_from_dict(m) for m in data.get("missions", [])]
    active = [_mission_from_dict(m) for m in data.get("active_missions", [])]
    return pel, history, active
