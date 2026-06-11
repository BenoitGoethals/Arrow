"""Hierarchy export endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.auth.jwt_auth import get_current_operator
from backend.storage.database import get_db
from backend.storage.models import Company

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/hierarchy")
def export_hierarchy(
    db: Session = Depends(get_db),
    _: object = Depends(get_current_operator),
) -> JSONResponse:
    """Export the full hierarchy as a nested JSON snapshot (no passwords)."""
    companies = db.query(Company).all()

    result: dict = {"version": "1", "companies": []}
    for co in companies:
        co_data: dict = {"name": co.name, "platoons": []}
        for plt in co.platoons:
            plt_data: dict = {"name": plt.name, "sections": []}
            for sec in plt.sections:
                sec_data: dict = {"name": sec.name, "teams": []}
                for team in sec.teams:
                    team_data: dict = {"name": team.name, "operators": []}
                    for op in team.operators:
                        team_data["operators"].append({
                            "callsign": op.callsign,
                            "rank": op.rank,
                            "role": op.role,
                            "team_role": op.team_role,
                            "password": "changeme",
                        })
                    sec_data["teams"].append(team_data)
                plt_data["sections"].append(sec_data)
            co_data["platoons"].append(plt_data)
        result["companies"].append(co_data)

    return JSONResponse(
        content=result,
        headers={"Content-Disposition": "attachment; filename=hierarchy_export.json"},
    )
