"""Admin-only endpoints: system config, stats, and audit helpers."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.auth.jwt_auth import require_role
from backend.config.xml_config import load_config
from backend.storage.database import get_db
from backend.storage.models import Alert, Message, Operator, Report, TacticalObject

router = APIRouter(prefix="/admin", tags=["admin"])

ONLINE_WINDOW = timedelta(seconds=90)


@router.get("/config")
def get_config(
    request: Request,
    _: Operator = Depends(require_role("ADMIN")),
) -> dict:
    """Return the current server configuration as JSON.

    The JWT secret is masked; all other values are shown as-is.
    """
    cfg = request.app.state.config
    d = dataclasses.asdict(cfg)
    # Mask the JWT secret
    d["auth"]["secret"] = "***" if d["auth"]["secret"] != "change-me-in-production" else "⚠ DEFAULT — change me!"
    return d


@router.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN")),
) -> dict:
    """Return a live system snapshot for the admin dashboard."""
    now = datetime.now(timezone.utc)

    total_ops      = db.query(Operator).count()
    unassigned_ops = db.query(Operator).filter(Operator.team_id.is_(None)).count()
    online_ops = sum(
        1 for op in db.query(Operator).filter(Operator.status == "ONLINE").all()
        if (now - (op.last_seen if op.last_seen.tzinfo else op.last_seen.replace(tzinfo=timezone.utc))) <= ONLINE_WINDOW
    )
    active_alerts  = db.query(Alert).filter(Alert.status == "ACTIVE").count()
    total_reports  = db.query(Report).count()
    total_objects  = db.query(TacticalObject).count()
    total_messages = db.query(Message).count()

    roles = {}
    for (r, cnt) in db.query(Operator.role, db.query(Operator).count()).all():
        pass  # simplified below
    role_rows = db.execute(
        __import__("sqlalchemy").text(
            "SELECT role, COUNT(*) FROM operators GROUP BY role"
        )
    ).fetchall()

    return {
        "operators": {
            "total":      total_ops,
            "online":     online_ops,
            "unassigned": unassigned_ops,
            "by_role":    {row[0]: row[1] for row in role_rows},
        },
        "alerts":        {"active": active_alerts},
        "reports":       {"total": total_reports},
        "tactical_objects": {"total": total_objects},
        "messages":      {"total": total_messages},
    }
