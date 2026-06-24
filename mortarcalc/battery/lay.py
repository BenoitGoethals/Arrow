"""Op waak brengen per groep: vizier-instelling per stuk op een gemeenschappelijk merkpunt.

Principe (parallellisatie binnen één groep):
  - Alle lopen van de stukken in de groep moeten evenwijdig staan met de
    waakrichting (PDF) van die groep.
  - Elk stuk in de groep richt zijn vizier op één gemeenschappelijk merkpunt.
  - Vizierinstelling per stuk = (azimut stuk→AP) − (PDF azimut), mod 6400.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..geo import polar
from ..units import normalize_mils
from .peloton import Peloton, Group, AimingPoint


@dataclass(frozen=True)
class SightSetting:
    piece: str
    group: str
    aiming_point: str
    sight_mils: float            # in te draaien op vizier (gonio-streep)
    azimuth_to_ap_mils: float    # ter info
    range_to_ap_m: float         # ter info — bij <500 m parallax-fout vermelden


def lay_on_watch(peloton: Peloton, group: Group, ap: AimingPoint) -> list[SightSetting]:
    """Bereken per stuk in de groep de vizier-instelling om op de groep-PDF te liggen."""
    out: list[SightSetting] = []
    for p in peloton.pieces_in(group):
        pol = polar(p.position, ap.position)
        out.append(SightSetting(
            piece=p.name,
            group=group.name,
            aiming_point=ap.name,
            sight_mils=normalize_mils(pol.azimuth_mils - group.pdf_mils),
            azimuth_to_ap_mils=pol.azimuth_mils,
            range_to_ap_m=pol.range_m,
        ))
    return out
