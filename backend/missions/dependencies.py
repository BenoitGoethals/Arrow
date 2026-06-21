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

from backend.storage.database import get_db
from backend.storage.models import Mission


def get_active_mission(
    x_mission_id: int | None = Header(None, alias="X-Mission-ID"),
    db: Session = Depends(get_db),
) -> Mission | None:
    if x_mission_id is None:
        return None
    return db.get(Mission, x_mission_id)
