"""Peloton (FDC-niveau) en Waakgroepen (tactische subgroepen).

Structuur:
  Peloton
    ├── pieces[]            (1-4 mortieren met GPS)
    ├── groups[]            (1-4 waakgroepen)
    │     ├── name
    │     ├── pdf_mils      (eigen waakrichting)
    │     ├── member_names  (subset van piece-namen, exclusief)
    │     └── (actieve FireMission wordt elders bijgehouden)
    └── aiming_points[]     (gedeelde merkpunten)

Invariant: elke piece-naam zit in hoogstens één group.member_names.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..geo import Position
from .piece import Piece


@dataclass(frozen=True)
class AimingPoint:
    name: str
    position: Position


@dataclass(frozen=True)
class Observer:
    """Forward Observer / OP: tactische roepnaam + stelling.

    Persistent op pelotonsniveau zodat dezelfde FO's hergebruikt kunnen worden
    over meerdere vuuropdrachten (selecteerbaar in de Call-For-Fire dialoog).
    """
    call_sign: str
    position: Position


@dataclass
class Group:
    """Waakgroep: subset van stukken met eigen PDF en vuursector.

    `member_names` verwijst naar Piece.name in het bovenliggende Peloton.
    `left_limit_mils`/`right_limit_mils` begrenzen de vuursector (laterale
    grenzen). De sector loopt met de klok mee van links naar rechts; gelijke
    grenzen (default 0/0) betekenen 'onbegrensd' (volledige cirkel).
    """
    name: str
    pdf_mils: float = 0.0
    member_names: list[str] = field(default_factory=list)
    left_limit_mils: float = 0.0
    right_limit_mils: float = 0.0
    # Optional max range cap in metres. 0.0 = no override → use firing-table max.
    # When set, range envelopes on the diagram and map are clipped to this value.
    max_range_m: float = 0.0

    def set_pdf(self, pdf_mils: float) -> None:
        self.pdf_mils = pdf_mils % 6400.0

    def set_limits(self, left_mils: float, right_mils: float) -> None:
        self.left_limit_mils = left_mils % 6400.0
        self.right_limit_mils = right_mils % 6400.0

    def effective_max_m(self, firetable_max_m: float) -> float:
        """Resolve the max range used for diagrams/map (group cap wins if set)."""
        if self.max_range_m > 0.0:
            return min(self.max_range_m, firetable_max_m)
        return firetable_max_m

    def sector_width_mils(self) -> float:
        """Breedte van de vuursector (klok-mee, links→rechts), in mils.

        Gelijke grenzen → 6400 (onbegrensd / volledige cirkel).
        """
        width = (self.right_limit_mils - self.left_limit_mils) % 6400.0
        return 6400.0 if width == 0.0 else width

    def has_limits(self) -> bool:
        """True als er een echte (begrensde) vuursector is ingesteld."""
        return self.left_limit_mils != self.right_limit_mils


DEFAULT_LOW_AMMO_THRESHOLD = 5


@dataclass
class Peloton:
    """FDC/Peloton-niveau: stukken + groepen + merkpunten + munitievoorraad + fire plan."""
    pieces: list[Piece] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    aiming_points: list[AimingPoint] = field(default_factory=list)
    observers: list[Observer] = field(default_factory=list)
    # munitie: { piece_name: { shell_type: aantal } }
    ammo: dict[str, dict[str, int]] = field(default_factory=dict)
    low_ammo_threshold: int = DEFAULT_LOW_AMMO_THRESHOLD
    # fire plan: lijst van voorbereide doelen (PlannedTarget — gedefinieerd in fireplan.py)
    fire_plan: list = field(default_factory=list)
    # H-hour: referentie-tijd voor alle timings in het fire plan (None = onbepaald)
    h_hour: datetime | None = None
    # Auto-incrementing counter for fire mission IDs (FM001, FM002, ...)
    next_fm_number: int = 1

    def allocate_fm_id(self) -> str:
        """Allocate the next sequential fire mission ID. Increments the counter."""
        fm_id = f"FM{self.next_fm_number:03d}"
        self.next_fm_number += 1
        return fm_id

    # ---------- stukken ----------
    def base(self) -> Piece:
        """Eerste basisstuk van het peloton (zie ook `base_of` per sectie)."""
        for p in self.pieces:
            if p.is_base:
                return p
        raise ValueError("Geen basisstuk gedefinieerd.")

    def base_of(self, group: Group) -> Piece | None:
        """Het basisstuk binnen één sectie, of None als die er nog geen heeft.

        Elke sectie heeft een eigen basisstuk; over het peloton zijn dus
        meerdere basisstukken toegestaan (hoogstens één per sectie).
        """
        for p in self.pieces:
            if p.is_base and p.name in group.member_names:
                return p
        return None

    def piece(self, name: str) -> Piece:
        for p in self.pieces:
            if p.name == name:
                return p
        raise KeyError(name)

    def add_piece(self, piece: Piece) -> None:
        if any(p.name == piece.name for p in self.pieces):
            raise ValueError(f"Stuk '{piece.name}' bestaat al.")
        # Een nieuw stuk zit nog in geen enkele sectie; basisstuk-exclusiviteit
        # geldt per sectie en wordt afgedwongen bij toewijzing aan een sectie.
        self.pieces.append(piece)

    def remove_piece(self, name: str) -> None:
        self.pieces = [p for p in self.pieces if p.name != name]
        for g in self.groups:
            if name in g.member_names:
                g.member_names.remove(name)

    def update_piece(self, original_name: str, new_piece: Piece) -> None:
        """Vervang een bestaand stuk in-place (Piece is frozen).

        Behoudt groepslidmaatschap en munitievoorraad; migreert beide mee
        wanneer het stuk hernoemd wordt. Bewaakt de basisstuk-exclusiviteit
        binnen de sectie waar het stuk toe behoort.
        """
        idx = next((i for i, p in enumerate(self.pieces) if p.name == original_name), None)
        if idx is None:
            raise KeyError(original_name)
        renamed = new_piece.name != original_name
        if renamed and any(p.name == new_piece.name for p in self.pieces):
            raise ValueError(f"Stuk '{new_piece.name}' bestaat al.")
        self.pieces[idx] = new_piece
        if renamed:
            for g in self.groups:
                g.member_names = [
                    new_piece.name if n == original_name else n for n in g.member_names
                ]
            if original_name in self.ammo:
                self.ammo[new_piece.name] = self.ammo.pop(original_name)
        if new_piece.is_base:
            group = self.group_of(new_piece.name)
            if group is not None:
                self._demote_bases_in_group(group, keep=new_piece.name)

    def _demote_bases_in_group(self, group: Group, keep: str) -> None:
        """Zorg dat alleen `keep` basisstuk is binnen deze sectie."""
        for i, p in enumerate(self.pieces):
            if p.name != keep and p.is_base and p.name in group.member_names:
                self.pieces[i] = Piece(name=p.name, position=p.position, is_base=False)

    # ---------- groepen ----------
    def group(self, name: str) -> Group:
        for g in self.groups:
            if g.name == name:
                return g
        raise KeyError(name)

    def add_group(self, group: Group) -> None:
        if any(g.name == group.name for g in self.groups):
            raise ValueError(f"Groep '{group.name}' bestaat al.")
        for pname in group.member_names:
            self._detach_piece(pname)
        self.groups.append(group)

    def remove_group(self, name: str) -> None:
        self.groups = [g for g in self.groups if g.name != name]

    def assign_piece_to_group(self, piece_name: str, group_name: str) -> None:
        """Verplaats een stuk naar een groep (verwijdert eerst uit huidige groep)."""
        if not any(p.name == piece_name for p in self.pieces):
            raise KeyError(f"Stuk '{piece_name}' bestaat niet.")
        self._detach_piece(piece_name)
        group = self.group(group_name)
        group.member_names.append(piece_name)
        if self.piece(piece_name).is_base:
            self._demote_bases_in_group(group, keep=piece_name)

    def unassigned_pieces(self) -> list[Piece]:
        assigned: set[str] = {n for g in self.groups for n in g.member_names}
        return [p for p in self.pieces if p.name not in assigned]

    def group_of(self, piece_name: str) -> Group | None:
        for g in self.groups:
            if piece_name in g.member_names:
                return g
        return None

    def pieces_in(self, group: Group) -> list[Piece]:
        return [self.piece(n) for n in group.member_names]

    def _detach_piece(self, piece_name: str) -> None:
        for g in self.groups:
            if piece_name in g.member_names:
                g.member_names.remove(piece_name)

    # ---------- merkpunten ----------
    def add_aiming_point(self, ap: AimingPoint) -> None:
        if any(a.name == ap.name for a in self.aiming_points):
            raise ValueError(f"Merkpunt '{ap.name}' bestaat al.")
        self.aiming_points.append(ap)

    def aiming_point(self, name: str) -> AimingPoint:
        for ap in self.aiming_points:
            if ap.name == name:
                return ap
        raise KeyError(name)

    # ---------- waarnemers (FO) ----------
    def add_observer(self, obs: Observer) -> None:
        if any(o.call_sign == obs.call_sign for o in self.observers):
            raise ValueError(f"FO '{obs.call_sign}' bestaat al.")
        self.observers.append(obs)

    def observer(self, call_sign: str) -> Observer:
        for o in self.observers:
            if o.call_sign == call_sign:
                return o
        raise KeyError(call_sign)

    def remove_observer(self, call_sign: str) -> None:
        self.observers = [o for o in self.observers if o.call_sign != call_sign]

    def update_observer(self, original_call_sign: str, new_obs: Observer) -> None:
        idx = next((i for i, o in enumerate(self.observers)
                    if o.call_sign == original_call_sign), None)
        if idx is None:
            raise KeyError(original_call_sign)
        if new_obs.call_sign != original_call_sign and any(
            o.call_sign == new_obs.call_sign for o in self.observers
        ):
            raise ValueError(f"FO '{new_obs.call_sign}' bestaat al.")
        self.observers[idx] = new_obs

    # ---------- munitie ----------
    def set_ammo(self, piece_name: str, shell: str, count: int) -> None:
        if not any(p.name == piece_name for p in self.pieces):
            raise KeyError(f"Stuk '{piece_name}' bestaat niet.")
        self.ammo.setdefault(piece_name, {})[shell.upper()] = max(0, int(count))

    def ammo_of(self, piece_name: str, shell: str) -> int:
        return self.ammo.get(piece_name, {}).get(shell.upper(), 0)

    def consume_ammo(self, piece_name: str, shell: str, rounds: int) -> int:
        """Verminder voorraad met `rounds`; return werkelijk verbruikte aantal."""
        have = self.ammo_of(piece_name, shell)
        used = min(have, max(0, int(rounds)))
        self.ammo.setdefault(piece_name, {})[shell.upper()] = have - used
        return used

    def low_ammo_pieces(self, shell: str = "HE") -> list[str]:
        """Stukken waarvan de voorraad van `shell` onder de drempel zit."""
        return [
            p.name for p in self.pieces
            if self.ammo_of(p.name, shell) <= self.low_ammo_threshold
        ]
