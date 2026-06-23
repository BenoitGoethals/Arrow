"""Attach one vehicle per rifle section based on scenario flavor.

Vehicles in Arrow (`backend/storage/models.py:179`) belong to either an
operator or a team — never both. We pick the **team** and let the backend
derive position from whatever operator the team anchors on. This keeps the
scenario's overlay coherent without requiring per-operator GPS injects up
front.
"""

from __future__ import annotations

import logging

from sim_gui.backend_client import AdminSession
from sim_gui.hierarchy_seeder import HierarchyState

log = logging.getLogger("sim.vehicles")


VEHICLE_PROFILE: dict[str, list[tuple[str, str, str]]] = {
    # flavor → [(prefix, vehicle_type, symbol_code), ...]  cycled across sections
    "land": [
        ("CARNIVAL", "M-ATV", "SFGPEVUH-----"),
        ("REAVER", "RG-33 MRAP", "SFGPEVUH-----"),
        ("SANDFLY", "Husky MCV", "SFGPEVE------"),
    ],
    "airborne": [
        ("HORNET", "Polaris MRZR", "SFGPEVU------"),
        ("WASP", "FAV", "SFGPEVU------"),
    ],
    "riverine": [
        ("PIRATE", "SOC-R Boat", "SFSPC--------"),
        ("MARLIN", "CRRC Zodiac", "SFSPC--------"),
    ],
    "amphib": [
        ("WALRUS", "AAV-7", "SFGPEVAA-----"),
        ("OTTER", "CCM Mk1 Boat", "SFSPC--------"),
    ],
}


def attach_vehicles(
    session: AdminSession,
    state: HierarchyState,
    flavor: str,
    mission_id: int | None = None,
) -> list[dict]:
    """Create one vehicle per section's lead team. Returns the created records."""
    profile = VEHICLE_PROFILE.get(flavor, VEHICLE_PROFILE["land"])
    sections = state.combat_sections()
    log.info("attaching %d vehicle(s) — flavor=%s", len(sections), flavor)
    created: list[dict] = []
    for i, team in enumerate(sections):
        prefix, vehicle_type, sidc = profile[i % len(profile)]
        body = {
            "callsign": f"{prefix}-{team.team_id:02d}",
            "vehicle_type": vehicle_type,
            "symbol_code": sidc,
            "affiliation": "FRIENDLY",
            "ops_status": "OPS",
            "team_id": team.team_id,
            "notes": f"{team.company_name} / {team.platoon_name} / {team.section_name}",
        }
        if mission_id:
            body["mission_id"] = mission_id
        try:
            v = session.post("/vehicles", session.token, body)
            if isinstance(v, dict):
                created.append(v)
        except Exception as e:
            log.warning("vehicle for team %s failed: %s", team.name, e)
    log.info("vehicles created: %d", len(created))
    return created
