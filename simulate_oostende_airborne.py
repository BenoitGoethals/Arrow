#!/usr/bin/env python3
"""
Arrow — Operation SEAGULL: 1-75 RGR BN airborne assault on Oostende Airport
============================================================================

Battalion-level end-to-end simulator. Stands up everything an operations cell
needs to brief, rehearse and "fight" a BN-level airborne seizure of Oostende
Airport (EBOS) against the live Arrow backend.

  1. Hierarchy  : BN HQ COY + RANGER COY (A COY) + B COY + C COY
                  → 4 companies, 14 platoons, 28 sections, 31 teams, 49 operators
  2. Mission    : Created/adopted and started via /missions
  3. Roster     : 49 operators via /auth/register/admin
  4. OPORD      : BN-level 5-paragraph OPORD 26-002 SEAGULL (UNCLASS // FOUO)
  5. Graphics   : DZ OSPREY/FALCON, OBJ TERMINAL/RUNWAY, PL WAVE/SURF,
                  ATK axes (3 PLTs), B/C COY blocking positions, BN boundaries,
                  enemy positions (10+), friendly POIs (15)
  6. Reports    : MEDEVAC (1x URGENT — 3-1 SL GSW east fence breach)
                  DRONE_SPOT (enemy ISR quadcopter over north fence — W-MTR1)
                  SPOT/SALUTE (enemy QRF 4x BTR-80 on N33 — B-1)
  7. Fire plan  : 4 missions (suppress tower, destroy vehicles, suppress east
                  perimeter, SMOKE north gate)
  8. Movement   : A COY two-DZ converging assault on airport;
                  B COY vehicle-mounts to N33 blocking position (east);
                  C COY vehicle-mounts to A10/E40 blocking position (SE);
                  BN HQ holds at BN TAC CP north of airport

Run:
    uv run python simulate_oostende_airborne.py
    uv run python simulate_oostende_airborne.py --backend https://78.21.255.210:6200/api
    uv run python simulate_oostende_airborne.py --reset
    uv run python simulate_oostende_airborne.py --no-move
    uv run python simulate_oostende_airborne.py --steps 80 --dt 1.5
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import time
from dataclasses import dataclass

import sim_utils

log = logging.getLogger("seagull")

# ── Operation constants ───────────────────────────────────────────────────────

AIRPORT  = (51.1989, 2.8622)   # Oostende Airport (EBOS) reference point
H_HOUR   = "262100ZMAY26"      # Night insertion
OP_NAME  = "OPERATION SEAGULL"
BN_NAME  = "1-75 RGR BN"

# Geographic reference points
N33_BLOCK    = (51.1840, 3.0500)   # B COY blocking position — N33 at Oudenburg
E40_BLOCK    = (51.1940, 3.1600)   # C COY blocking position — A10/E40 W of Brugge
BRUGGE_AREA  = (51.2080, 3.2200)   # start area for B/C COY (vehicle-mounted)
BN_TAC_CP    = (51.2130, 2.8622)   # BN TAC CP at DZ OSPREY / north dunes


# ── Geometry helpers ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LL:
    lat: float
    lon: float

    def offset(self, north_m: float, east_m: float) -> "LL":
        d_lat = north_m / 111_320.0
        d_lon = east_m  / (111_320.0 * math.cos(math.radians(self.lat)))
        return LL(self.lat + d_lat, self.lon + d_lon)

    def bearing(self, bearing_deg: float, distance_m: float) -> "LL":
        rad = math.radians(bearing_deg)
        return self.offset(
            north_m=distance_m * math.cos(rad),
            east_m =distance_m * math.sin(rad),
        )

    def pair(self) -> list[float]:
        return [self.lat, self.lon]


def lerp(a: LL, b: LL, t: float) -> LL:
    return LL(a.lat + (b.lat - a.lat) * t, a.lon + (b.lon - a.lon) * t)


Api = sim_utils.Api


# ── Roster ────────────────────────────────────────────────────────────────────
# insert field:
#   OSPREY   — airborne, DZ OSPREY (north dunes)
#   FALCON   — airborne, DZ FALCON (east fields)
#   VEHICLE  — vehicle-mounted; start = BRUGGE_AREA
#   BN_TAC   — remains at BN TAC CP throughout

@dataclass
class OpRoster:
    callsign:  str
    rank:      str
    role:      str       # OPERATOR | BATTLE_CAPTAIN | ADMIN
    company:   str       # company key for hierarchy builder
    team_name: str
    duty:      str
    insert:    str       # OSPREY | FALCON | VEHICLE | BN_TAC
    token:     str = ""
    op_id:     int = 0
    team_id:   int = 0


ROSTER: list[OpRoster] = [
    # ── BN HQ ─────────────────────────────────────────────────────────────────
    OpRoster("BN-6",   "OF-5", "BATTLE_CAPTAIN", "BN_HQ", "BN-CMD",   "BN CO",      "BN_TAC"),
    OpRoster("BN-5",   "OF-4", "BATTLE_CAPTAIN", "BN_HQ", "BN-CMD",   "BN XO",      "BN_TAC"),
    OpRoster("BN-7",   "OR-9", "OPERATOR",       "BN_HQ", "BN-CMD",   "BN CSM",     "BN_TAC"),
    OpRoster("BN-S2",  "OF-2", "OPERATOR",       "BN_HQ", "BN-STAFF", "S2 Intel",   "BN_TAC"),
    OpRoster("BN-S3",  "OF-3", "OPERATOR",       "BN_HQ", "BN-STAFF", "S3 Ops",     "BN_TAC"),
    OpRoster("BN-S4",  "OF-2", "OPERATOR",       "BN_HQ", "BN-STAFF", "S4 Log",     "BN_TAC"),
    OpRoster("BN-S6",  "OF-2", "OPERATOR",       "BN_HQ", "BN-STAFF", "S6 Comms",   "BN_TAC"),
    OpRoster("BN-FSO", "OF-2", "OPERATOR",       "BN_HQ", "BN-FSE",   "BN FSO",     "BN_TAC"),
    OpRoster("BN-JTAC","OR-7", "OPERATOR",       "BN_HQ", "BN-FSE",   "BN JTAC",    "BN_TAC"),

    # ── A COY — RANGER COY (main effort, airborne assault) ───────────────────
    # COY HQ → DZ OSPREY
    OpRoster("RANGER-6",  "OF-3", "BATTLE_CAPTAIN", "A_COY", "HHC-CMD",   "CO",       "OSPREY"),
    OpRoster("RANGER-5",  "OF-2", "BATTLE_CAPTAIN", "A_COY", "HHC-CMD",   "XO",       "OSPREY"),
    OpRoster("RANGER-7",  "OR-8", "OPERATOR",       "A_COY", "HHC-CMD",   "1SG",      "OSPREY"),
    OpRoster("RANGER-FO", "OF-1", "OPERATOR",       "A_COY", "HHC-FIRES", "FO/JTAC",  "OSPREY"),
    # 1 PLT → DZ OSPREY (supporting, north perimeter)
    OpRoster("1-6",  "OF-1", "OPERATOR", "A_COY", "1PLT-HQ",  "PL",  "OSPREY"),
    OpRoster("1-7",  "OR-7", "OPERATOR", "A_COY", "1PLT-HQ",  "PSG", "OSPREY"),
    OpRoster("1-1",  "OR-6", "OPERATOR", "A_COY", "1PLT-SQ1", "SL",  "OSPREY"),
    OpRoster("1-2",  "OR-6", "OPERATOR", "A_COY", "1PLT-SQ2", "SL",  "OSPREY"),
    OpRoster("1-3",  "OR-6", "OPERATOR", "A_COY", "1PLT-SQ3", "SL",  "OSPREY"),
    # 2 PLT → DZ FALCON (reserve, east threshold)
    OpRoster("2-6",  "OF-1", "OPERATOR", "A_COY", "2PLT-HQ",  "PL",  "FALCON"),
    OpRoster("2-7",  "OR-7", "OPERATOR", "A_COY", "2PLT-HQ",  "PSG", "FALCON"),
    OpRoster("2-1",  "OR-6", "OPERATOR", "A_COY", "2PLT-SQ1", "SL",  "FALCON"),
    OpRoster("2-2",  "OR-6", "OPERATOR", "A_COY", "2PLT-SQ2", "SL",  "FALCON"),
    OpRoster("2-3",  "OR-6", "OPERATOR", "A_COY", "2PLT-SQ3", "SL",  "FALCON"),
    # 3 PLT → DZ FALCON (main effort, seize terminal from east)
    OpRoster("3-6",  "OF-1", "OPERATOR", "A_COY", "3PLT-HQ",  "PL",  "FALCON"),
    OpRoster("3-7",  "OR-7", "OPERATOR", "A_COY", "3PLT-HQ",  "PSG", "FALCON"),
    OpRoster("3-1",  "OR-6", "OPERATOR", "A_COY", "3PLT-SQ1", "SL",  "FALCON"),
    OpRoster("3-2",  "OR-6", "OPERATOR", "A_COY", "3PLT-SQ2", "SL",  "FALCON"),
    OpRoster("3-3",  "OR-6", "OPERATOR", "A_COY", "3PLT-SQ3", "SL",  "FALCON"),
    # WPNS PLT → DZ OSPREY (mortar line + MMG overwatch)
    OpRoster("W-6",    "OF-1", "OPERATOR", "A_COY", "WPLT-HQ",  "PL",      "OSPREY"),
    OpRoster("W-MTR1", "OR-5", "OPERATOR", "A_COY", "WPLT-MTR", "Mortar 1","OSPREY"),
    OpRoster("W-MTR2", "OR-5", "OPERATOR", "A_COY", "WPLT-MTR", "Mortar 2","OSPREY"),
    OpRoster("W-MMG1", "OR-5", "OPERATOR", "A_COY", "WPLT-MMG", "MMG 1",   "OSPREY"),
    OpRoster("W-MMG2", "OR-5", "OPERATOR", "A_COY", "WPLT-MMG", "MMG 2",   "OSPREY"),

    # ── B COY — blocking N33 (Brugge approach, vehicle-mounted) ──────────────
    OpRoster("B-6",  "OF-2", "BATTLE_CAPTAIN", "B_COY", "BPLT-HQ",  "PL",  "VEHICLE"),
    OpRoster("B-7",  "OR-7", "OPERATOR",       "B_COY", "BPLT-HQ",  "PSG", "VEHICLE"),
    OpRoster("B-1",  "OR-6", "OPERATOR",       "B_COY", "BPLT-SQ1", "SL",  "VEHICLE"),
    OpRoster("B-2",  "OR-6", "OPERATOR",       "B_COY", "BPLT-SQ2", "SL",  "VEHICLE"),
    OpRoster("B-3",  "OR-6", "OPERATOR",       "B_COY", "BPLT-SQ3", "SL",  "VEHICLE"),

    # ── C COY — blocking A10/E40 west of Brugge (vehicle-mounted) ────────────
    OpRoster("C-6",  "OF-2", "BATTLE_CAPTAIN", "C_COY", "CPLT-HQ",  "PL",  "VEHICLE"),
    OpRoster("C-7",  "OR-7", "OPERATOR",       "C_COY", "CPLT-HQ",  "PSG", "VEHICLE"),
    OpRoster("C-1",  "OR-6", "OPERATOR",       "C_COY", "CPLT-SQ1", "SL",  "VEHICLE"),
    OpRoster("C-2",  "OR-6", "OPERATOR",       "C_COY", "CPLT-SQ2", "SL",  "VEHICLE"),
    OpRoster("C-3",  "OR-6", "OPERATOR",       "C_COY", "CPLT-SQ3", "SL",  "VEHICLE"),
]


# ── Hierarchy ─────────────────────────────────────────────────────────────────

def ensure_company(api: Api, tok: str, name: str) -> int:
    for c in api.get("/companies", tok):
        if c["name"] == name:
            return c["id"]
    return api.post("/companies", tok, {"name": name})["id"]


def ensure_platoon(api: Api, tok: str, name: str, coy_id: int) -> int:
    for p in api.get("/platoons", tok):
        if p["name"] == name and p["company_id"] == coy_id:
            return p["id"]
    return api.post("/platoons", tok, {"name": name, "company_id": coy_id})["id"]


def ensure_section(api: Api, tok: str, name: str, plt_id: int) -> int:
    for s in api.get("/sections", tok):
        if s["name"] == name and s["platoon_id"] == plt_id:
            return s["id"]
    return api.post("/sections", tok, {"name": name, "platoon_id": plt_id})["id"]


def ensure_team(api: Api, tok: str, name: str, sec_id: int) -> int:
    for t in api.get("/teams", tok):
        if t["name"] == name and t["section_id"] == sec_id:
            return t["id"]
    return api.post("/teams", tok, {"name": name, "section_id": sec_id})["id"]


def build_hierarchy(api: Api, admin_tok: str) -> dict[str, int]:
    """Create the full BN hierarchy (4 companies). Returns {team_name: team_id}."""
    teams: dict[str, int] = {}

    # ── BN HQ ─────────────────────────────────────────────────────────────────
    bn_id  = ensure_company(api, admin_tok, "BN HQ COY")
    bn_plt = ensure_platoon(api, admin_tok, "BN HQ PLT", bn_id)
    bn_sec = ensure_section(api, admin_tok, "BN-HQ-SEC", bn_plt)
    for team in ("BN-CMD", "BN-STAFF", "BN-FSE"):
        teams[team] = ensure_team(api, admin_tok, team, bn_sec)

    # ── A COY (RANGER COY) ────────────────────────────────────────────────────
    a_id = ensure_company(api, admin_tok, "RANGER COY")
    plts = {
        "HHC":  ensure_platoon(api, admin_tok, "HHC",      a_id),
        "1PLT": ensure_platoon(api, admin_tok, "1 PLT",    a_id),
        "2PLT": ensure_platoon(api, admin_tok, "2 PLT",    a_id),
        "3PLT": ensure_platoon(api, admin_tok, "3 PLT",    a_id),
        "WPLT": ensure_platoon(api, admin_tok, "WPNS PLT", a_id),
    }
    secs = {p: ensure_section(api, admin_tok, f"{p}-SEC", plts[p]) for p in plts}
    a_teams = [
        ("HHC-CMD",   "HHC"), ("HHC-FIRES", "HHC"),
        ("1PLT-HQ",  "1PLT"), ("1PLT-SQ1",  "1PLT"), ("1PLT-SQ2", "1PLT"), ("1PLT-SQ3", "1PLT"),
        ("2PLT-HQ",  "2PLT"), ("2PLT-SQ1",  "2PLT"), ("2PLT-SQ2", "2PLT"), ("2PLT-SQ3", "2PLT"),
        ("3PLT-HQ",  "3PLT"), ("3PLT-SQ1",  "3PLT"), ("3PLT-SQ2", "3PLT"), ("3PLT-SQ3", "3PLT"),
        ("WPLT-HQ",  "WPLT"), ("WPLT-MTR",  "WPLT"), ("WPLT-MMG", "WPLT"),
    ]
    for name, plt in a_teams:
        teams[name] = ensure_team(api, admin_tok, name, secs[plt])

    # ── B COY (blocking N33) ──────────────────────────────────────────────────
    b_id  = ensure_company(api, admin_tok, "B COY")
    b_plt = ensure_platoon(api, admin_tok, "B PLT",    b_id)
    b_sec = ensure_section(api, admin_tok, "BPLT-SEC", b_plt)
    for team in ("BPLT-HQ", "BPLT-SQ1", "BPLT-SQ2", "BPLT-SQ3"):
        teams[team] = ensure_team(api, admin_tok, team, b_sec)

    # ── C COY (blocking A10/E40) ──────────────────────────────────────────────
    c_id  = ensure_company(api, admin_tok, "C COY")
    c_plt = ensure_platoon(api, admin_tok, "C PLT",    c_id)
    c_sec = ensure_section(api, admin_tok, "CPLT-SEC", c_plt)
    for team in ("CPLT-HQ", "CPLT-SQ1", "CPLT-SQ2", "CPLT-SQ3"):
        teams[team] = ensure_team(api, admin_tok, team, c_sec)

    log.info("hierarchy ready: %d teams across 4 companies", len(teams))
    return teams


# ── Operators ─────────────────────────────────────────────────────────────────

def _find_operator_id(api: Api, admin_tok: str, callsign: str) -> int | None:
    for op in api.get("/operators", admin_tok):
        if op.get("callsign") == callsign:
            return op["id"]
    return None


def register_operators(api: Api, admin_tok: str, teams: dict[str, int],
                       password: str) -> None:
    for r in ROSTER:
        r.team_id = teams[r.team_name]
        body = {
            "callsign": r.callsign, "password": password,
            "rank":     r.rank,     "role":     r.role,
            "team_id":  r.team_id,
        }
        resp = api.c.post(
            api._p("/auth/register/admin"), json=body,
            headers={"Authorization": f"Bearer {admin_tok}"},
        )
        if resp.status_code == 201:
            r.token = resp.json()["access_token"]
        else:
            # Already exists — reset password via admin endpoint then log in
            op_id = _find_operator_id(api, admin_tok, r.callsign)
            if op_id is not None:
                api.c.post(
                    api._p(f"/operators/{op_id}/set-password"),
                    json={"password": password},
                    headers={"Authorization": f"Bearer {admin_tok}"},
                )
            time.sleep(0.15)   # avoid bursting the /auth/login rate limit
            r.token = api.login(r.callsign, password)
        me = api.get("/auth/me", r.token)
        r.op_id = me["id"]
    log.info("roster ready: %d operators", len(ROSTER))


# ── OPORD ─────────────────────────────────────────────────────────────────────

def build_opord() -> dict:
    return {
        "title":          "OPORD 26-002 — OPERATION SEAGULL",
        "opord_number":   "26-002",
        "dtg":            H_HOUR,
        "time_zone":      "ZULU",
        "classification": "UNCLASSIFIED // FOUO",
        "references": (
            "(a) Map: NATO 1:25,000 Belgium Coast Sheet 11/1-2 OOSTENDE\n"
            "(b) BDE WARNORD 14 dtd 251400ZMAY26\n"
            "(c) BN INTSUM 26-025 — EBOS garrison est. 30-40 PAX; QRF Brugge est. 60-80 PAX ETA H+60\n"
            "(d) EBOS Aerodrome Chart (mil edition) AIP EBOS-AD-2\n"
            "(e) ROE Card: TF DAGGER ROE-01\n"
            "(f) BN CBRN ANNEX 26-002A — MOPP-0 throughout; kit carried"
        ),
        "task_organization": (
            f"{BN_NAME} (TF SEAGULL) — TASK ORGANIZATION\n"
            "  BN HQ — CO (BN-6), XO (BN-5), CSM (BN-7), "
            "S2 (BN-S2), S3 (BN-S3), S4 (BN-S4), S6 (BN-S6), "
            "FSO (BN-FSO), JTAC (BN-JTAC)\n"
            "  A COY (RANGER COY) — MAIN EFFORT — AIRBORNE ASSAULT\n"
            "    COY HQ: RANGER-6 CO, RANGER-5 XO, RANGER-7 1SG, RANGER-FO FO/JTAC\n"
            "    1 PLT (SUPPORTING): 1-6 PL, 1-7 PSG, 1-1/2/3 SL — DZ OSPREY\n"
            "    2 PLT (RESERVE):    2-6 PL, 2-7 PSG, 2-1/2/3 SL — DZ FALCON\n"
            "    3 PLT (MAIN EFFORT):3-6 PL, 3-7 PSG, 3-1/2/3 SL — DZ FALCON\n"
            "    WPNS PLT: W-6 PL, W-MTR1/2 (81mm), W-MMG1/2 (M240B) — DZ OSPREY\n"
            "  B COY — BLOCKING — N33 BRUGGE APPROACH\n"
            "    B-6 PL, B-7 PSG, B-1/2/3 SL (vehicle-mounted, HMMWV x5)\n"
            "  C COY — BLOCKING — A10/E40 BRUGGE APPROACH\n"
            "    C-6 PL, C-7 PSG, C-1/2/3 SL (vehicle-mounted, HMMWV x5)\n"
            "  ATTACHMENTS — BDE FSE (1x JTAC embedded BN-JTAC); "
            "CAS on-call 2× F/A-18E (WASP 11); "
            "CCT embeds with RANGER-FO for CLP approach control"
        ),
        "situation": {
            "enemy": (
                "Motorised rifle platoon (-), est. 30-40 PAX, occupying "
                "Oostende Airport (EBOS) as a forward logistics node. "
                "Two technical vehicles (DShK-mounted) on south apron "
                "(51.1975N/2.862E). MANPADS team mobile, last seen vic "
                "control tower. Perimeter guard posts at west fence "
                "(51.199N/2.843E), south fence, east gate (51.199N/2.877E). "
                "Observer with optics in control tower (51.200N/2.858E). "
                "MMG bunker on north apron. "
                "ENEMY COA-MOST-LIKELY: delay on perimeter, withdraw "
                "toward N33 if airfield compromised. "
                "COA-MOST-DANGEROUS: QRF from Brugge garrison "
                "(est. 60-80 PAX, 4x BTR-80), ETA H+60 via N33/A10."
            ),
            "friendly": (
                f"{BN_NAME} (TF SEAGULL) is BDE main effort for the Belgian coast. "
                "A COY (RANGER COY) conducts the airborne seizure of EBOS; "
                "B COY blocks N33 at Oudenburg to prevent QRF from Brugge; "
                "C COY blocks A10/E40 approach west of Brugge for depth protection. "
                "BN HQ establishes TAC CP at DZ OSPREY area NLT H+15. "
                "Adjacent: BDE reserve vic Dunkirk (FR). "
                "CAS: 2× F/A-18E (WASP 11) loiter vic 51.30N/3.00E, "
                "armed JDAM + Mk-82, 30-min loiter."
            ),
            "civilian": (
                "Civilian airfield — EBOS active 0600-2200L. "
                "Night insertion minimises civilian presence. Airport staff "
                "est. 5-10 in terminal at H-Hour (security, night ops). "
                "Fire control: NO FIRE within 100m of terminal glass facade. "
                "Fuel farm at south apron — avoid direct fire (secondary). "
                "N33 / A10 — civilians possible until H-Hour curfew (H-30). "
                "B/C COY must establish VCPs before engaging vehicle threats."
            ),
            "weather": (
                "BMNT 0516Z, EENT 2148Z. H-Hour 2100Z = 47 min before EENT. "
                "Partly cloudy 40%, ceiling 2400m. Wind 270/08 KTS (westerly). "
                "Vis 12km. No precipitation. NVG: GOOD. "
                "Moon illumination 12% (near-total darkness — favours assault). "
                "Sea state 2. Parachute conditions GREEN (wind < 10 kts at alt)."
            ),
            "terrain": (
                "OCOKA:\n"
                "  O — Open runway environment; no cover within 300m of "
                "runway 08/26 centreline. Perimeter fence canalises dismounted.\n"
                "  C — Three entry gates (N, E, S) are key nodes. N33 and "
                "A10/E40 are the two enemy QRF routes.\n"
                "  K — Control tower (obs), terminal building (key terrain), "
                "fuel farm (hazard), CLP pad (RWY 08 threshold).\n"
                "  O — Dunes 800m north offer covered DZ and mortar line; "
                "harbour mouth 1.5km west.\n"
                "  A — Open ground east of airport supports DZ FALCON "
                "and 3 PLT/2 PLT approach. Oudenburg fields open "
                "for B COY vehicle movement."
            ),
        },
        "mission": (
            f"{BN_NAME} conducts a multi-company airborne assault and blocking "
            f"operation NLT {H_HOUR} to seize and hold Oostende Airport (OBJ SEAGULL, "
            "51.1989N/2.8622E) and block enemy QRF routes (N33 and A10/E40) "
            "IOT destroy/capture the EBOS garrison and enable CLP air-landing of "
            "BDE follow-on forces NLT H+120."
        ),
        "execution": {
            "commanders_intent": {
                "purpose": (
                    "Rapidly seize EBOS airport intact, destroy the enemy garrison, "
                    "block both QRF routes simultaneously, and secure the runway for "
                    "immediate follow-on air-landing of BDE main body."
                ),
                "key_tasks": [
                    f"A COY inserts DZ OSPREY + DZ FALCON NLT {H_HOUR}.",
                    "B COY occupies N33 blocking position (Oudenburg) NLT H-15.",
                    "C COY occupies A10/E40 blocking position (W of Brugge) NLT H-15.",
                    "WPNS PLT engages TRP-001 (tower) + TRP-002 (south apron) H-5 to H+0.",
                    "3 PLT seizes OBJ TERMINAL NLT H+45.",
                    "1 PLT clears north perimeter, secures north gate NLT H+30.",
                    "2 PLT secures RWY 26 threshold and east gate NLT H+35.",
                    "Runway clear and CLP pad marked NLT H+90.",
                    "Preserve terminal structure and fuel farm throughout.",
                ],
                "end_state": (
                    "OBJ SEAGULL seized; enemy garrison destroyed or captured; "
                    "RANGER COY consolidated on PL SURF; "
                    "B COY holding N33 — QRF blocked; "
                    "C COY holding A10/E40 — depth block in place; "
                    "runway 08/26 clear; CLP pad lit and marked; "
                    "airport infrastructure intact for BDE air-landing."
                ),
            },
            "concept_of_operations": {
                "form_of_maneuver": (
                    "BN converging operation: A COY airborne assault from two DZs "
                    "on the objective simultaneously with B/C COY vehicle-mounted "
                    "blocking on both QRF approach routes. BN TAC CP at DZ OSPREY."
                ),
                "scheme_of_maneuver": (
                    "Phase 1 — Isolation (H-60 to H-Hour): B COY and C COY "
                    "vehicle-mount and occupy blocking positions NLT H-15. "
                    "B COY blocks N33 at Oudenburg (51.184N/3.050E). "
                    "C COY blocks A10/E40 west of Brugge (51.194N/3.160E). "
                    "C-130 package lifts A COY + BN HQ from FOB.\n"
                    "Phase 2 — Insertion (H-Hour): First pass drops 1 PLT, "
                    "WPNS PLT, COY HQ, BN HQ at DZ OSPREY (dunes north). "
                    "Second pass drops 2 PLT + 3 PLT at DZ FALCON (east fields). "
                    "BN TAC CP established at DZ OSPREY NLT H+15.\n"
                    "Phase 3 — Isolation of OBJ (H-Hour to H+20): WPNS PLT "
                    "occupies mortar line. Engages TRP-001 (tower) H-5. "
                    "MMG overwatches north gate. 1 PLT advances south to perimeter.\n"
                    "Phase 4 — Assault (H+20 to H+60): 3 PLT (MAIN EFFORT) "
                    "breaches east fence, advances west, seizes OBJ TERMINAL. "
                    "2 PLT secures east gate and RWY 26 threshold. "
                    "1 PLT sweeps north taxiway, links COY HQ at terminal.\n"
                    "Phase 5 — Consolidation (H+60 to H+120): Clear terminal. "
                    "CCP active DZ OSPREY. Mark CLP pad RWY 08. "
                    "BN-JTAC coordinates CAS against QRF if B/C COY positions "
                    "are penetrated. RANGER-FO controls CCT for first CLP.\n"
                    "Phase 6 — CLP (H+120): Guide first C-130 onto RWY 08. "
                    "Establish hasty defence on PL SURF (airport perimeter). "
                    "B/C COY hold until BDE follow-on forces through."
                ),
                "main_effort":        "A COY 3 PLT — seize OBJ TERMINAL from east",
                "supporting_effort":  "A COY 1 PLT — isolate north perimeter",
                "reserve":            "A COY 2 PLT at east threshold; BPT reinforce 3 PLT or block QRF",
            },
            "tasks_to_subordinate_units": {
                "A_COY": (
                    "MAIN EFFORT. Conduct airborne assault. Seize OBJ TERMINAL "
                    "and OBJ RUNWAY NLT H+45. Protect DZ OSPREY for CASEVAC "
                    "(LZ OSPREY). PRIORITY OF FIRES H-5 to H+45. Mark CLP pad "
                    "RWY 08 threshold on OBJ seizure."
                ),
                "1_PLT": (
                    "SUPPORTING EFFORT. DZ OSPREY. Assembly NLT H+10. Advance south "
                    "to north perimeter, breach north gate. Clear north taxiway area. "
                    "Link up 3 PLT on OBJ TERMINAL NLT H+45. ON ORDER: VCP on N34."
                ),
                "2_PLT": (
                    "RESERVE / BLOCKING. DZ FALCON. Assembly NLT H+10. Advance to "
                    "RWY 26 threshold (east). Secure east gate. BPT block N33 against "
                    "QRF from Brugge. BPT reinforce 3 PLT if OBJ TERMINAL not seized by H+45."
                ),
                "3_PLT": (
                    "MAIN EFFORT. DZ FALCON. Assembly NLT H+10. Advance west on south "
                    "axis. Breach east perimeter fence. Seize OBJ TERMINAL NLT H+45. "
                    "Mark CLP pad on seizure. PRIORITY OF FIRES H-Hour to H+45."
                ),
                "WPNS_PLT": (
                    "DZ OSPREY. Occupy mortar line at 51.207N/2.862E. "
                    "81mm: TRP-001 (tower, H-5), TRP-002 (south apron, H-3), "
                    "TRP-003 (east fence before 3 PLT breach, H+18). "
                    "MMG: overwatch DZ OSPREY; shift to north gate on 1 PLT entry. "
                    "Protect DZ OSPREY for LZ OSPREY (CASEVAC)."
                ),
                "B_COY": (
                    "BLOCKING. Vehicle-mount NLT H-60. Occupy N33 blocking position "
                    "(Oudenburg, 51.184N/3.050E) NLT H-15. Establish VCP + AT ambush. "
                    "Block all traffic from Brugge direction. BPT engage QRF with "
                    "AT4 and direct fire. Report QRF sightings immediately to BN-S3. "
                    "ON ORDER: pursue withdrawing enemy west on N33."
                ),
                "C_COY": (
                    "BLOCKING / DEPTH. Vehicle-mount NLT H-60. Occupy A10/E40 "
                    "blocking position (51.194N/3.160E, W of Brugge) NLT H-15. "
                    "Establish VCP and depth block. Block reinforcements from Ghent "
                    "direction. Coordinate with B COY on N33 to prevent bypass. "
                    "Report all military vehicle movement to BN-S2."
                ),
                "BN_HQ": (
                    "Establish BN TAC CP at DZ OSPREY NLT H+15. BN-6 commands. "
                    "BN-S3 maintains COA tracking. BN-S2 fuses PIR answers. "
                    "BN-FSO coordinates BN fires. BN-JTAC controls WASP 11 if QRF. "
                    "BN-S4 coordinates CASEVAC, CLP logistics plan."
                ),
            },
            "coordinating_instructions": [
                f"H-HOUR: {H_HOUR}.",
                "DZ OSPREY: 51.2120N/2.8622E — A COY (1 PLT/WPNS/HQ), BN HQ.",
                "DZ FALCON: 51.1989N/2.8900E — A COY (2 PLT/3 PLT).",
                "Assembly time at each DZ: NLT H+10.",
                "B/C COY blocking positions occupied NLT H-15 (pre-H-Hour).",
                "PL WAVE: north perimeter fence + east perimeter fence of EBOS.",
                "PL SURF: airport boundary (final consolidation line, LOA for A COY).",
                "PIR: (1) QRF composition / route from Brugge; (2) MANPADS team "
                "location; (3) runway obstructions.",
                "FFIR: KIA/WIA A COY > 8%; any B/C COY blocking position penetrated; "
                "loss of comms > 10 min; MANPADS active; CBRN indicators.",
                "ROE: PID prior to engagement; NO FIRE within 100m of terminal glass "
                "/ fuel farm; civilians at VCP — challenge first.",
                "MOPP: MOPP-0 throughout; MOPP kit in ruck / vehicle.",
                "Recognition: IR strobe on helmet rear; IR VS-17 panel DZ OIC; "
                "vehicle panel on HMMWV rooftop (B/C COY).",
                "CLP approach: RWY 08 (westbound). Threshold marked IR strobes L/R. "
                "CCT controls approach. Expect C-130 × 4 (H+120 to H+180).",
                "CASEVAC: LZ OSPREY (DZ OSPREY secondary) freq 38.250 MHz. "
                "DUSTOFF callsign ANGEL 21.",
                "TRPs: TRP-001=control tower; TRP-002=south apron vehicles; "
                "TRP-003=east fence breach pt; TRP-004=SMOKE north gate.",
            ],
        },
        "sustainment": {
            "logistics": (
                "A COY: jump-loaded 3 days food/water, 600 rds 5.56, 2× AT4. "
                "CCP at DZ OSPREY. Class III/V resupply via first CLP aircraft H+120. "
                "FST on 2nd CLP aircraft. "
                "B/C COY: vehicle load 72hr; ammo re-supply by LOGPAC from BDE H+180."
            ),
            "personnel": (
                "BN AS at Dunkirk (FR) — KIA evac by helo from LZ OSPREY. "
                "DUSTOFF ANGEL 21 on standby H-Hour to H+120. "
                "EPW collection point at DZ OSPREY (RANGER-7)."
            ),
            "medical": (
                "Role 1 BAS at DZ OSPREY (RANGER-7/1SG runs CCP). "
                "CASEVAC LZ: DZ OSPREY, freq 282.800 MHz UHF, callsign ANGEL 21. "
                "Mass casualty plan: CCP DZ OSPREY primary, terminal foyer secondary. "
                "B/C COY: self-aid/buddy-aid; CASEVAC to DZ OSPREY by HMMWV."
            ),
        },
        "command_signal": {
            "command": (
                "BN-6 jumps with A COY HQ at DZ OSPREY. BN TAC CP established NLT H+15 "
                "at DZ OSPREY area. BN-5 (XO) at BN TAC CP. BN-S3 maintains ops log. "
                "Succession: BN CO → BN XO → A COY CO → B COY CO."
            ),
            "command_post_locations": (
                "BN TAC CP: DZ OSPREY (51.213N/2.862E), NLT H+15. "
                "BN MAIN CP: FOB (rear, not deployed). "
                "A COY TAC CP: with 3 PLT on OBJ TERMINAL on seizure. "
                "B COY CP: blocking position N33 (51.184N/3.050E). "
                "C COY CP: blocking position A10/E40 (51.194N/3.160E)."
            ),
            "signal": (
                "PACE: P=SINCGARS BN CMD NET 38.050 MHz fixed; "
                "A=HF voice 5.430 MHz USB; C=Arrow chat #seagull-bn; "
                "E=Pyro (Green star = OBJ SEAGULL seized; Red star = retrograde "
                "to DZ OSPREY). "
                "A COY COY NET: 38.100 MHz. B COY NET: 38.200 MHz. "
                "C COY NET: 38.300 MHz. BN FSE: 38.400 MHz. "
                "CAS net WASP 11: 251.000 MHz. DUSTOFF ANGEL 21: 282.800 MHz. "
                "CCT/CLP approach net: 132.600 MHz. "
                "COMSEC: card MAY-26 ACTIVE."
            ),
        },
    }


# ── Tactical graphics ─────────────────────────────────────────────────────────

def build_graphics() -> list[dict]:
    apt         = LL(*AIRPORT)
    terminal    = apt.offset(+180, -230)
    tower       = apt.offset(+150, -300)
    rwy_08      = apt.offset(   0, -900)
    south_apron = apt.offset(-250, -200)
    east_gate   = apt.offset(   0, +750)
    north_gate  = apt.offset(+550, -100)
    west_gate   = apt.offset(   0, -850)
    dz_osprey   = apt.offset(+1350, +100)
    dz_falcon   = apt.offset(+100,  +1500)
    bn_tac      = LL(*BN_TAC_CP)
    b_block     = LL(*N33_BLOCK)
    c_block     = LL(*E40_BLOCK)

    def tg(type_: str, ll: LL, *, affiliation: str = "FRIENDLY",
           echelon: str = "", notes: str = "", rotation: float = 0.0,
           geometry: str = "", symbol_code: str = "") -> dict:
        return {
            "type": type_, "latitude": ll.lat, "longitude": ll.lon,
            "affiliation": affiliation, "echelon": echelon, "notes": notes,
            "rotation": rotation, "geometry": geometry,
            "symbol_code": symbol_code, "visibility": "COMPANY",
        }

    def line(type_: str, pts: list[LL], **kw) -> dict:
        geom = {"type": "line", "coords": [p.pair() for p in pts]}
        return tg(type_, pts[0], geometry=json.dumps(geom), **kw)

    def poly(type_: str, pts: list[LL], **kw) -> dict:
        geom = {"type": "polygon", "coords": [p.pair() for p in pts]}
        return tg(type_, pts[0], geometry=json.dumps(geom), **kw)

    items: list[dict] = []

    # ── Objectives ────────────────────────────────────────────────────────────
    items.append(poly("OBJ_AREA", [
        terminal.offset(+120, -150), terminal.offset(+120, +250),
        terminal.offset(-100, +250), terminal.offset(-100, -150),
    ], echelon="COY", notes="OBJ TERMINAL — A COY main objective (terminal + tower)"))

    items.append(poly("OBJ_AREA", [
        apt.offset(+60, -900), apt.offset(+60, +900),
        apt.offset(-60, +900), apt.offset(-60, -900),
    ], echelon="BN", notes="OBJ RUNWAY — secure runway 08/26 for CLP air-landing"))

    # ── Drop zones ────────────────────────────────────────────────────────────
    items.append(poly("OBJ_AREA", [
        dz_osprey.offset(+300, -400), dz_osprey.offset(+300, +400),
        dz_osprey.offset(-300, +400), dz_osprey.offset(-300, -400),
    ], echelon="PL", notes="DZ OSPREY — 1 PLT / WPNS PLT / A COY HQ / BN HQ (H-Hour)"))

    items.append(poly("OBJ_AREA", [
        dz_falcon.offset(+350, -350), dz_falcon.offset(+350, +350),
        dz_falcon.offset(-350, +350), dz_falcon.offset(-350, -350),
    ], echelon="PL", notes="DZ FALCON — 2 PLT / 3 PLT (H-Hour, 2nd pass)"))

    # ── Phase lines ───────────────────────────────────────────────────────────
    items.append(line("PHASE_LINE",
                      [apt.offset(+600, -1100), apt.offset(+600, +1100)],
                      echelon="COY",
                      notes="PL WAVE — assemble at DZ; begin movement to airport"))
    items.append(line("PHASE_LINE",
                      [apt.offset(+600, -1100), apt.offset(+600, +1100),
                       apt.offset(+600, +1100), apt.offset(-500, +1100),
                       apt.offset(-500, +1100), apt.offset(-500, -1100),
                       apt.offset(-500, -1100), apt.offset(+600, -1100)],
                      echelon="COY",
                      notes="PL SURF — LOA: airport perimeter (A COY final consolidation)"))

    # ── BN boundaries ────────────────────────────────────────────────────────
    items.append(line("BOUNDARY",
                      [dz_osprey.offset(0, 0), b_block],
                      echelon="BN",
                      notes="BN eastern boundary — A COY (west) / B COY (east of EBOS)"))
    items.append(line("BOUNDARY",
                      [apt.offset(+1400, 0), apt.offset(-200, 0)],
                      echelon="PL",
                      notes="1 PLT / 3 PLT boundary — 1 PLT west, 3 PLT east"))

    # ── Platoon attack axes ───────────────────────────────────────────────────
    items.append(tg("ATK_AXIS", dz_osprey.bearing(180, 600),
                    echelon="PL", rotation=180,
                    notes="1 PLT axis — south from DZ OSPREY to north gate / terminal"))
    items.append(tg("ATK_AXIS", dz_falcon.bearing(270, 800),
                    echelon="PL", rotation=270,
                    notes="3 PLT axis — MAIN EFFORT west from DZ FALCON to OBJ TERMINAL"))
    items.append(tg("ATK_AXIS", dz_falcon.bearing(250, 600),
                    echelon="PL", rotation=250,
                    notes="2 PLT axis — RESERVE east threshold (RWY 26 end + N33 block)"))

    # ── WPNS PLT fire position ────────────────────────────────────────────────
    items.append(tg("DEF_AREA", apt.offset(+620, -100),
                    echelon="PL", rotation=180,
                    notes="WPNS PLT mortar line — 81mm + MMG overwatch from north dunes"))

    # ── B COY blocking position ───────────────────────────────────────────────
    items.append(poly("DEF_AREA", [
        b_block.offset(+300, -500), b_block.offset(+300, +500),
        b_block.offset(-300, +500), b_block.offset(-300, -500),
    ], echelon="COY",
    notes="B COY blocking position — N33 at Oudenburg (blocks Brugge QRF)"))
    items.append(tg("ATK_AXIS", b_block.bearing(270, 800),
                    echelon="COY", rotation=270,
                    notes="B COY vehicle approach — east to N33 blocking position"))

    # ── C COY blocking position ───────────────────────────────────────────────
    items.append(poly("DEF_AREA", [
        c_block.offset(+300, -500), c_block.offset(+300, +500),
        c_block.offset(-300, +500), c_block.offset(-300, -500),
    ], echelon="COY",
    notes="C COY blocking position — A10/E40 west of Brugge (depth block)"))
    items.append(tg("ATK_AXIS", c_block.bearing(270, 1000),
                    echelon="COY", rotation=270,
                    notes="C COY vehicle approach — east to A10/E40 blocking position"))

    # ── FLOT / FLET ──────────────────────────────────────────────────────────
    items.append(line("FLOT",
                      [apt.offset(+600, -1100), apt.offset(+600, +1100)],
                      echelon="BN",
                      notes="FLOT — TF SEAGULL (A COY, after DZ assembly, PL WAVE)"))
    items.append(line("FLET",
                      [apt.offset(+550, -1000), apt.offset(+550, +1000)],
                      affiliation="ENEMY", echelon="BN",
                      notes="FLET — enemy perimeter guard line (estimated)"))

    # ── Enemy positions ───────────────────────────────────────────────────────
    enemies = [
        ("Enemy observer — control tower",      "SHGPUCRVO---", tower),
        ("Enemy motorised rifle platoon (-)",   "SHGPUCIZ----", apt.offset(+100, -50)),
        ("Enemy technical (DShK) #1",           "SHGPEVAT----", south_apron.offset(0, +80)),
        ("Enemy technical (DShK) #2",           "SHGPEVAT----", south_apron.offset(0, -80)),
        ("Enemy MANPADS team (mobile)",          "SHGPUCDS----", apt.offset(+50, +200)),
        ("Enemy perimeter post — west gate",     "SHGPUCIZ----", west_gate),
        ("Enemy perimeter post — east gate",     "SHGPUCIZ----", east_gate),
        ("Enemy perimeter post — south fence",   "SHGPUCIZ----", apt.offset(-500, 0)),
        ("Enemy MMG bunker — north apron",       "SHGPUCFW----", apt.offset(+300, -400)),
        ("Enemy QRF route — N33 (Brugge est.)",  "SHGPUCIZ----", b_block.offset(+200, +800)),
    ]
    for name, sidc, ll in enemies:
        items.append({
            "type": "ENEMY", "symbol_code": sidc,
            "latitude": ll.lat, "longitude": ll.lon,
            "affiliation": "ENEMY", "notes": name,
            "echelon": "", "rotation": 0.0, "geometry": "",
            "visibility": "COMPANY",
        })

    # ── Friendly POIs ────────────────────────────────────────────────────────
    pois = [
        # A COY / BN HQ area
        ("BN TAC CP (DZ OSPREY area)",       "SFGPUH------", bn_tac),
        ("CCP — DZ OSPREY (RANGER-7)",       "SFGPIME-----", dz_osprey.offset(-200, +100)),
        ("BAS / Role 1",                     "SFGPIMS-----", dz_osprey.offset(-200, -200)),
        ("LZ OSPREY (CASEVAC / ANGEL 21)",   "SFGPIBA-----", dz_osprey.offset(+150, 0)),
        ("AMMO point",                       "SFGPIRP-----", dz_osprey.offset(-100, +300)),
        # Objective area
        ("TAC CP (with 3 PLT on OBJ)",       "SFGPUH------", terminal.offset(-50, +100)),
        ("OBJ TERMINAL — HVT",               "SFGPIMG-----", terminal),
        ("Control tower — key terrain",      "SFGPIBE-----", tower),
        ("CLP pad — RWY 08 threshold",       "SFGPIBA-----", rwy_08),
        ("Fuel farm — NO DIRECT FIRE",       "SFGPIMH-----", south_apron.offset(-100, +200)),
        ("North gate — breach point",        "SFGPIBE-----", north_gate),
        ("East gate — 2 PLT block",          "SFGPIBE-----", east_gate),
        # Blocking positions
        ("B COY OP — N33 Oudenburg",         "SFGPUH------", b_block),
        ("C COY OP — A10/E40 W Brugge",      "SFGPUH------", c_block),
        ("Hospital — NO FIRE (Oostende)",    "SFGPIMH-----", LL(51.2108, 2.9067)),
    ]
    for name, sidc, ll in pois:
        items.append({
            "type": "POI", "symbol_code": sidc,
            "latitude": ll.lat, "longitude": ll.lon,
            "affiliation": "FRIENDLY", "notes": name,
            "echelon": "", "rotation": 0.0, "geometry": "",
            "visibility": "COMPANY",
        })

    return items


# ── Fire plan ─────────────────────────────────────────────────────────────────

def build_fire_plan() -> list[dict]:
    apt     = LL(*AIRPORT)
    tower   = apt.offset(+150, -300)
    s_apron = apt.offset(-250, -200)
    e_fence = apt.offset(+100, +700)
    n_gate  = apt.offset(+550, -100)

    return [
        {
            "latitude":     tower.lat,  "longitude":    tower.lon,
            "altitude":     10.0,       "direction":    180.0,
            "mission_type": "SUPPRESSION",  "ammunition": "HE",  "quantity": 6,
            "description":  "FM-001 TRP-001 — suppress enemy observer control tower (H-5 to H+0)",
        },
        {
            "latitude":     s_apron.lat, "longitude":   s_apron.lon,
            "altitude":     5.0,         "direction":   180.0,
            "mission_type": "FIRE_FOR_EFFECT", "ammunition": "HE", "quantity": 12,
            "description":  "FM-002 TRP-002 — destroy enemy technical vehicles south apron (H-3)",
        },
        {
            "latitude":     e_fence.lat, "longitude":   e_fence.lon,
            "altitude":     5.0,         "direction":   270.0,
            "mission_type": "SUPPRESSION", "ammunition": "MIXED", "quantity": 8,
            "description":  "FM-003 TRP-003 — suppress east fence before 3 PLT breach (H+18)",
        },
        {
            "latitude":     n_gate.lat, "longitude":    n_gate.lon,
            "altitude":     5.0,        "direction":    180.0,
            "mission_type": "ADJUST_FIRE", "ammunition": "SMOKE", "quantity": 4,
            "description":  "FM-004 TRP-004 — SMOKE screen north gate for 1 PLT breach (H+15 to H+25)",
        },
    ]


# ── Reports ───────────────────────────────────────────────────────────────────

def submit_reports(api: Api, by_callsign: dict[str, OpRoster]) -> None:
    """File the three battle-phase reports: MEDEVAC, DRONE_SPOT, SPOT."""
    apt     = LL(*AIRPORT)
    e_fence = apt.offset(+100, +700)   # where 3-1 was hit

    # 1. MEDEVAC — 3-1 SL wounded during east fence breach ────────────────────
    r_31 = by_callsign.get("3-1")
    if r_31 and r_31.token:
        lz = LL(*BN_TAC_CP).offset(-200, 0)
        api.post("/reports", r_31.token, {
            "type": "MEDEVAC",
            "payload": {
                "line_1":  "LZ OSPREY — DZ OSPREY (secondary role)",
                "line_2":  "ANGEL 21 — 282.800 MHz UHF",
                "line_3":  "1x URGENT",
                "line_4":  "None (no special equip req)",
                "line_5":  f"{lz.lat:.4f}N {lz.lon:.4f}E",
                "line_6":  "IR strobe (masked from east)",
                "line_7":  "CDAG — no enemy aircraft at LZ",
                "line_8":  "N — 1x LITTER",
                "line_9":  "No CBRN. 1x E (enemy in area east perimeter).",
                "patient":         "3-1 (SL, 3 PLT SQ1)",
                "precedence":      "URGENT",
                "injury":          "GSW left thigh during east fence breach — tourniquet applied T+03",
                "status":          "Unconscious, breathing, pulse present",
                "grid":            f"{e_fence.lat:.4f}N {e_fence.lon:.4f}E (pickup: LZ OSPREY)",
                "blood_type":      "O+",
                "reporting_unit":  "3 PLT / RANGER COY",
                "dtg":             "262123ZMAY26",
            },
        })
        log.info("MEDEVAC report filed by 3-1 (1x URGENT GSW east fence)")

    # 2. DRONE_SPOT — enemy ISR quadcopter over north fence (W-MTR1) ──────────
    w_mtr1 = by_callsign.get("W-MTR1")
    if w_mtr1 and w_mtr1.token:
        drone_pos = apt.offset(+420, +80)
        resp = api.c.post(
            api._p("/reports/drone-spot"),
            json={
                "latitude":      drone_pos.lat,
                "longitude":     drone_pos.lon,
                "drone_type":    "QUADCOPTER",
                "altitude_m":    75.0,
                "direction_deg": 270.0,
                "speed_kts":     12.0,
                "behavior":      "RECONNAISSANCE",
                "notes": (
                    "Small ISR quad, heading west over north fence line. "
                    "Approx 75m AGL. Suspect enemy surveillance of WPNS PLT "
                    "mortar line and DZ OSPREY. W-MTR1 reports at 262108ZMAY26. "
                    "No engagement attempted — MANPADS team status unknown."
                ),
            },
            headers={"Authorization": f"Bearer {w_mtr1.token}"},
        )
        if resp.status_code in (200, 201):
            log.info("DRONE_SPOT filed by W-MTR1 (ISR quad over north fence, hdg 270)")
        else:
            log.warning("DRONE_SPOT failed: %d %s", resp.status_code, resp.text[:120])

    # 3. SPOT/SALUTE — B-1 observes enemy QRF vehicles on N33 ────────────────
    b_1 = by_callsign.get("B-1")
    if b_1 and b_1.token:
        qrf_sighting = LL(*N33_BLOCK).offset(+200, +2500)   # ~2.5 km east of B COY pos
        api.post("/reports", b_1.token, {
            "type": "SPOT",
            "payload": {
                "S": "4x wheeled APC (BTR-80 est.); dismounts unknown",
                "A": "N33, heading west toward Oostende Airport at approx 40 km/h",
                "L": f"{qrf_sighting.lat:.4f}N {qrf_sighting.lon:.4f}E — OP KINGFISHER (B-1)",
                "U": "Motorised rifle QRF, est. Brugge garrison — 30-40 dismounts",
                "T": "262155ZMAY26",
                "E": (
                    "4x BTR-80, lights masked. Lead vehicle mounted HMG. "
                    "ETA B COY blocking position est. 7 min. "
                    "Request immediate CAS (WASP 11) and BN fires TRP-005."
                ),
                "observer":       "B-1 (SL, B COY BPLT-SQ1)",
                "reporting_net":  "B COY NET 38.200 MHz → BN CMD NET 38.050 MHz",
                "dtg":            "262155ZMAY26",
                "grid_observer":  f"{LL(*N33_BLOCK).lat:.4f}N {LL(*N33_BLOCK).lon:.4f}E",
                "grid_target":    f"{qrf_sighting.lat:.4f}N {qrf_sighting.lon:.4f}E",
                "action_taken":   "B COY AT positions manned. B-6 requesting CAS.",
                "latitude":       qrf_sighting.lat,
                "longitude":      qrf_sighting.lon,
            },
        })
        log.info("SPOT report filed by B-1 (4x BTR-80 QRF inbound on N33)")


# ── Movement ──────────────────────────────────────────────────────────────────

def simulate_movement(api: Api, steps: int, dt: float) -> None:
    """Multi-company movement:
    - A COY: two-DZ converging assault on EBOS
    - B COY: vehicle-mount east → N33 blocking position
    - C COY: vehicle-mount east → A10/E40 blocking position
    - BN HQ: holds at BN TAC CP (DZ OSPREY area)
    """
    apt         = LL(*AIRPORT)
    terminal    = apt.offset(+180, -230)
    rwy_26      = apt.offset(0,    +900)
    mortar_line = apt.offset(+620, -100)
    dz_osprey   = apt.offset(+1350, +100)
    dz_falcon   = apt.offset(+100, +1500)
    bn_tac      = LL(*BN_TAC_CP)
    b_end       = LL(*N33_BLOCK)
    c_end       = LL(*E40_BLOCK)
    brugge      = LL(*BRUGGE_AREA)

    plan: dict[str, tuple[LL, LL]] = {}
    for r in ROSTER:
        cs = r.callsign
        sp = (hash(cs) % 11 - 5) * 30
        np = (hash(cs + "n") % 11 - 5) * 25
        ep = (hash(cs + "e") % 7 - 3) * 20
        fp = (hash(cs + "f") % 7 - 3) * 20

        if r.insert == "OSPREY":
            start = dz_osprey.offset(np, sp)
        elif r.insert == "FALCON":
            start = dz_falcon.offset(np, sp)
        elif r.insert == "VEHICLE":
            start = brugge.offset(np * 2, sp * 2)
        else:  # BN_TAC
            start = bn_tac.offset(np // 2, sp // 2)

        if r.insert == "BN_TAC":
            # BN HQ stays at TAC CP
            end = bn_tac.offset(ep // 2, fp // 2)
        elif cs.startswith("1-") or cs in ("RANGER-6", "RANGER-5", "RANGER-7", "RANGER-FO"):
            end = terminal.offset(ep, fp)
        elif cs.startswith("3-"):
            end = terminal.offset(ep, fp)
        elif cs.startswith("2-"):
            end = rwy_26.offset(ep, fp)
        elif cs.startswith("W-"):
            end = mortar_line.offset(ep * 2, fp * 2)
        elif cs.startswith("B-"):
            end = b_end.offset(ep, fp)
        elif cs.startswith("C-"):
            end = c_end.offset(ep, fp)
        else:
            end = terminal

        plan[cs] = (start, end)

    log.info("H-HOUR — BN movement: %d operators / %d steps × %.1fs", len(ROSTER), steps, dt)
    for i in range(steps + 1):
        t = i / steps
        for r in ROSTER:
            start, end = plan[r.callsign]
            here = lerp(start, end, t)
            try:
                api.post("/tracking/position", r.token, {
                    "latitude":  here.lat,
                    "longitude": here.lon,
                    "altitude":  5.0,
                })
            except Exception as exc:
                log.warning("%s: %s", r.callsign, exc)
        if i % 10 == 0:
            log.info("  step %d/%d — t=%.2f", i, steps, t)
        time.sleep(dt)
    log.info("OBJ SEAGULL seized — TF SEAGULL consolidating")


# ── Reset ─────────────────────────────────────────────────────────────────────

def reset_objects(api: Api, admin_tok: str) -> int:
    objs = api.get("/tactical-objects", admin_tok)
    n = 0
    for o in objs:
        if api.delete(f"/tactical-objects/{o['id']}", admin_tok) == 204:
            n += 1
    log.info("reset: deleted %d tactical objects", n)
    return n


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"OPERATION SEAGULL — {BN_NAME} airborne assault on Oostende Airport")
    parser.add_argument("--backend",
                        default=os.environ.get("ARROW_BACKEND_URL", "https://78.21.255.210:6200/api"),
                        help="Backend URL (default: ARROW_BACKEND_URL env, else production)")
    parser.add_argument("--admin",        default="benoit",   help="ADMIN callsign")
    parser.add_argument("--password",     default="ranger14", help="ADMIN password")
    parser.add_argument("--op-password",  default="rangers!", help="Operator password")
    parser.add_argument("--reset",        action="store_true", help="Delete all tactical objects first")
    parser.add_argument("--no-move",      action="store_true", help="Plan-only — skip GPS simulation")
    parser.add_argument("--no-reports",   action="store_true", help="Skip filing MEDEVAC / SPOT / DRONE reports")
    parser.add_argument("--steps",        type=int,   default=80,  help="Movement steps")
    parser.add_argument("--dt",           type=float, default=2.0, help="Seconds between steps")
    parser.add_argument("--mission-name", default="Operation SEAGULL",
                        help="Mission name to create or adopt")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")

    api = Api(args.backend)

    log.info("OPERATION SEAGULL — %s airborne assault on OOSTENDE AIRPORT (EBOS)", BN_NAME)
    log.info("backend=%s  admin=%s", args.backend, args.admin)

    admin_tok = api.login(args.admin, args.password)

    # 1. Mission
    api.create_mission(admin_tok, args.mission_name,
                       description=(
                           f"{BN_NAME} airborne seizure of Oostende Airport (EBOS) "
                           "to enable BDE CLP air-landing. A COY assaults via DZ OSPREY/FALCON; "
                           "B/C COY block QRF routes N33 + A10/E40."
                       ),
                       map_center_lat=AIRPORT[0], map_center_lng=AIRPORT[1], map_zoom=13)
    log.info("mission ready (id=%s)", api.mission_id)

    if args.reset:
        reset_objects(api, admin_tok)

    # 2. Hierarchy
    teams = build_hierarchy(api, admin_tok)

    # 3. Operators
    register_operators(api, admin_tok, teams, args.op_password)
    by_callsign = {r.callsign: r for r in ROSTER}

    # 4. OPORD
    try:
        opord = api.post("/opord", admin_tok, build_opord())
        log.info("OPORD %s posted (id=%s)", opord["opord_number"], opord["id"])
        api.post(f"/opord/{opord['id']}/publish", admin_tok, {})
        api.post(f"/opord/{opord['id']}/send", admin_tok,
                 {"operator_ids": [r.op_id for r in ROSTER]})
        log.info("OPORD published and sent to %d operators", len(ROSTER))
    except Exception as exc:
        log.warning("OPORD skipped: %s", exc)

    # 5. Tactical graphics
    objs = build_graphics()
    posted = 0
    for o in objs:
        try:
            api.post("/tactical-objects", admin_tok, o)
            posted += 1
        except Exception as exc:
            log.warning("TG failed [%s]: %s", o.get("type"), exc)
    log.info("tactical graphics posted: %d/%d items", posted, len(objs))

    # 6. Fire plan
    fm_ok = 0
    for fm in build_fire_plan():
        try:
            api.post("/fire-missions", admin_tok, fm)
            fm_ok += 1
        except Exception as exc:
            log.warning("FM failed: %s", exc)
    log.info("fire plan posted: %d/4 missions", fm_ok)

    # 7. Reports
    if not args.no_reports:
        submit_reports(api, by_callsign)
        log.info("battle reports filed: MEDEVAC + DRONE_SPOT + SPOT")

    # 8. Movement
    if args.no_move:
        log.info("--no-move: plan complete — skipping GPS simulation")
        return
    simulate_movement(api, steps=args.steps, dt=args.dt)


if __name__ == "__main__":
    main()
