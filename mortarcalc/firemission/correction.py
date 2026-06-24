"""FO-correcties: OT-frame (right/left, add/drop) → absoluut UTM → herrekenen.

De FO meldt correcties in zijn eigen frame (loodrecht/langs de OT-lijn).
De FDC vertaalt dat naar een nieuwe doelpositie en laat solve_mission opnieuw
de elementen per stuk uitrekenen. Hierdoor blijft de wiskunde simpel en
hoeven we geen aparte 'per stuk' OT→GT transform te doen.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..geo import Position, polar
from ..units import mils_to_rad
from .mission import FireMission


@dataclass(frozen=True)
class Correction:
    """Correctie van de waarnemer t.o.v. het laatste salvo.

    Conventie: positief right = naar rechts (vanuit FO gezien),
    positief add = verder weg van FO, positief up = doel ligt hoger.
    """
    right_m: float = 0.0
    add_m: float = 0.0
    up_m: float = 0.0


def apply_correction(mission: FireMission, corr: Correction) -> Position:
    """Pas een FO-correctie toe op het huidige doel en update de mission.

    Geeft de nieuwe doelpositie terug. Roep daarna `solve_mission` opnieuw aan
    om de bijgewerkte vuurelementen te krijgen.
    """
    if mission.target_position is None:
        raise ValueError("Target position not yet computed; call solve_mission() first.")
    ot = polar(mission.observer.position, mission.target_position)
    ot_rad = mils_to_rad(ot.azimuth_mils)
    # add = langs OT (richting van het doel); right = +90° t.o.v. OT (klokwijs).
    de = corr.add_m * math.sin(ot_rad) + corr.right_m * math.sin(ot_rad + math.pi / 2)
    dn = corr.add_m * math.cos(ot_rad) + corr.right_m * math.cos(ot_rad + math.pi / 2)
    new = Position(
        easting=mission.target_position.easting + de,
        northing=mission.target_position.northing + dn,
        zone=mission.target_position.zone,
        hemisphere=mission.target_position.hemisphere,
        altitude_m=mission.target_position.altitude_m + corr.up_m,
    )
    mission.target_position = new
    mission.note(
        f"Correction R{corr.right_m:+.0f} A{corr.add_m:+.0f} U{corr.up_m:+.0f} → {new}"
    )
    return new
