"""Tactical reports: contact, spot, 9-liners (CASEVAC, MEDEVAC, CAS) and NATO CBRN 1..6."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session

from backend.api.schemas import ReportIn, ReportOut, ReportUpdate
from backend.audit import log_event
from backend.auth.jwt_auth import get_current_operator, require_role
from backend.reports.cbrn import CbrnParseError, parse_cbrn
from backend.storage.database import get_db
from backend.storage.models import Operator, Report
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/reports", tags=["reports"])

CBRN_TYPES    = {f"CBRN_{i}" for i in range(1, 7)}
VALID_TYPES   = {"CONTACT", "SPOT", "CASEVAC", "MEDEVAC", "CAS"} | CBRN_TYPES
VALID_STATUSES = {"RECEIVED", "ACKNOWLEDGED", "PROCESSED", "REJECTED"}


@router.get("", response_model=list[ReportOut])
def list_reports(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> list[Report]:
    return db.query(Report).order_by(Report.timestamp.desc()).limit(200).all()


@router.post("", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def submit_report(
    payload: ReportIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> Report:
    rtype = payload.type.upper()
    if rtype not in VALID_TYPES:
        rtype = "CONTACT"
    rep = Report(type=rtype, operator_id=current.id,
                 payload=json.dumps(payload.payload), status="RECEIVED")
    db.add(rep)
    db.commit()
    db.refresh(rep)

    await broadcaster.broadcast({
        "channel": "report",
        "event":   "submitted",
        "data": {
            "id":          rep.id,
            "type":        rep.type,
            "status":      rep.status,
            "operator_id": rep.operator_id,
            "payload":     payload.payload,
        },
    })
    return rep


@router.post("/cbrn/import", response_model=list[ReportOut], status_code=status.HTTP_201_CREATED)
async def import_cbrn(
    files: list[UploadFile] = File(..., description="One or more NATO CBRN 1..6 text files"),
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> list[Report]:
    """Parse uploaded NATO CBRN message files and store each as a Report.

    Each file is parsed with :func:`backend.reports.cbrn.parse_cbrn`. The
    resulting structured payload is stored as the report payload and a
    realtime event is broadcast on the ``report`` channel so map clients
    can render it (marker + hazard zones).
    """
    created: list[Report] = []
    errors:  list[str]    = []

    for up in files:
        raw = (await up.read()).decode("utf-8", errors="replace")
        try:
            parsed = parse_cbrn(raw)
        except CbrnParseError as exc:
            errors.append(f"{up.filename}: {exc}")
            continue

        rtype = parsed.get("msg_type", "CBRN_1")
        if rtype not in CBRN_TYPES:
            rtype = "CBRN_1"

        # Tag the source filename so operators can trace the import.
        parsed["source_file"] = up.filename or "uploaded.cbrn"

        rep = Report(
            type=rtype, operator_id=current.id,
            payload=json.dumps(parsed), status="RECEIVED",
        )
        db.add(rep)
        db.commit()
        db.refresh(rep)

        await broadcaster.broadcast({
            "channel": "report",
            "event":   "submitted",
            "data": {
                "id":          rep.id,
                "type":        rep.type,
                "status":      rep.status,
                "operator_id": rep.operator_id,
                "payload":     parsed,
            },
        })
        created.append(rep)

    if not created and errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "; ".join(errors))
    return created


@router.patch("/{report_id}", response_model=ReportOut)
async def update_report_status(
    report_id: int,
    payload:   ReportUpdate,
    db:        Session  = Depends(get_db),
    current:   Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> Report:
    """Update the status of a report and notify the originating operator via WebSocket."""
    rep = db.get(Report, report_id)
    if not rep:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    new_status = payload.status.upper()
    if new_status not in VALID_STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Status must be one of: {', '.join(sorted(VALID_STATUSES))}")

    rep.status        = new_status
    rep.reviewer_note = payload.reviewer_note.strip()
    db.commit()
    db.refresh(rep)

    log_event(db, "REPORT_STATUS_UPDATE", operator_id=current.id,
              resource=f"report:{report_id}",
              detail=f"status:{new_status} note:{rep.reviewer_note[:60]}")

    # Broadcast to ALL connected clients — the sender's Android app will pick this up
    # and notify the operator that their report has been reviewed.
    await broadcaster.broadcast({
        "channel": "report",
        "event":   "status_updated",
        "data": {
            "id":            rep.id,
            "type":          rep.type,
            "status":        rep.status,
            "reviewer_note": rep.reviewer_note,
            "operator_id":   rep.operator_id,   # original sender
            "reviewed_by":   current.callsign,
        },
    })
    return rep
