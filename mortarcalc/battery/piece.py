"""Eén mortier (stuk)."""
from __future__ import annotations

from dataclasses import dataclass

from ..geo import Position


@dataclass(frozen=True)
class Piece:
    """Een enkel mortierstuk.

    `name` is het tactisch nummer (bv. 'A', 'B', '1', '2', ...).
    `position` is de stelling (MGRS via Position-helpers).
    `is_base` is True voor het basisstuk dat als referentie dient.
    """
    name: str
    position: Position
    is_base: bool = False
