"""FastAPI dependency that resolves the active mission from a request header.

Every mission-scoped endpoint depends on ``get_active_mission``.  The client
(web browser or Android app) sends the chosen mission id as::

    X-Mission-ID: 3

A missing header returns None — endpoints treat that as "no filter"
(useful for ADMIN/BC who manage the full system).
An invalid id returns 404 immediately.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from backend.storage.database import get_db
from backend.storage.models import Mission


def get_active_mission(
    x_mission_id: int | None = Header(None, alias="X-Mission-ID"),
    db: Session = Depends(get_db),
) -> Mission | None:
    if x_mission_id is None:
        return None
    mission = db.get(Mission, x_mission_id)
    if not mission:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"Mission {x_mission_id} not found")
    return mission
