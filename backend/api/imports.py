"""Bulk import endpoints for hierarchy and operators."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.infrastructure.password_hasher import hash_password
from backend.auth.jwt_auth import require_role
from backend.storage.database import get_db
from backend.storage.models import Company, Operator, Platoon, Section, Team

router = APIRouter(prefix="/import", tags=["import"])


class HierarchyRow(BaseModel):
    company: str
    platoon: str
    section: str
    team: str


class HierarchyImportBody(BaseModel):
    rows: list[HierarchyRow]


class HierarchyImportResult(BaseModel):
    created: int
    total_rows: int


class OperatorRow(BaseModel):
    callsign: str
    password: str = "changeme"
    rank: str = "OR-1"
    role: str = "OPERATOR"
    team: str | None = None


class OperatorImportBody(BaseModel):
    rows: list[OperatorRow]


class OperatorImportResult(BaseModel):
    created: int
    updated: int
    total_rows: int


@router.post("/hierarchy", response_model=HierarchyImportResult)
def import_hierarchy(
    body: HierarchyImportBody,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("ADMIN")),
) -> HierarchyImportResult:
    """Idempotently create the Company → Platoon → Section → Team tree from a row list."""
    created = 0

    def gc(model: type, **kw: object) -> object:
        nonlocal created
        obj = db.query(model).filter_by(**kw).first()
        if obj:
            return obj
        obj = model(**kw)
        db.add(obj)
        db.flush()
        created += 1
        return obj

    for row in body.rows:
        co  = gc(Company, name=row.company)
        plt = gc(Platoon, name=row.platoon, company_id=co.id)
        sec = gc(Section, name=row.section, platoon_id=plt.id)
        gc(Team, name=row.team, section_id=sec.id)

    db.commit()
    return HierarchyImportResult(created=created, total_rows=len(body.rows))


@router.post("/operators", response_model=OperatorImportResult)
def import_operators(
    body: OperatorImportBody,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("ADMIN")),
) -> OperatorImportResult:
    """Create or update operators from a row list. Team is matched by name."""
    team_map: dict[str, int] = {t.name: t.id for t in db.query(Team).all()}
    created = updated = 0

    for row in body.rows:
        team_id = team_map.get(row.team) if row.team else None
        existing = db.query(Operator).filter_by(callsign=row.callsign).first()
        if existing:
            existing.rank = row.rank
            existing.role = row.role
            if team_id is not None:
                existing.team_id = team_id
            updated += 1
        else:
            op = Operator(
                callsign=row.callsign,
                password_hash=hash_password(row.password),
                rank=row.rank,
                role=row.role,
                team_id=team_id,
                last_seen=datetime.now(timezone.utc),
            )
            db.add(op)
            created += 1

    db.commit()
    return OperatorImportResult(created=created, updated=updated, total_rows=len(body.rows))
