"""Security classification levels and clearance enforcement.

Arrow uses a 5-level ordered scheme stored as a small integer so comparisons are
cheap in SQL (``WHERE classification <= :clearance``) and on the WebSocket fan-out:

    0 UNCLASSIFIED · 1 RESTRICTED · 2 CONFIDENTIAL · 3 SECRET · 4 TOP SECRET

Rules enforced across the backend:

* **See** an element:  ``element.classification <= operator.clearance``.
* **See/select** a mission:  ``mission.classification <= operator.clearance``.
* **Create/patch** an element: the level defaults to the mission's ceiling and is
  hard-capped at ``min(mission.classification, operator.clearance)`` — a request
  above that is refused (403).

Everything defaults to ``0`` (UNCLASSIFIED), so raising the columns changes no
behaviour until levels are actually assigned.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

UNCLASSIFIED = 0
RESTRICTED = 1
CONFIDENTIAL = 2
SECRET = 3
TOP_SECRET = 4

MIN_LEVEL = 0
MAX_LEVEL = 4

#: JDSS (STANAG-4677) has no TOP SECRET — its wire classification is 0..3.
JDSS_MAX = SECRET

_NAMES: dict[int, str] = {
    0: "UNCLASSIFIED",
    1: "RESTRICTED",
    2: "CONFIDENTIAL",
    3: "SECRET",
    4: "TOP SECRET",
}
_LEVELS: dict[str, int] = {v: k for k, v in _NAMES.items()}


def clamp(level: int | None) -> int:
    """Bound an incoming level into ``[0, 4]``; ``None`` → 0 (UNCLASSIFIED)."""
    if level is None:
        return UNCLASSIFIED
    try:
        lvl = int(level)
    except (TypeError, ValueError):
        return UNCLASSIFIED
    return max(MIN_LEVEL, min(MAX_LEVEL, lvl))


def name_for(level: int | None) -> str:
    """Human-readable marking for a level (clamped)."""
    return _NAMES[clamp(level)]


def level_for(name: str | None) -> int:
    """Level for a marking name (case-insensitive); unknown → 0."""
    return _LEVELS.get((name or "").strip().upper(), UNCLASSIFIED)


def can_see(element_classification: int | None, clearance: int | None) -> bool:
    """True if an operator at ``clearance`` may see ``element_classification``."""
    return clamp(element_classification) <= clamp(clearance)


def resolve_default_and_cap(mission: Any, operator: Any, requested: int | None) -> int:
    """Resolve the classification for a new/edited element.

    * ``requested is None`` → the effective cap (mission ceiling, further bounded
      by the operator's clearance) — i.e. new elements default to the mission level.
    * ``requested`` out of ``[0, 4]`` → 422.
    * ``requested`` above the cap → 403 (mission ceiling or clearance exceeded).
    """
    ceiling = (
        clamp(getattr(mission, "classification", 0))
        if mission is not None
        else UNCLASSIFIED
    )
    cap = min(ceiling, clamp(getattr(operator, "clearance", 0)))
    if requested is None:
        return cap
    try:
        want = int(requested)
    except (TypeError, ValueError):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "classification must be an integer 0..4",
        )
    if want < MIN_LEVEL or want > MAX_LEVEL:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "classification out of range 0..4"
        )
    if want > cap:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "classification exceeds the mission ceiling or your clearance",
        )
    return want


def require_mission_clearance(mission: Any, operator: Any) -> None:
    """Raise 403 if the operator's clearance is below the mission's classification."""
    if mission is not None and clamp(getattr(mission, "classification", 0)) > clamp(
        getattr(operator, "clearance", 0)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Insufficient clearance for this mission"
        )


def jdss_inbound(level: int | None) -> int:
    """Map a JDSS wire classification (0..3) onto our scale."""
    return clamp(level)


def jdss_outbound(level: int | None) -> int:
    """Cap an Arrow classification for the JDSS wire (no TOP SECRET)."""
    return min(clamp(level), JDSS_MAX)
