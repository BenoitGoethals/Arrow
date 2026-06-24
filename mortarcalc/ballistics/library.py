"""FireTableLibrary — meerdere vuurtafels, gekoppeld aan munitietype (shell).

Het peloton vuurt verschillende munities (HE, ILLUM, SMOKE, WP, …) en elke
munitie heeft een eigen vuurtafel. Deze bibliotheek koppelt een shell-naam aan
een FireTable en kiest bij het berekenen van een vuuropdracht de juiste tafel
op basis van `FireMission.shell`. Eén tafel is de default-fallback voor
munities zonder eigen tafel.

Sleutels worden genormaliseerd (upper-case, gestript) zodat 'he', 'HE' en
' He ' dezelfde tafel aanwijzen — net als `Peloton.set_ammo`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .firetable import FireTable


class FireTableError(ValueError):
    """Geen geschikte vuurtafel beschikbaar voor een gevraagde munitie."""


def _norm(shell: str) -> str:
    return shell.strip().upper()


@dataclass
class FireTableLibrary:
    """Koppeling shell → FireTable, met één default-tafel als fallback."""

    tables: dict[str, FireTable] = field(default_factory=dict)
    default_shell: str | None = None

    # ---------- mutaties ----------
    def add(self, shell: str, table: FireTable) -> None:
        """Koppel `table` aan munitie `shell` (overschrijft een bestaande koppeling)."""
        key = _norm(shell)
        if not key:
            raise FireTableError("Munitienaam mag niet leeg zijn.")
        self.tables[key] = table
        if self.default_shell is None:
            self.default_shell = key

    def remove(self, shell: str) -> None:
        key = _norm(shell)
        self.tables.pop(key, None)
        if self.default_shell == key:
            self.default_shell = next(iter(self.tables), None)

    def set_default(self, shell: str) -> None:
        key = _norm(shell)
        if key not in self.tables:
            raise FireTableError(f"Geen vuurtafel gekoppeld aan '{shell}'.")
        self.default_shell = key

    # ---------- lookup ----------
    def get(self, shell: str) -> FireTable | None:
        return self.tables.get(_norm(shell))

    def resolve(self, shell: str) -> FireTable:
        """De tafel voor `shell`; valt terug op de default-tafel.

        Raises FireTableError als de bibliotheek leeg is.
        """
        table = self.get(shell)
        if table is not None:
            return table
        if self.default_shell is not None:
            default = self.tables.get(self.default_shell)
            if default is not None:
                return default
        if self.tables:
            return next(iter(self.tables.values()))
        raise FireTableError("Geen vuurtafels geladen.")

    def shells(self) -> list[str]:
        """Gekoppelde munitienamen, alfabetisch."""
        return sorted(self.tables)

    def is_default(self, shell: str) -> bool:
        return self.default_shell == _norm(shell)

    def __len__(self) -> int:
        return len(self.tables)

    def __bool__(self) -> bool:
        return bool(self.tables)
