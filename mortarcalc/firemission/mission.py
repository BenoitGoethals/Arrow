"""Fire Mission — volledige NATO call-for-fire elementen.

Standaard 6-element call from FO (vereenvoudigd):
  1. Observer ID + warning order   → mission.observer + mission.id
  2. Target location               → mission.target_spec
  3. Target description            → mission.target_description + target_type
  4. Method of engagement          → shell, fuze, method_of_fire, sheaf, rounds_per_piece
  5. Method of fire and control    → control
  6. End of mission / refinement   → state, log
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from ..geo import Position
from .observer import Observer, TargetSpec

if TYPE_CHECKING:
    from .solution import PieceSolution


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MissionState(str, Enum):
    """Standard NATO FM 3-09 fire mission phases (FDC perspective)."""
    RECEIVED = "received"                # CFF received from FO
    COMPUTED = "computed"                # firing data computed
    MTO_SENT = "mto_sent"                # Message To Observer sent
    READY = "ready"                      # guns laid, ready to fire
    SHOT = "shot"                        # round(s) in flight ("Shot, over")
    SPLASH = "splash"                    # ~5 s before impact ("Splash, over")
    ADJUSTING = "adjusting"              # awaiting / received FO correction
    IN_EFFECT = "in_effect"              # Fire For Effect in progress
    ROUNDS_COMPLETE = "rounds_complete"  # all FFE rounds out ("Rounds Complete, over")
    END_OF_MISSION = "end_of_mission"


class MethodOfFire(str, Enum):
    """Hoe het vuur wordt afgegeven."""
    AF = "AF"                       # Adjust Fire — 1 stuk, 1 rond, FO past aan
    FFE = "FFE"                     # Fire For Effect — alle stukken, vooraf bepaald aantal rondes
    FPF = "FPF"                     # Final Protective Fire — vooraf vastgelegd defensief vuur


class Sheaf(str, Enum):
    """Vuurpatroon van de stukken op het doel."""
    PARALLEL = "parallel"           # alle lopen evenwijdig (default, salvo valt in patroon)
    CONVERGED = "converged"         # alle stukken op exact zelfde punt (puntdoel)
    LINEAR = "linear"               # verdeeld over een lijn (lijndoel)


class TargetType(str, Enum):
    POINT = "point"                 # puntdoel (vrachtwagen, mortierstelling)
    AREA = "area"                   # gebiedsdoel (troops in open)
    LINEAR = "linear"               # lijndoel (loopgraaf, weg)


class Fuze(str, Enum):
    QUICK = "quick"                 # PD — explodeert bij impact
    DELAY = "delay"                 # vertraging — penetreert dan exploit
    VT = "vt"                       # variable time / proximity
    TIME = "time"                   # ingestelde tijd voor airburst
    ILLUM = "illum"                 # licht-munitie


class FireControl(str, Enum):
    WHEN_READY = "when_ready"       # vuur openen zodra elementen berekend en stuk klaar
    AT_MY_COMMAND = "at_my_command" # wachten op FO-bevel
    TOT = "tot"                     # Time on Target — gecoördineerde aankomst


@dataclass
class FireMission:
    """Een complete vuuropdracht, gekoppeld aan één groep."""
    id: str
    group_name: str

    # element 1
    observer: Observer

    # element 2
    target_spec: TargetSpec

    # element 3
    target_description: str = ""
    target_type: TargetType = TargetType.POINT

    # element 4 — method of engagement
    shell: str = "HE"
    fuze: Fuze = Fuze.QUICK
    method_of_fire: MethodOfFire = MethodOfFire.AF
    sheaf: Sheaf = Sheaf.CONVERGED
    rounds_per_piece: int = 1       # gepland aantal rondes per stuk (voor FFE)

    # LINEAR sheaf parameters (alleen relevant als sheaf == LINEAR)
    line_azimuth_mils: float = 0.0  # oriëntatie van de lijn (grid-azimut)
    line_length_m: float = 200.0    # totale lengte van de lijn

    # element 5 — method of fire and control
    control: FireControl = FireControl.WHEN_READY

    # runtime state
    state: MissionState = MissionState.RECEIVED
    target_position: Position | None = None
    received_at: datetime = field(default_factory=_utcnow)
    log: list[str] = field(default_factory=list)
    final_solutions: list["PieceSolution"] | None = None

    # munitie-tracking: aantal rondes werkelijk afgegeven, per stuk-naam
    rounds_fired: dict[str, int] = field(default_factory=dict)

    # ---------- helpers ----------
    def note(self, msg: str) -> None:
        self.log.append(f"{_utcnow().isoformat(timespec='seconds')}  {msg}")

    def record_salvo(self, piece_names: list[str], rounds: int = 1) -> None:
        """Record a salvo: for each piece in `piece_names`, add `rounds` rounds fired."""
        for name in piece_names:
            self.rounds_fired[name] = self.rounds_fired.get(name, 0) + rounds
        self.note(f"Salvo: {rounds} rnd/piece × {len(piece_names)} pieces ({', '.join(piece_names)})")

    def total_rounds_fired(self) -> int:
        return sum(self.rounds_fired.values())

    def rounds_remaining(self, piece_name: str) -> int:
        """Planned minus fired rounds for this piece (may be negative if over-fired)."""
        return self.rounds_per_piece - self.rounds_fired.get(piece_name, 0)

    def call_for_fire_brief(self) -> str:
        """One-line CFF-style summary for headers and logs."""
        return (
            f"{self.observer.call_sign} → {self.group_name} | "
            f"{self.shell}/{self.fuze.value.upper()} | "
            f"{self.method_of_fire.value} {self.rounds_per_piece}rd/pc | "
            f"sheaf {self.sheaf.value} | "
            f"{self.target_type.value} '{self.target_description or '?'}'"
        )
