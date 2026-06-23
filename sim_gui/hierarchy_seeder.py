"""Seed the 3 PARA / SOR battalion from data/3para_sor.json.

After a `full_reset`, the unit tree (Company/Platoon/Section/Team) is still
present but every non-ADMIN operator is gone. We therefore:

1. Ensure every node in the JSON ORBAT exists (idempotent get-or-create —
   identical to the `ensure_*` pattern in `simulate_ranger_bastogne.py:141`).
2. Re-register every operator via `POST /auth/register/admin` (skipped, then
   `/auth/login`, if the callsign somehow survived).

Returns a `HierarchyState` with everything the rest of the pipeline needs:
team-id lookup, operator-id lookup, callsign → token for follow-on calls, and
a flat list of operators per section (for vehicle attachment).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from sim_gui.backend_client import AdminSession

log = logging.getLogger("sim.hierarchy")

_ORBAT_JSON = Path(__file__).resolve().parent.parent / "data" / "3para_sor.json"


@dataclass(slots=True)
class OperatorRef:
    callsign: str
    rank: str
    role: str
    team_role: str
    password: str
    team_id: int = 0
    op_id: int = 0
    token: str = ""


@dataclass(slots=True)
class TeamRef:
    name: str
    team_id: int
    section_id: int
    section_name: str
    platoon_name: str
    company_name: str
    operators: list[OperatorRef] = field(default_factory=list)


@dataclass(slots=True)
class HierarchyState:
    companies: dict[str, int] = field(default_factory=dict)
    platoons: dict[tuple[str, str], int] = field(default_factory=dict)
    sections: dict[tuple[str, str, str], int] = field(default_factory=dict)
    teams: dict[str, TeamRef] = field(default_factory=dict)
    operators: list[OperatorRef] = field(default_factory=list)

    @property
    def total_operators(self) -> int:
        return len(self.operators)

    def find_team(self, name: str) -> TeamRef | None:
        return self.teams.get(name)

    def combat_sections(self) -> list[TeamRef]:
        """One representative team per section (the section's first team).

        Used by the vehicle seeder so each rifle section gets one vehicle —
        not one per fire-team.
        """
        seen: set[int] = set()
        out: list[TeamRef] = []
        for team in self.teams.values():
            if team.section_id in seen:
                continue
            seen.add(team.section_id)
            out.append(team)
        return out


def load_orbat() -> dict:
    return json.loads(_ORBAT_JSON.read_text())


def _list(session: AdminSession, path: str) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], session.get(path) or [])


def _obj(session: AdminSession, path: str, body: dict) -> dict[str, Any]:
    return cast(dict[str, Any], session.post(path, session.token, body))


def _ensure_company(session: AdminSession, name: str) -> int:
    for c in _list(session, "/companies"):
        if c["name"] == name:
            return int(c["id"])
    return int(_obj(session, "/companies", {"name": name})["id"])


def _ensure_platoon(session: AdminSession, name: str, company_id: int) -> int:
    for p in _list(session, "/platoons"):
        if p["name"] == name and p["company_id"] == company_id:
            return int(p["id"])
    return int(
        _obj(session, "/platoons", {"name": name, "company_id": company_id})["id"]
    )


def _ensure_section(session: AdminSession, name: str, platoon_id: int) -> int:
    for s in _list(session, "/sections"):
        if s["name"] == name and s["platoon_id"] == platoon_id:
            return int(s["id"])
    return int(
        _obj(session, "/sections", {"name": name, "platoon_id": platoon_id})["id"]
    )


def _ensure_team(session: AdminSession, name: str, section_id: int) -> int:
    for t in _list(session, "/teams"):
        if t["name"] == name and t["section_id"] == section_id:
            return int(t["id"])
    return int(_obj(session, "/teams", {"name": name, "section_id": section_id})["id"])


def seed_hierarchy(session: AdminSession) -> HierarchyState:
    """Build the 3 PARA / SOR tree. Idempotent."""
    orbat = load_orbat()
    state = HierarchyState()

    for c_def in orbat["companies"]:
        c_name = c_def["name"]
        c_id = _ensure_company(session, c_name)
        state.companies[c_name] = c_id

        for p_def in c_def.get("platoons", []):
            p_name = p_def["name"]
            p_id = _ensure_platoon(session, p_name, c_id)
            state.platoons[(c_name, p_name)] = p_id

            for s_def in p_def.get("sections", []):
                s_name = s_def["name"]
                s_id = _ensure_section(session, s_name, p_id)
                state.sections[(c_name, p_name, s_name)] = s_id

                for t_def in s_def.get("teams", []):
                    t_name = t_def["name"]
                    t_id = _ensure_team(session, t_name, s_id)
                    team = TeamRef(
                        name=t_name,
                        team_id=t_id,
                        section_id=s_id,
                        section_name=s_name,
                        platoon_name=p_name,
                        company_name=c_name,
                    )
                    for op_def in t_def.get("operators", []):
                        op = OperatorRef(
                            callsign=op_def["callsign"],
                            rank=op_def.get("rank", "OR-1"),
                            role=op_def.get("role", "OPERATOR"),
                            team_role=op_def.get("team_role", "INFANTRY"),
                            password=op_def.get("password", "changeme"),
                            team_id=t_id,
                        )
                        team.operators.append(op)
                        state.operators.append(op)
                    state.teams[t_name] = team

    log.info(
        "ORBAT shape: %d companies, %d platoons, %d sections, %d teams, %d operators",
        len(state.companies),
        len(state.platoons),
        len(state.sections),
        len(state.teams),
        len(state.operators),
    )
    return state


def register_operators(session: AdminSession, state: HierarchyState) -> None:
    """Create / log in every operator in the ORBAT and stash their tokens.

    Uses `session.post_raw` so the admin token's 401 fallback (parallel login
    superseded our session) is handled transparently before we mis-interpret
    the response as "callsign already exists".
    """
    new_count = 0
    relog_count = 0
    for op in state.operators:
        body = {
            "callsign": op.callsign,
            "password": op.password,
            "rank": op.rank,
            "role": op.role,
            "team_id": op.team_id,
        }
        resp = session.post_raw("/auth/register/admin", body)
        if resp.status_code == 201:
            op.token = resp.json()["access_token"]
            new_count += 1
        else:
            # Already exists (rare after a reset, but possible) — fall back.
            try:
                op.token = session.login(op.callsign, op.password)
                relog_count += 1
            except SystemExit:
                log.warning("could not log in existing %s", op.callsign)
                continue
        try:
            me = session.api.get("/auth/me", op.token)
            if isinstance(me, dict) and "id" in me:
                op.op_id = int(me["id"])
        except Exception as e:
            log.debug("could not resolve op_id for %s: %s", op.callsign, e)
    log.info("operators ready: %d new + %d relogged", new_count, relog_count)
