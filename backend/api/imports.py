"""Bulk import endpoints for hierarchy and operators."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
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
    team_role: str | None = None


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

    def gc(model: type, **kw: object) -> Any:
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
        co = gc(Company, name=row.company)
        plt = gc(Platoon, name=row.platoon, company_id=co.id)
        sec = gc(Section, name=row.section, platoon_id=plt.id)
        gc(Team, name=row.team, section_id=sec.id)

    db.commit()
    return HierarchyImportResult(created=created, total_rows=len(body.rows))


# ── Nested JSON import ────────────────────────────────────────────────────────


class HierarchyJsonOperator(BaseModel):
    callsign: str
    rank: str = "OR-1"
    role: str = "OPERATOR"
    team_role: str | None = None
    password: str = "changeme"


class HierarchyJsonTeam(BaseModel):
    name: str
    operators: list[HierarchyJsonOperator] = []


class HierarchyJsonSection(BaseModel):
    name: str
    teams: list[HierarchyJsonTeam] = []


class HierarchyJsonPlatoon(BaseModel):
    name: str
    sections: list[HierarchyJsonSection] = []


class HierarchyJsonCompany(BaseModel):
    name: str
    platoons: list[HierarchyJsonPlatoon] = []


class HierarchyJsonBody(BaseModel):
    version: str = "1"
    companies: list[HierarchyJsonCompany]


class HierarchyJsonResult(BaseModel):
    companies_created: int
    platoons_created: int
    sections_created: int
    teams_created: int
    operators_created: int
    operators_updated: int


@router.post("/hierarchy-json", response_model=HierarchyJsonResult)
def import_hierarchy_json(
    body: HierarchyJsonBody,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("ADMIN")),
) -> HierarchyJsonResult:
    """Import a full nested hierarchy snapshot (companies → operators). Idempotent."""
    counts: dict[str, int] = {
        "companies_created": 0,
        "platoons_created": 0,
        "sections_created": 0,
        "teams_created": 0,
        "operators_created": 0,
        "operators_updated": 0,
    }

    def gc(model: type, key: str, **kw: object) -> Any:
        obj = db.query(model).filter_by(**kw).first()
        if obj:
            return obj
        obj = model(**kw)
        db.add(obj)
        db.flush()
        counts[key] += 1
        return obj

    for co_data in body.companies:
        co = gc(Company, "companies_created", name=co_data.name)
        for plt_data in co_data.platoons:
            plt = gc(Platoon, "platoons_created", name=plt_data.name, company_id=co.id)
            for sec_data in plt_data.sections:
                sec = gc(
                    Section, "sections_created", name=sec_data.name, platoon_id=plt.id
                )
                for team_data in sec_data.teams:
                    team = gc(
                        Team, "teams_created", name=team_data.name, section_id=sec.id
                    )
                    for op_data in team_data.operators:
                        existing = (
                            db.query(Operator)
                            .filter_by(callsign=op_data.callsign)
                            .first()
                        )
                        if existing:
                            existing.rank = op_data.rank
                            existing.role = op_data.role
                            existing.team_id = team.id
                            existing.team_role = op_data.team_role
                            counts["operators_updated"] += 1
                        else:
                            db.add(
                                Operator(
                                    callsign=op_data.callsign,
                                    password_hash=hash_password(op_data.password),
                                    rank=op_data.rank,
                                    role=op_data.role,
                                    team_id=team.id,
                                    team_role=op_data.team_role,
                                    last_seen=datetime.now(timezone.utc),
                                )
                            )
                            counts["operators_created"] += 1

    db.commit()
    return HierarchyJsonResult(**counts)


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
            if row.team_role is not None:
                existing.team_role = row.team_role
            updated += 1
        else:
            op = Operator(
                callsign=row.callsign,
                password_hash=hash_password(row.password),
                rank=row.rank,
                role=row.role,
                team_id=team_id,
                team_role=row.team_role,
                last_seen=datetime.now(timezone.utc),
            )
            db.add(op)
            created += 1

    db.commit()
    return OperatorImportResult(
        created=created, updated=updated, total_rows=len(body.rows)
    )
