"""Vuurtafels: laden uit JSON + lineaire interpolatie per lading."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class TableRow:
    range_m: float
    elevation_mils: float
    tof_s: float
    drift_mils: float
    dR_per_100m_height: float   # m horizontale dracht per 100 m Δhoogte


@dataclass(frozen=True)
class Charge:
    id: int
    muzzle_velocity_mps: float
    min_range_m: float
    max_range_m: float
    rows: tuple[TableRow, ...]

    def covers(self, range_m: float) -> bool:
        return self.min_range_m <= range_m <= self.max_range_m

    def interp(self, range_m: float) -> TableRow:
        """Lineaire interpolatie van alle kolommen in functie van dracht."""
        if not self.covers(range_m):
            raise ValueError(f"Lading {self.id} dekt {range_m:.0f} m niet "
                             f"({self.min_range_m:.0f}-{self.max_range_m:.0f} m).")
        ranges = np.array([r.range_m for r in self.rows])
        def _i(col: str) -> float:
            ys = np.array([getattr(r, col) for r in self.rows])
            return float(np.interp(range_m, ranges, ys))
        return TableRow(
            range_m=range_m,
            elevation_mils=_i("elevation_mils"),
            tof_s=_i("tof_s"),
            drift_mils=_i("drift_mils"),
            dR_per_100m_height=_i("dR_per_100m_height"),
        )


@dataclass(frozen=True)
class FireTable:
    shell: str
    fuze: str
    charges: tuple[Charge, ...]

    @property
    def range_span_m(self) -> tuple[float, float]:
        """Min/max dracht (m) gedekt door alle ladingen samen."""
        return (
            min(c.min_range_m for c in self.charges),
            max(c.max_range_m for c in self.charges),
        )

    def charge_for(self, range_m: float, prefer: str = "lowest") -> Charge:
        """Kies een geschikte lading voor een gegeven dracht.

        prefer:
          - 'lowest' : laagste lading die het doel dekt (minste slijtage, kortste TOF-spread)
          - 'highest': hoogste lading die het doel dekt (steilste val, meest precies bij korte dracht)
        """
        candidates = [c for c in self.charges if c.covers(range_m)]
        if not candidates:
            raise ValueError(f"Geen lading dekt dracht {range_m:.0f} m.")
        if prefer == "highest":
            return max(candidates, key=lambda c: c.id)
        return min(candidates, key=lambda c: c.id)


def firetable_from_dict(data: dict) -> FireTable:
    """Bouw een FireTable uit een (gedeserialiseerde) JSON-structuur.

    Raises KeyError/TypeError/ValueError bij ontbrekende of foute velden — de
    aanroeper (bv. de upload-flow) vangt dit en toont een nette foutmelding.
    """
    charges = tuple(
        Charge(
            id=c["id"],
            muzzle_velocity_mps=c["muzzle_velocity_mps"],
            min_range_m=c["min_range_m"],
            max_range_m=c["max_range_m"],
            rows=tuple(
                TableRow(
                    range_m=row[0],
                    elevation_mils=row[1],
                    tof_s=row[2],
                    drift_mils=row[3],
                    dR_per_100m_height=row[4],
                )
                for row in c["rows"]
            ),
        )
        for c in data["charges"]
    )
    if not charges:
        raise ValueError("Vuurtafel bevat geen ladingen ('charges').")
    return FireTable(shell=data["shell"], fuze=data["fuze"], charges=charges)


def firetable_to_dict(ft: FireTable) -> dict:
    """Serialiseer een FireTable terug naar de JSON-structuur (round-trip)."""
    return {
        "shell": ft.shell,
        "fuze": ft.fuze,
        "charges": [
            {
                "id": c.id,
                "muzzle_velocity_mps": c.muzzle_velocity_mps,
                "min_range_m": c.min_range_m,
                "max_range_m": c.max_range_m,
                "rows": [
                    [r.range_m, r.elevation_mils, r.tof_s, r.drift_mils, r.dR_per_100m_height]
                    for r in c.rows
                ],
            }
            for c in ft.charges
        ],
    }


def load_firetable(path: str | Path) -> FireTable:
    return firetable_from_dict(json.loads(Path(path).read_text()))
