"""Scenario protocol + shared dataclasses.

A scenario module exports:

    META: ScenarioMeta
    VEHICLE_FLAVOR: str            # one of "land" | "airborne" | "riverine" | "amphib"
    def inject(api, token, state) -> InjectResult: ...

Optional, only the dynamic scenario:

    def start_runtime(api, token, state, stop_event, log_cb) -> None: ...
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from sim_gui.hierarchy_seeder import HierarchyState


class _ApiLike(Protocol):
    """Structural type covering both `sim_utils.Api` and
    `sim_gui.backend_client.AdminSession` — anything with the Api-style
    `get/post/patch/delete` surface."""

    def post(self, path: str, tok: str, body: dict) -> Any: ...
    def patch(self, path: str, tok: str, body: dict) -> Any: ...


@dataclass(slots=True, frozen=True)
class ScenarioMeta:
    id: str
    name: str
    mission_type: str
    real_world: str
    aor_center: tuple[float, float]
    map_zoom: int
    summary: str


@dataclass(slots=True)
class InjectResult:
    overlay_objects: int = 0
    enemy_units: int = 0
    friendly_pois: int = 0
    control_measures: int = 0
    alerts: int = 0
    reports: int = 0
    fire_missions: int = 0
    extra: dict[str, int] = field(default_factory=dict)


class Scenario(Protocol):
    META: ScenarioMeta
    VEHICLE_FLAVOR: str

    def inject(
        self, api: _ApiLike, token: str, state: HierarchyState
    ) -> InjectResult: ...


LogCallback = Callable[[str], None]
StartRuntime = Callable[
    [_ApiLike, str, HierarchyState, threading.Event, LogCallback], None
]


# ── Shared posting helpers ────────────────────────────────────────────────────


_OVERLAY_KIND = {
    "ENEMY": "enemy_units",
    "POI": "friendly_pois",
    "OBJECTIVE": "friendly_pois",
    "OBJ_AREA": "friendly_pois",
    "ROUTE": "friendly_pois",
    "ZONE": "friendly_pois",
    "MARKER": "friendly_pois",
    "ATK_AXIS": "control_measures",
    "DEF_AREA": "control_measures",
    "AMBUSH": "control_measures",
    "BOUNDARY": "control_measures",
    "FLET": "control_measures",
    "FLOT": "control_measures",
    "PHASE_LINE": "control_measures",
}


def post_overlay(
    api: _ApiLike, token: str, items: list[dict], result: InjectResult
) -> list[dict]:
    """POST every tactical object in *items*, tallying counts into *result*.

    Returns the server's `TacticalObjectOut` responses (with `id` etc) — useful
    for the dynamic scenario which later PATCHes objects to move them.
    """
    out: list[dict] = []
    for body in items:
        resp = api.post("/tactical-objects", token, body)
        if isinstance(resp, dict):
            out.append(resp)
            result.overlay_objects += 1
            field = _OVERLAY_KIND.get(body.get("type", ""), None)
            if field is not None:
                setattr(result, field, getattr(result, field) + 1)
    return out


def post_tic(
    api: _ApiLike,
    token: str,
    lat: float,
    lon: float,
    result: InjectResult | None = None,
) -> dict | None:
    """Trigger a TIC alert at (lat,lon)."""
    try:
        resp = api.post(
            "/alerts", token, {"type": "TIC", "latitude": lat, "longitude": lon}
        )
        if result is not None:
            result.alerts += 1
        return resp if isinstance(resp, dict) else None
    except Exception:
        return None


def post_salute(
    api: _ApiLike,
    token: str,
    payload: dict,
    result: InjectResult | None = None,
) -> dict | None:
    """Submit a SPOT report carrying a SALUTE payload."""
    try:
        resp = api.post("/reports", token, {"type": "SPOT", "payload": payload})
        if result is not None:
            result.reports += 1
        return resp if isinstance(resp, dict) else None
    except Exception:
        return None


def post_drone_spot(
    api: _ApiLike,
    token: str,
    body: dict,
    result: InjectResult | None = None,
) -> dict | None:
    try:
        resp = api.post("/reports/drone-spot", token, body)
        if result is not None:
            result.reports += 1
        return resp if isinstance(resp, dict) else None
    except Exception:
        return None


def post_fire_mission(
    api: _ApiLike,
    token: str,
    body: dict,
    result: InjectResult | None = None,
) -> dict | None:
    try:
        resp = api.post("/fire-missions", token, body)
        if result is not None:
            result.fire_missions += 1
        return resp if isinstance(resp, dict) else None
    except Exception:
        return None


def post_logrep(
    api: _ApiLike,
    token: str,
    payload: dict,
    result: InjectResult | None = None,
) -> dict | None:
    """Submit a NATO LOGREP. Shape mirrors `simulate_logreps.py`."""
    try:
        resp = api.post("/reports", token, {"type": "LOGREP", "payload": payload})
        if result is not None:
            result.reports += 1
        return resp if isinstance(resp, dict) else None
    except Exception:
        return None


def post_medevac(
    api: _ApiLike,
    token: str,
    payload: dict,
    result: InjectResult | None = None,
) -> dict | None:
    """Submit a 9-line MEDEVAC report."""
    try:
        resp = api.post("/reports", token, {"type": "MEDEVAC", "payload": payload})
        if result is not None:
            result.reports += 1
        return resp if isinstance(resp, dict) else None
    except Exception:
        return None


def set_ops_status(
    api: _ApiLike,
    token: str,
    operator_id: int,
    ops_status: str,
) -> dict | None:
    """PATCH /operators/{id}/ops-status — mark a casualty (INOPS/KIA/MIA)."""
    try:
        resp = api.patch(
            f"/operators/{operator_id}/ops-status",
            token,
            {"ops_status": ops_status},
        )
        return resp if isinstance(resp, dict) else None
    except Exception:
        return None


def post_supply_point(
    api: _ApiLike,
    token: str,
    body: dict,
    result: InjectResult | None = None,
) -> dict | None:
    """Create a logistics supply point. Requires an active mission scope."""
    try:
        resp = api.post("/logcop/supply-points", token, body)
        if result is not None:
            result.extra["supply_points"] = result.extra.get("supply_points", 0) + 1
        return resp if isinstance(resp, dict) else None
    except Exception:
        return None


# ── OPORD builder ───────────────────────────────────────────────────────────


def build_default_opord(meta: ScenarioMeta) -> dict:
    """Generate a 5-paragraph OPORD from scenario metadata.

    Scenario modules can override by exporting their own `build_opord(meta)`
    function that returns a dict in the same shape — see
    `backend/opord/schemas.py:OpordCreate`.
    """
    return {
        "title": f"OPORD — {meta.name}",
        "opord_number": f"OPS-{meta.id.upper()[:6]}-001",
        "dtg": "190001ZJUN26",
        "time_zone": "ZULU",
        "classification": "UNCLASSIFIED // FOUO",
        "references": (
            f"(a) Real-world basis: {meta.real_world}\n"
            f"(b) Mission type: {meta.mission_type}\n"
            "(c) Map: NATO 1:50,000 AOR sheet\n"
            "(d) BN INTSUM 26-019, ROE Card: TF DAGGER ROE-01"
        ),
        "task_organization": (
            "3 PARA / SOR — TASK ORGANIZATION\n"
            "  BHQ — Battalion HQ, Signals Plt, Bn Aid Station, Log Plt, Recon Plt\n"
            "  ECHO CIE — Main effort rifle company\n"
            "  FOXTROT CIE — Supporting effort rifle company\n"
            "  GOLF CIE — Reserve rifle company\n"
            "  HOTEL CIE (Support) — Sniper Plt, Mortar Plt, Pioneer Plt, AT Plt\n"
            "  Attached: GHOSTRIDER-1 (F-16C CAS), DUSTOFF-1 (UH-60 MEDEVAC)"
        ),
        "situation": {
            "enemy": (
                "Estimated enemy: reinforced motor-rifle battalion with armour, "
                "mortar, ATGM, MANPADS, AAA, and BN TAC HQ in zone. Defends in "
                "depth from prepared positions. Counter-attack capability noted."
            ),
            "friendly": (
                "3 PARA / SOR (-) is main effort. Adjacent units: NCA / TBD. "
                "Joint fires available; CAS on-station +120 min."
            ),
            "civilian": (
                "Low civilian density in AO. Local authorities notified; key "
                "infrastructure deconfliction list briefed."
            ),
            "weather": (
                "Visibility good. Wind 270/12 kts. Cloud SCT @ 4500 ft. "
                "BMNT 04:42 / EENT 21:18 local."
            ),
            "terrain": (
                "OCOKA: Open, gently rolling. Key terrain — ridge OBJ DRAGON "
                "(observation + dominant overwatch). Approach NW restricted by "
                "tree line. Canalising avenue along PL OBJECTIVE."
            ),
        },
        "mission": (
            f"3 PARA / SOR conducts {meta.mission_type} NLT H-Hour to "
            f"{meta.summary.split('.')[0].lower()} IOT deny enemy use of the "
            "AOR and enable follow-on operations."
        ),
        "execution": {
            "commanders_intent": (
                "PURPOSE: seize OBJ DRAGON and defeat enemy in zone, enabling "
                "follow-on coalition operations in sector.\n"
                "KEY TASKS: secure LZ INSERT; cross PL LOD by H+30; seize OBJ "
                "DRAGON by H+120; establish defence in depth; defeat counter-"
                "attack; conduct exfil by H+300.\n"
                "END STATE: OBJ secured; enemy destroyed/withdrawn in zone; "
                "battalion exfiltrated with zero left behind; civilian "
                "infrastructure intact."
            ),
            "concept_of_operations": (
                f"Type of operation: {meta.mission_type}. Four-phase scheme:\n"
                "  Phase 1 INSERT (~90m) — Battalion lifts to LZ INSERT, "
                "consolidates at ORP THUNDER, conducts final coordination.\n"
                "  Phase 2 ATTACK (~150m) — Cross PL LOD, press east, seize "
                "OBJ DRAGON. ECHO main effort.\n"
                "  Phase 3 DEFEND (~150m) — Establish defence box BP-1, repel "
                "counter-attacks, prepare exfil.\n"
                "  Phase 4 EXTRACT (~90m) — Withdraw under fire to PZ TALON, "
                "lift to FOB."
            ),
            "tasks_to_subordinate_units": {
                "ECHO CIE": (
                    "Main effort. Seize OBJ DRAGON NLT H+120. Establish "
                    "blocking position OBJ-NORTH."
                ),
                "FOXTROT CIE": (
                    "Supporting effort. Support by fire from PL OBJECTIVE. "
                    "Prepared to relieve ECHO on order."
                ),
                "GOLF CIE": (
                    "Reserve at ORP THUNDER. Be prepared to counter-attack or "
                    "exploit success."
                ),
                "HOTEL CIE": (
                    "Sniper overwatch from PL DEFEND. Mortar fires on call. "
                    "AT screen south flank."
                ),
                "BHQ": (
                    "C2 from CP RAVEN, BAS DAGGER for casualty receiving, "
                    "Log Plt operates SP-I/III/V/VIII/IX."
                ),
            },
            "coordinating_instructions": [
                "ROE per TF DAGGER ROE-01.",
                "TIC: immediate FM + CAS request authorised; FAC clears.",
                "MEDEVAC pickup default: nearest LZ or PZ.",
                "PIR/CCIR per BN INTSUM. Drone observations report immediately.",
                "Air corridor: 12,000-18,000 ft AGL. ROZ over OBJ DRAGON.",
                "No-strike list briefed and acknowledged.",
            ],
        },
        "sustainment": {
            "supply": (
                "Class I (rations) at SP-I FOOD near BAS DAGGER. Class III "
                "(fuel) at SP-III FUEL. Class V (ammunition) at SP-V AMMO "
                "with forward dump at ORP THUNDER. Class VIII (medical) at "
                "BAS DAGGER. Class IX (repair parts) at SP-IX REPAIR."
            ),
            "medical": (
                "BAS DAGGER receives casualties. CCP STORM forward. MEDEVAC "
                "via DUSTOFF-1 (UH-60). All operators carry IFAK + tourniquet."
            ),
            "personnel": (
                "120+ operators inserted. Hot replacements via DZ REINFORCE on "
                "call. EPW collection at CCP STORM."
            ),
        },
        "command_signal": {
            "command": (
                "BN CDR forward with ECHO CIE TAC. XO/S3 at CP RAVEN. "
                "Succession: CDR → XO → S3 → SR Coy CDR present."
            ),
            "signal": (
                "Primary: VHF 250.100. Alternate: VHF 250.150. "
                "Contingency: HF 8.250 USB. Emergency: pyro / smoke per SOP. "
                "CoT TCP active to BN TOC. Callsigns per CEOI."
            ),
        },
    }


def get_opord(scenario_module, meta: ScenarioMeta) -> dict:
    """Return the scenario's OPORD — either its own `build_opord()` or a default."""
    custom = getattr(scenario_module, "build_opord", None)
    if callable(custom):
        try:
            built = custom(meta)
            if isinstance(built, dict):
                return built
        except Exception:
            pass
    return build_default_opord(meta)
