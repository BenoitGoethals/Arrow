"""FastAPI dependency that resolves the active mission from a request header.

Every mission-scoped endpoint depends on ``get_active_mission``.  The client
(web browser or Android app) sends the chosen mission id as::

    X-Mission-ID: 3

A missing header — or one referencing a mission that no longer exists —
returns ``None``; endpoints treat that as "no filter" (useful for ADMIN/BC
who manage the full system, and resilient to a client holding a deleted
mission id in localStorage).
"""

from __future__ import annotations

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_current_operator
from backend.classification import require_mission_clearance
from backend.storage.database import get_db
from backend.storage.models import Mission, Operator


def get_active_mission(
    x_mission_id: int | None = Header(None, alias="X-Mission-ID"),
    current: Operator = Depends(get_current_operator),
    db: Session = Depends(get_db),
) -> Mission | None:
    """Resolve the active mission, enforcing the mission lock + clearance gate.

    * **ADMIN** honors the ``X-Mission-ID`` header — the only role that may switch
      missions — but only for a mission they are cleared for (403 otherwise).
    * **Everyone else** is LOCKED to their assigned ``Operator.mission_id``; the
      header is ignored (no switching). Unassigned → ``None`` (global/read view;
      mission-scoped writes simply have no mission), so nothing hard-breaks.
    """
    if current.role == "ADMIN":
        if x_mission_id is None:
            return None
        mission = db.get(Mission, x_mission_id)
        if mission is None:
            return None
        require_mission_clearance(mission, current)
        return mission

    if current.mission_id is None:
        return None
    mission = db.get(Mission, current.mission_id)
    if mission is not None:
        require_mission_clearance(mission, current)
    return mission
