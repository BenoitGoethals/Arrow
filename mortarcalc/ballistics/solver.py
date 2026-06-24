"""Ballistische oplosser: dracht + Δhoogte → lading, elevatie, TOF, drift."""
from __future__ import annotations

from dataclasses import dataclass

from ..units import normalize_mils
from .firetable import FireTable, Charge, TableRow


@dataclass(frozen=True)
class FiringSolution:
    charge: int
    elevation_mils: float        # gecompenseerd voor drift
    tof_s: float
    raw_range_m: float           # werkelijk grid-dracht
    equiv_range_m: float         # dracht na Δhoogte-correctie (input voor tabel)
    drift_mils: float


def solve(
    firetable: FireTable,
    range_m: float,
    delta_height_m: float = 0.0,
    prefer_charge: str = "lowest",
) -> FiringSolution:
    """Bereken een vuuroplossing.

    Stappen:
      1) Equivalente dracht = werkelijke dracht − Δhoogte-correctie
         (Δhoogte > 0 = doel hoger → kleinere equivalente dracht).
      2) Kies een lading die de equiv. dracht dekt.
      3) Interpoleer elevatie/TOF/drift.
      4) Compenseer azimut (in caller) voor drift door tegengestelde streep toe
         te passen op de richting; hier geven we drift terug zodat de Section
         dat per stuk kan doen.
    """
    candidate = firetable.charge_for(range_m, prefer=prefer_charge)
    equiv = _equiv_range(candidate, range_m, delta_height_m)
    # Als correctie de equiv. dracht buiten lading-bereik duwt, herzoek.
    if not candidate.covers(equiv):
        candidate = firetable.charge_for(equiv, prefer=prefer_charge)
        equiv = _equiv_range(candidate, range_m, delta_height_m)
    row: TableRow = candidate.interp(equiv)
    return FiringSolution(
        charge=candidate.id,
        elevation_mils=row.elevation_mils,
        tof_s=row.tof_s,
        raw_range_m=range_m,
        equiv_range_m=equiv,
        drift_mils=row.drift_mils,
    )


def _equiv_range(charge: Charge, range_m: float, delta_height_m: float) -> float:
    """Pas Δhoogte-correctie toe (eenvoudige eerste-orde benadering).

    Gebruikt dR/100m van de tabelrij dichtst bij de werkelijke dracht.
    Voor productie: 2-D interpolatie (range × hoek-of-hoogte) of richtige solver.
    """
    if delta_height_m == 0.0 or not charge.covers(range_m):
        return range_m
    row = charge.interp(range_m)
    return range_m - (delta_height_m / 100.0) * row.dR_per_100m_height


def apply_drift(azimuth_mils: float, drift_mils: float) -> float:
    """Compenseer voor drift: schiet links van het doel om naar rechts te driften
    (rechts-twist tube, zoals 81 mm). Drift in tabel is conventie 'naar rechts positief'.
    """
    return normalize_mils(azimuth_mils - drift_mils)
