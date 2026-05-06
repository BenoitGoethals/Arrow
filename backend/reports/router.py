"""Tactical reports: contact, spot, 9-liners (CASEVAC, MEDEVAC, CAS)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.api.schemas import ReportIn, ReportOut
from backend.auth.jwt_auth import get_current_operator
from backend.storage.database import get_db
from backend.storage.models import Operator, Report
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/reports", tags=["reports"])

VALID_TYPES = {"CONTACT", "SPOT", "CASEVAC", "MEDEVAC", "CAS"}


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
    rep = Report(type=rtype, operator_id=current.id, payload=json.dumps(payload.payload))
    db.add(rep)
    db.commit()
    db.refresh(rep)

    await broadcaster.broadcast(
        {
            "channel": "report",
            "event": "submitted",
            "data": {
                "id": rep.id,
                "type": rep.type,
                "operator_id": rep.operator_id,
                "payload": payload.payload,
            },
        }
    )
    return rep
