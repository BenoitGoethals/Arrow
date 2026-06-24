"""Fire plan: lijst van vooraf-uitgewerkte doelen (preplotted targets, incl. FPF).

Een PlannedTarget bevat alle CFF-elementen die nodig zijn om snel een
fire mission op te bouwen — de FDC selecteert er één en vuurt af zonder dat
de FO de volledige call hoeft te geven. Targets kunnen ook FPF-doelen zijn
(Final Protective Fire), gemarkeerd met `is_fpf=True`.

Timings volgen NATO fire-plan conventie:
  - H-hour wordt op peloton-niveau gezet (Peloton.h_hour).
  - `start_offset_min` is minuten t.o.v. H-hour (negatief = voor H, positief = na H).
  - `duration_min` is de duur van aanhoudend vuur (0 = enkele FFE).

Naming-conventie: AB1001, AB1002, ... (Belgische/NL doctrine).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..geo import Position


@dataclass
class PlannedTarget:
    """Voorbereid doel in het fire plan."""
    name: str                       # tactisch nummer, bv. "AB1001"
    position: Position              # MGRS + hoogte
    description: str = ""           # bv. "kruispunt N9 / kerk", "FPF Noord"
    target_type: str = "point"      # 'point' / 'area' / 'linear'
    shell: str = "HE"
    fuze: str = "quick"             # waarde van Fuze enum
    sheaf: str = "converged"        # waarde van Sheaf enum
    rounds_per_piece: int = 1
    suggested_group: str = ""       # optioneel: groep die normaal dit doel behandelt
    is_fpf: bool = False            # True = Final Protective Fire — krijgt prioriteit in UI
    # LINEAR sheaf:
    line_azimuth_mils: float = 0.0
    line_length_m: float = 200.0
    # Timing (t.o.v. H-hour):
    start_offset_min: int | None = None   # None = on call (geen vaste timing)
    duration_min: int = 0                  # 0 = enkele FFE; >0 = aanhoudend vuur

    # ---------- timing helpers ----------
    def offset_label(self) -> str:
        """Geef H±NN of 'On Call' terug."""
        if self.start_offset_min is None:
            return "On Call"
        if self.start_offset_min == 0:
            return "H"
        sign = "+" if self.start_offset_min > 0 else "−"
        return f"H{sign}{abs(self.start_offset_min)}"

    def scheduled_start(self, h_hour: datetime | None) -> datetime | None:
        if h_hour is None or self.start_offset_min is None:
            return None
        return h_hour + timedelta(minutes=self.start_offset_min)

    def scheduled_end(self, h_hour: datetime | None) -> datetime | None:
        start = self.scheduled_start(h_hour)
        if start is None:
            return None
        return start + timedelta(minutes=max(0, self.duration_min))

    def status_at(self, now: datetime, h_hour: datetime | None) -> str:
        """SCHEDULED / DUE / ACTIVE / PAST / ON_CALL."""
        if self.start_offset_min is None:
            return "ON_CALL"
        start = self.scheduled_start(h_hour)
        end = self.scheduled_end(h_hour)
        if start is None:
            return "SCHEDULED"
        if now < start:
            return "SCHEDULED"
        if self.duration_min > 0 and now < end:
            return "ACTIVE"
        if self.duration_min == 0 and (now - start).total_seconds() < 60:
            return "DUE"
        return "PAST"
