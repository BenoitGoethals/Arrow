from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, selectinload

from backend.auth.jwt_auth import get_current_operator
from backend.missions.dependencies import get_active_mission
from backend.storage.database import get_db
from backend.storage.models import Company, Mission, Operator

router = APIRouter(prefix="/hierarchy", tags=["hierarchy"])

ONLINE_WINDOW_SECONDS = 90


def _is_online(op: Operator, now: datetime) -> bool:
    if op.status != "ONLINE":
        return False
    last = op.last_seen
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last) <= timedelta(seconds=ONLINE_WINDOW_SECONDS)


def _operator_dict(op: Operator, online: bool) -> dict:
    return {
        "id": op.id,
        "callsign": op.callsign,
        "rank": op.rank,
        "role": op.role,
        "ops_status": op.ops_status,
        "team_id": op.team_id,
        "online": online,
        "latitude": op.latitude,
        "longitude": op.longitude,
    }


@router.get("")
def get_hierarchy(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> dict:
    """Return the full Company → Platoon → Section → Team → Operator tree.

    Operators without a team_id are returned under `unassigned_operators` at the top level.
    Each operator carries an `online` flag computed from their last_seen heartbeat.
    """
    now = datetime.now(timezone.utc)

    companies = (
        db.query(Company)
        .options(
            selectinload(Company.platoons)
            .selectinload(__import__("backend.storage.models", fromlist=["Platoon"]).Platoon.sections)
        )
        .all()
    )

    q = db.query(Operator)
    if mission:
        # Show operators in this mission OR operators not assigned to any mission.
        # This ensures freshly imported operators (no mission_id) are always visible.
        q = q.filter(
            (Operator.mission_id == mission.id) | (Operator.mission_id.is_(None))
        )
    operators = q.all()
    by_team: dict[int, list[Operator]] = {}
    unassigned: list[Operator] = []
    for op in operators:
        if op.team_id is None:
            unassigned.append(op)
        else:
            by_team.setdefault(op.team_id, []).append(op)

    tree: list[dict] = []
    for company in companies:
        c_node = {"id": company.id, "name": company.name, "platoons": []}
        for platoon in company.platoons:
            p_node = {"id": platoon.id, "name": platoon.name, "sections": []}
            for section in platoon.sections:
                s_node = {"id": section.id, "name": section.name, "teams": []}
                for team in section.teams:
                    members = by_team.get(team.id, [])
                    s_node["teams"].append(
                        {
                            "id": team.id,
                            "name": team.name,
                            "operators": [_operator_dict(o, _is_online(o, now)) for o in members],
                        }
                    )
                p_node["sections"].append(s_node)
            c_node["platoons"].append(p_node)
        tree.append(c_node)

    return {
        "companies": tree,
        "unassigned_operators": [_operator_dict(o, _is_online(o, now)) for o in unassigned],
        "online_window_seconds": ONLINE_WINDOW_SECONDS,
    }
