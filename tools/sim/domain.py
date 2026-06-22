"""CoT domain model — single source of truth for the CotEntry value object."""

from __future__ import annotations

import dataclasses

# Seconds before a CoT event becomes stale, keyed by affiliation character.
STALE: dict[str, int] = {"f": 90, "h": 300, "n": 600, "u": 120}


@dataclasses.dataclass(frozen=True)
class CotEntry:
    """Immutable CoT message template stored in the library.

    ``category`` and ``label`` are UI metadata only; ``CotXmlBuilder`` ignores
    them.  Use ``dataclasses.replace(entry, lat=…)`` to derive edited copies.
    """

    uid: str
    cot_type: str
    label: str
    category: str
    callsign: str = ""
    lat: float = 0.0
    lon: float = 0.0
    hae: float = 0.0
    speed: float = 0.0
    course: float = 0.0
    team: str = ""
    role: str = ""

    @property
    def affiliation(self) -> str:
        """Single-character affiliation from the CoT type string (f/h/n/u)."""
        parts = self.cot_type.split("-")
        return parts[1] if len(parts) > 1 else "u"
