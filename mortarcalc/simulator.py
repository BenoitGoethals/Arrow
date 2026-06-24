"""Demo-scenario generator — a ready-made platoon for the Otterburn ranges.

Builds a full 81 mm mortar platoon on the **Otterburn Training Area**
(Northumberland, UK — UTM zone 30U): three sections of two tubes each, every
section with its own base gun and sector of fire (left/right limits), a
Day-of-Supply (DOS) ammunition load per tube, shared aiming points, two
Forward Observers per section, and a set of pre-plotted fire-plan targets
(incl. smoke, illumination and an FPF).

Positions are given as real WGS84 lat/lon in the training area and converted to
UTM; the battery sits on a roughly east–west gun line south of the impact area
and fires north, with the FOs on forward high ground.

Run this file (`python -m mortarcalc.simulator`) to (re)generate the bundled
scenario JSON that the app loads on a fresh start.
"""
from __future__ import annotations

# Allow running this file directly (`python .../simulator.py`): without a package
# context the relative imports below fail, so re-establish it from the source root.
if __name__ == "__main__" and not __package__:
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    __package__ = "mortarcalc"

from pathlib import Path

from .battery import Peloton, Piece, Group, AimingPoint, Observer, PlannedTarget

SCENARIO_NAME = "Otterburn Training Area"

# Day of Supply (basic load) per tube, rounds per shell type.
DOS_LOAD: dict[str, int] = {"HE": 90, "SMOKE": 18, "ILLUM": 12, "WP": 8}

# (section, pdf, left_limit, right_limit, [(gun, lat, lon, altitude_m, is_base), ...])
_SECTIONS: list[tuple[str, float, float, float, list[tuple[str, float, float, float, bool]]]] = [
    ("Charlie", 5600, 4800, 0, [
        ("C1", 55.23500, -2.22400, 282, True),
        ("C2", 55.23508, -2.22353, 283, False),
    ]),
    ("Bravo", 0, 5600, 800, [
        ("B1", 55.23500, -2.22000, 278, True),
        ("B2", 55.23508, -2.21953, 279, False),
    ]),
    ("Alpha", 800, 0, 1600, [
        ("A1", 55.23500, -2.21600, 275, True),
        ("A2", 55.23492, -2.21553, 274, False),
    ]),
]

# Shared aiming points (rear / flank reference points for laying).
_AIMING_POINTS: list[tuple[str, float, float, float]] = [
    ("RP-CAMP", 55.23000, -2.21800, 250),   # Otterburn Camp area (south)
    ("RP-MAST", 55.23300, -2.23000, 305),   # mast on the western ridge
    ("RP-FARM", 55.23200, -2.20800, 268),   # farm to the east
]

# Two FOs per section, on forward high ground (north of the impact area).
_OBSERVERS: list[tuple[str, float, float, float]] = [
    ("A-FO1", 55.26250, -2.21200, 315),
    ("A-FO2", 55.26400, -2.20800, 325),
    ("B-FO1", 55.26200, -2.22000, 320),
    ("B-FO2", 55.26350, -2.22300, 330),
    ("C-FO1", 55.26250, -2.22900, 335),
    ("C-FO2", 55.26400, -2.23300, 340),
]


def _pos(lat: float, lon: float, altitude_m: float):
    from .geo import latlon_to_utm
    return latlon_to_utm(lat, lon, altitude_m=altitude_m)


def _planned_targets() -> list[PlannedTarget]:
    """Pre-plotted fire-plan targets, each pre-assigned to the covering section."""
    return [
        PlannedTarget(
            name="AB1001", position=_pos(55.25750, -2.22000, 300),
            description="Track junction north of camp", target_type="point",
            shell="HE", fuze="quick", sheaf="converged", rounds_per_piece=2,
            suggested_group="Bravo",
        ),
        PlannedTarget(
            name="AB1002", position=_pos(55.25850, -2.21200, 295),
            description="Tree-line assembly area", target_type="area",
            shell="HE", fuze="quick", sheaf="parallel", rounds_per_piece=3,
            suggested_group="Alpha",
        ),
        PlannedTarget(
            name="AB1003", position=_pos(55.25900, -2.22900, 310),
            description="Ford / stream crossing", target_type="point",
            shell="HE", fuze="delay", sheaf="converged", rounds_per_piece=2,
            suggested_group="Charlie",
        ),
        PlannedTarget(
            name="AB1004", position=_pos(55.26000, -2.22000, 300),
            description="Smoke screen across valley track", target_type="linear",
            shell="SMOKE", fuze="time", sheaf="linear", rounds_per_piece=2,
            suggested_group="Bravo", line_azimuth_mils=1600, line_length_m=400,
            start_offset_min=0, duration_min=5,
        ),
        PlannedTarget(
            name="AB1005", position=_pos(55.26150, -2.21200, 305),
            description="Illumination — northern valley", target_type="point",
            shell="ILLUM", fuze="illum", sheaf="converged", rounds_per_piece=4,
            suggested_group="Alpha",
        ),
        PlannedTarget(
            name="FPF-BRAVO", position=_pos(55.24400, -2.22000, 290),
            description="FPF Bravo — final protective fire", target_type="linear",
            shell="HE", fuze="quick", sheaf="linear", rounds_per_piece=3,
            suggested_group="Bravo", is_fpf=True,
            line_azimuth_mils=1600, line_length_m=300,
        ),
    ]


def build_demo_peloton() -> Peloton:
    """A fully populated Otterburn platoon (3×2 tubes, limits, base guns, DOS, FOs)."""
    pel = Peloton()

    for name, pdf, left, right, guns in _SECTIONS:
        members: list[str] = []
        for gun, lat, lon, alt, is_base in guns:
            pel.add_piece(Piece(name=gun, position=_pos(lat, lon, alt), is_base=is_base))
            for shell, qty in DOS_LOAD.items():
                pel.set_ammo(gun, shell, qty)
            members.append(gun)
        pel.add_group(Group(
            name=name, pdf_mils=pdf, member_names=members,
            left_limit_mils=left, right_limit_mils=right,
        ))

    for ap_name, lat, lon, alt in _AIMING_POINTS:
        pel.add_aiming_point(AimingPoint(name=ap_name, position=_pos(lat, lon, alt)))

    for call_sign, lat, lon, alt in _OBSERVERS:
        pel.add_observer(Observer(call_sign=call_sign, position=_pos(lat, lon, alt)))

    pel.fire_plan = _planned_targets()

    return pel


def default_scenario_path() -> Path:
    """Bundled location of the generated scenario JSON."""
    return Path(__file__).resolve().parent / "data" / "scenarios" / "otterburn.json"


def write_scenario_json(path: Path | None = None) -> Path:
    """Write the demo platoon to a state JSON the app can load. Returns the path."""
    from .persistence import save_state
    target = Path(path) if path is not None else default_scenario_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    save_state(target, build_demo_peloton(), [], [])
    return target


def _print_summary(pel: Peloton) -> None:
    print(f"=== MortarCalc scenario: {SCENARIO_NAME} ===\n")
    print(f"Sections ({len(pel.groups)}):")
    for g in pel.groups:
        base = pel.base_of(g)
        print(f"  {g.name:8} PDF {int(g.pdf_mils):4d} mils  "
              f"sector {int(g.left_limit_mils)}→{int(g.right_limit_mils)} "
              f"({int(g.sector_width_mils())} mils)  "
              f"tubes {', '.join(g.member_names)}  base {base.name if base else '—'}")
    print(f"\nTubes ({len(pel.pieces)}):")
    for p in pel.pieces:
        flag = " (base)" if p.is_base else ""
        print(f"  {p.name:3}{flag:7} {p.position.to_mgrs()}  alt {p.position.altitude_m:.0f} m")
    print("\nDOS ammunition / tube: " + ", ".join(f"{s} {q}" for s, q in DOS_LOAD.items()))
    print(f"\nAiming points ({len(pel.aiming_points)}): "
          + ", ".join(a.name for a in pel.aiming_points))
    print(f"Forward Observers ({len(pel.observers)}): "
          + ", ".join(o.call_sign for o in pel.observers))
    print(f"\nFire plan ({len(pel.fire_plan)} targets):")
    for t in pel.fire_plan:
        fpf = " [FPF]" if t.is_fpf else ""
        print(f"  {t.name:9} {t.shell:5} {t.target_type:6} → {t.suggested_group:8} "
              f"{t.offset_label():8} {t.position.to_mgrs()}{fpf}  {t.description}")


def main() -> None:
    """Generate the bundled scenario JSON and print a summary."""
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    path = write_scenario_json(out)
    _print_summary(build_demo_peloton())
    print(f"\nScenario JSON written to:\n  {path}")


if __name__ == "__main__":
    main()
