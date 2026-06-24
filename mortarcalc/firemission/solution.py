"""Per-piece firing solution + sheaf-strategy dispatcher."""
from __future__ import annotations

from dataclasses import dataclass

from ..ballistics import FireTable
from ..battery import Peloton
from .mission import FireMission, MissionState
from .sheaf_solver import solver_for


@dataclass(frozen=True)
class PieceSolution:
    piece: str
    charge: int
    elevation_mils: float
    azimuth_mils: float          # grid azimuth, drift-compensated
    deflection_mils: float       # azimuth − group PDF, mod 6400
    tof_s: float
    range_m: float


def solve_mission(
    mission: FireMission,
    peloton: Peloton,
    firetable: FireTable,
    prefer_charge: str = "lowest",
) -> list[PieceSolution]:
    """Resolve target and dispatch to the sheaf strategy."""
    group = peloton.group(mission.group_name)
    target = mission.target_spec.resolve(mission.observer, peloton)
    mission.target_position = target
    mission.state = MissionState.COMPUTED
    mission.note(f"Target resolved for group '{group.name}': {target}  ({mission.call_for_fire_brief()})")
    pieces = peloton.pieces_in(group)
    if not pieces:
        return []
    return solver_for(mission.sheaf).solve(
        mission, peloton, group, target, pieces, firetable, prefer_charge,
    )
