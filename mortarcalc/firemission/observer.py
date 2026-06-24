"""Observer (FO) + polymorphic target specifications.

Each target spec knows how to resolve itself to an absolute Position, given
the FO position and the platoon (for aiming-point lookups). This replaces the
isinstance-based dispatch and follows the Open/Closed Principle: adding a
new target-call format (e.g. 'laser range/bearing from FO') means writing
a new class, not editing existing ones.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..geo import Position, offset, polar
from ..units import mils_to_rad
from ..battery import Peloton, Observer  # Observer leeft op batterijniveau (persistent)


class TargetSpec(ABC):
    """Base type for any way an FO can locate a target."""

    @abstractmethod
    def resolve(self, observer: Observer, peloton: Peloton) -> Position:
        ...


@dataclass(frozen=True)
class TargetByGrid(TargetSpec):
    """'Grid 31UDS12345678, altitude 120 m'."""
    position: Position

    def resolve(self, observer: Observer, peloton: Peloton) -> Position:
        return self.position


@dataclass(frozen=True)
class TargetByPolar(TargetSpec):
    """'Direction 2400, distance 1850, up 30' — measured from the FO."""
    azimuth_mils: float
    range_m: float
    delta_height_m: float = 0.0

    def resolve(self, observer: Observer, peloton: Peloton) -> Position:
        pos = offset(observer.position, self.azimuth_mils, self.range_m)
        return Position(
            easting=pos.easting, northing=pos.northing,
            zone=pos.zone, hemisphere=pos.hemisphere,
            altitude_m=observer.position.altitude_m + self.delta_height_m,
        )


@dataclass(frozen=True)
class TargetByShift(TargetSpec):
    """'From RP ALPHA, right 200, add 150, up 10'."""
    reference_name: str
    right_m: float = 0.0
    add_m: float = 0.0
    delta_height_m: float = 0.0

    def resolve(self, observer: Observer, peloton: Peloton) -> Position:
        ap = peloton.aiming_point(self.reference_name)
        ot = polar(observer.position, ap.position)
        ot_rad = mils_to_rad(ot.azimuth_mils)
        de = self.add_m * math.sin(ot_rad) + self.right_m * math.sin(ot_rad + math.pi / 2)
        dn = self.add_m * math.cos(ot_rad) + self.right_m * math.cos(ot_rad + math.pi / 2)
        return Position(
            easting=ap.position.easting + de,
            northing=ap.position.northing + dn,
            zone=ap.position.zone, hemisphere=ap.position.hemisphere,
            altitude_m=ap.position.altitude_m + self.delta_height_m,
        )


def resolve_target(spec: TargetSpec, observer: Observer, peloton: Peloton) -> Position:
    """Thin compatibility wrapper — delegate to the spec itself."""
    return spec.resolve(observer, peloton)
