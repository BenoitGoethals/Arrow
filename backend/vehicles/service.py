"""Helpers for deriving a vehicle's live map position.

A Vehicle has no GPS of its own — its position follows the assigned operator
(``operator_id``) or, when assigned to a whole team (``team_id``), that team's
anchor operator (the first online operator with a fix, else the first operator
with a fix). Returns ``(lat, lon, online)``; lat/lon are ``None`` when no
position can be derived (unassigned, or no assigned operator has a fix).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.storage.models import Operator, Vehicle

ONLINE_WINDOW_SECONDS = 90


def _is_online(op: Operator, now: datetime) -> bool:
    if op.status != "ONLINE":
        return False
    last = op.last_seen
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last) <= timedelta(seconds=ONLINE_WINDOW_SECONDS)


def _anchor_operator(db: Session, vehicle: Vehicle) -> Operator | None:
    if vehicle.operator_id is not None:
        return db.get(Operator, vehicle.operator_id)
    if vehicle.team_id is not None:
        members = (
            db.query(Operator)
            .filter(Operator.team_id == vehicle.team_id)
            .filter(Operator.latitude.isnot(None))
            .all()
        )
        if not members:
            return None
        now = datetime.now(timezone.utc)
        # Prefer an online member; otherwise any member with a fix.
        return next((m for m in members if _is_online(m, now)), members[0])
    return None


def derived_position(
    db: Session, vehicle: Vehicle
) -> tuple[float | None, float | None, bool]:
    op = _anchor_operator(db, vehicle)
    if op is None or op.latitude is None or op.longitude is None:
        return None, None, False
    return op.latitude, op.longitude, _is_online(op, datetime.now(timezone.utc))
