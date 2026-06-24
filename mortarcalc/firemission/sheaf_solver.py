"""Sheaf solvers as Strategy (SOLID — Open/Closed).

Add a new sheaf type by writing a new `SheafSolver` subclass and registering
it in `SHEAF_SOLVERS`. The dispatcher in `solution.py` looks up the right
strategy by the FireMission's sheaf value, without needing to change the
existing solvers (Open for extension, closed for modification).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..ballistics import FireTable, solve
from ..ballistics.solver import apply_drift
from ..battery import Peloton, Group, Piece
from ..geo import Position, polar, offset
from ..units import normalize_mils
from .mission import FireMission, Sheaf


class SheafSolver(ABC):
    """Compute per-piece firing solutions for a single sheaf type."""

    @abstractmethod
    def solve(
        self,
        mission: FireMission,
        peloton: Peloton,
        group: Group,
        target: Position,
        pieces: list[Piece],
        firetable: FireTable,
        prefer_charge: str,
    ) -> list:
        """Return a list of PieceSolution objects."""


class ConvergedSheaf(SheafSolver):
    """Each piece computes its own polar to the target → all rounds converge on the point."""

    def solve(self, mission, peloton, group, target, pieces, firetable, prefer_charge):
        from .solution import PieceSolution
        out: list = []
        for p in pieces:
            gt = polar(p.position, target)
            firing = solve(firetable, gt.range_m, gt.delta_height_m, prefer_charge=prefer_charge)
            az = apply_drift(gt.azimuth_mils, firing.drift_mils)
            out.append(PieceSolution(
                piece=p.name, charge=firing.charge,
                elevation_mils=firing.elevation_mils,
                azimuth_mils=az,
                deflection_mils=normalize_mils(az - group.pdf_mils),
                tof_s=firing.tof_s, range_m=gt.range_m,
            ))
        return out


class ParallelSheaf(SheafSolver):
    """All tubes parallel to the guide piece — rounds land in the gun-line pattern."""

    def solve(self, mission, peloton, group, target, pieces, firetable, prefer_charge):
        from .solution import PieceSolution
        guide = self._guide_piece(peloton, group, pieces)
        gt = polar(guide.position, target)
        firing = solve(firetable, gt.range_m, gt.delta_height_m, prefer_charge=prefer_charge)
        az = apply_drift(gt.azimuth_mils, firing.drift_mils)
        defl = normalize_mils(az - group.pdf_mils)
        base = PieceSolution(
            piece=guide.name, charge=firing.charge,
            elevation_mils=firing.elevation_mils, azimuth_mils=az,
            deflection_mils=defl, tof_s=firing.tof_s, range_m=gt.range_m,
        )
        out = [base if p.name == guide.name else PieceSolution(
            piece=p.name, charge=base.charge,
            elevation_mils=base.elevation_mils, azimuth_mils=base.azimuth_mils,
            deflection_mils=base.deflection_mils, tof_s=base.tof_s, range_m=base.range_m,
        ) for p in pieces]
        mission.note(f"Sheaf PARALLEL: all tubes parallel to {guide.name}")
        return out

    @staticmethod
    def _guide_piece(peloton: Peloton, group: Group, pieces: list[Piece]) -> Piece:
        base = peloton.base_of(group)
        if base is not None:
            return base
        return pieces[0]


class LinearSheaf(SheafSolver):
    """Distribute aim points evenly along a line (azimuth + length, centered on target)."""

    def solve(self, mission, peloton, group, target, pieces, firetable, prefer_charge):
        from .solution import PieceSolution
        n = len(pieces)
        az_line = mission.line_azimuth_mils
        length = max(0.0, mission.line_length_m)
        if n == 1:
            offsets = [0.0]
        else:
            spacing = length / (n - 1)
            offsets = [-length / 2.0 + i * spacing for i in range(n)]
        out: list = []
        for piece, off in zip(pieces, offsets):
            aim = offset(target, az_line, off)
            gt = polar(piece.position, aim)
            firing = solve(firetable, gt.range_m, gt.delta_height_m, prefer_charge=prefer_charge)
            az = apply_drift(gt.azimuth_mils, firing.drift_mils)
            out.append(PieceSolution(
                piece=piece.name, charge=firing.charge,
                elevation_mils=firing.elevation_mils, azimuth_mils=az,
                deflection_mils=normalize_mils(az - group.pdf_mils),
                tof_s=firing.tof_s, range_m=gt.range_m,
            ))
        spacing_str = f"{length/(n-1) if n > 1 else 0:.0f} m"
        mission.note(
            f"Sheaf LINEAR: {n} pieces along {length:.0f} m at azimuth {az_line:.0f} mils "
            f"(spacing {spacing_str})"
        )
        return out


# Registry — extend here to add new sheaf types.
SHEAF_SOLVERS: dict[Sheaf, SheafSolver] = {
    Sheaf.CONVERGED: ConvergedSheaf(),
    Sheaf.PARALLEL: ParallelSheaf(),
    Sheaf.LINEAR: LinearSheaf(),
}


def solver_for(sheaf: Sheaf) -> SheafSolver:
    return SHEAF_SOLVERS.get(sheaf, SHEAF_SOLVERS[Sheaf.CONVERGED])
