"""Polair: afstand + azimut (in streep) tussen twee UTM-punten.

Conventie: azimut = klokwijs vanaf grid-noord, in streep (NATO 6400/cirkel).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..units import MILS_PER_CIRCLE, rad_to_mils, mils_to_rad
from .coords import Position


@dataclass(frozen=True)
class Polar:
    range_m: float
    azimuth_mils: float       # grid-azimut, klokwijs vanaf noord
    delta_height_m: float     # to - from (positief = doel ligt hoger)


def polar(from_pos: Position, to_pos: Position) -> Polar:
    """Bereken polaire vector van `from_pos` naar `to_pos`.

    Verwacht dezelfde UTM-zone. Als zones verschillen is een herprojectie nodig
    (TODO: handle cross-zone, voor 81 mm bereik <6 km zelden relevant).
    """
    if from_pos.zone != to_pos.zone or from_pos.hemisphere != to_pos.hemisphere:
        raise ValueError(
            f"UTM-zones verschillen ({from_pos.zone}{from_pos.hemisphere} vs "
            f"{to_pos.zone}{to_pos.hemisphere}); herprojectie nog niet ondersteund."
        )
    de = to_pos.easting - from_pos.easting
    dn = to_pos.northing - from_pos.northing
    range_m = math.hypot(de, dn)
    # atan2(east, north) → klokwijs vanaf noord
    az_rad = math.atan2(de, dn)
    if az_rad < 0:
        az_rad += 2 * math.pi
    return Polar(
        range_m=range_m,
        azimuth_mils=rad_to_mils(az_rad) % MILS_PER_CIRCLE,
        delta_height_m=to_pos.altitude_m - from_pos.altitude_m,
    )


def offset(origin: Position, azimuth_mils: float, range_m: float) -> Position:
    """Pas een polaire verplaatsing toe op een punt → nieuwe Position (zelfde zone, zelfde hoogte)."""
    az_rad = mils_to_rad(azimuth_mils)
    de = range_m * math.sin(az_rad)
    dn = range_m * math.cos(az_rad)
    return Position(
        easting=origin.easting + de,
        northing=origin.northing + dn,
        zone=origin.zone,
        hemisphere=origin.hemisphere,
        altitude_m=origin.altitude_m,
    )
