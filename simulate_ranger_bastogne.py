#!/usr/bin/env python3
"""
Arrow — Operation NUTS: RANGER COY deliberate attack on Bastogne
================================================================

End-to-end company-level simulator. Stands up everything an operations cell
would need to brief, rehearse and "fight" a single-COY attack on OBJ BASTOGNE
against the live Arrow backend:

  1. Hierarchy  : RANGER COY -> 4 Platoons -> Sections -> Teams
  2. Roster     : ~25 operators registered via /auth/register/admin
  3. OPORD      : Full 5-paragraph OPORD 26-001 (NUTS)
  4. Graphics   : OBJ_AREA polygon, ATK_AXIS arrows per platoon, PL_EAGLE,
                  PL_DAGGER (LOA), boundaries, FLOT/FLET, DEF_AREA / AMBUSH
  5. Enemy      : Defending mech inf, mortar, ATGM, sniper, MANPADS, MMG
  6. POIs       : CCP, BAS, LZ, AMMO, POL, TOC, key bridge, McAuliffe Sq
  7. Fires      : 4 planned fire missions (FFE on mortar/ATGM, SUPPRESS on
                  enemy DEF, SMOKE screen on N flank)
  8. Movement   : H-Hour kick-off — every platoon's callsigns crawl from
                  AA WOLF, through LD, across PL EAGLE, onto OBJ BASTOGNE.

Run:
    uv run python simulate_ranger_bastogne.py
    uv run python simulate_ranger_bastogne.py --backend http://78.21.255.210:6001
    uv run python simulate_ranger_bastogne.py --reset      # wipe TGs first
    uv run python simulate_ranger_bastogne.py --no-move    # plan-only, no GPS sim
    uv run python simulate_ranger_bastogne.py --steps 60 --dt 1.5

Watch in the web map and the Android client — every callsign appears, the
overlay paints, fire missions show up in the side panel, and operators
march west.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger("nuts")

BASTOGNE = (50.0028, 5.7178)   # OBJ centre (McAuliffe Sq vicinity)
ATTACK_BEARING_FROM = 90.0     # enemy faces east; we attack westward
H_HOUR = "191100ZMAY26"


# ── Geometry helpers ─────────────────────────────────────────────────────────

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


# ── HTTP plumbing ────────────────────────────────────────────────────────────

class Api:
    """HTTP client that honours a path prefix on the base URL.

    Pass any of these as ``base_url`` and the leading-slash paths in the
    rest of the script keep working unchanged:
        http://host:6001                  (direct backend)
        http://host:6200/api              (Caddy with /api prefix)
        https://arrow.example/v1          (custom mount)
    """

    def __init__(self, base_url: str) -> None:
        from urllib.parse import urlsplit
        parts = urlsplit(base_url)
        self._prefix = (parts.path or "").rstrip("/")          # "" or "/api"
        origin = f"{parts.scheme}://{parts.netloc}"
        self.c = httpx.Client(base_url=origin, timeout=30.0)

    def _p(self, path: str) -> str:
        """Prepend the path prefix if the request path doesn't already have it."""
        if not self._prefix or path.startswith(self._prefix + "/") or path == self._prefix:
            return path
        return self._prefix + path

    def login(self, callsign: str, password: str) -> str:
        r = self.c.post(self._p("/auth/login"), data={"username": callsign, "password": password})
        if r.status_code != 200:
            sys.exit(f"login failed for {callsign} ({r.status_code}): {r.text}")
        p = r.json()
        if p.get("mfa_required"):
            sys.exit(f"{callsign} has MFA enabled — pick a non-MFA admin")
        return p["access_token"]

    def _hdr(self, tok: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {tok}"}

    def get(self, path: str, tok: str) -> Any:
        r = self.c.get(self._p(path), headers=self._hdr(tok))
        r.raise_for_status()
        return r.json()

    def post(self, path: str, tok: str, body: dict) -> Any:
        r = self.c.post(self._p(path), json=body, headers=self._hdr(tok))
        if r.status_code >= 400:
            log.warning("POST %s -> %d: %s", path, r.status_code, r.text[:200])
            r.raise_for_status()
        return r.json() if r.content else {}

    def delete(self, path: str, tok: str) -> int:
        r = self.c.delete(self._p(path), headers=self._hdr(tok))
        return r.status_code


# ── Org structure & roster ───────────────────────────────────────────────────

@dataclass
class OpRoster:
    callsign: str
    rank: str
    role: str          # OPERATOR | BATTLE_CAPTAIN | ADMIN
    team_name: str     # which Team in hierarchy
    duty: str          # PL, PSG, SQD, FO, ...
    token: str = ""
    op_id: int = 0
    team_id: int = 0

# COY HQ
HQ = "HHC"
# Platoon name → list of (callsign, rank, role, team, duty)
ROSTER: list[OpRoster] = [
    # COY HQ
    OpRoster("RANGER-6",  "OF-3", "BATTLE_CAPTAIN", "HHC-CMD", "CO"),
    OpRoster("RANGER-5",  "OF-2", "BATTLE_CAPTAIN", "HHC-CMD", "XO"),
    OpRoster("RANGER-7",  "OR-8", "OPERATOR",       "HHC-CMD", "1SG"),
    OpRoster("RANGER-FO", "OF-1", "OPERATOR",       "HHC-FIRES", "FO"),
    # 1 PLT — supporting attack (NORTH)
    OpRoster("1-6",   "OF-1", "OPERATOR", "1PLT-HQ",  "PL"),
    OpRoster("1-7",   "OR-7", "OPERATOR", "1PLT-HQ",  "PSG"),
    OpRoster("1-1",   "OR-6", "OPERATOR", "1PLT-SQ1", "SL"),
    OpRoster("1-2",   "OR-6", "OPERATOR", "1PLT-SQ2", "SL"),
    OpRoster("1-3",   "OR-6", "OPERATOR", "1PLT-SQ3", "SL"),
    # 2 PLT — RESERVE (initially holds at AA WOLF, then advances after H+30)
    OpRoster("2-6",   "OF-1", "OPERATOR", "2PLT-HQ",  "PL"),
    OpRoster("2-7",   "OR-7", "OPERATOR", "2PLT-HQ",  "PSG"),
    OpRoster("2-1",   "OR-6", "OPERATOR", "2PLT-SQ1", "SL"),
    OpRoster("2-2",   "OR-6", "OPERATOR", "2PLT-SQ2", "SL"),
    OpRoster("2-3",   "OR-6", "OPERATOR", "2PLT-SQ3", "SL"),
    # 3 PLT — MAIN EFFORT (CENTER)
    OpRoster("3-6",   "OF-1", "OPERATOR", "3PLT-HQ",  "PL"),
    OpRoster("3-7",   "OR-7", "OPERATOR", "3PLT-HQ",  "PSG"),
    OpRoster("3-1",   "OR-6", "OPERATOR", "3PLT-SQ1", "SL"),
    OpRoster("3-2",   "OR-6", "OPERATOR", "3PLT-SQ2", "SL"),
    OpRoster("3-3",   "OR-6", "OPERATOR", "3PLT-SQ3", "SL"),
    # WPNS PLT — SBF / mortars
    OpRoster("W-6",   "OF-1", "OPERATOR", "WPLT-HQ",   "PL"),
    OpRoster("W-MTR1","OR-5", "OPERATOR", "WPLT-MTR",  "Mortar 1"),
    OpRoster("W-MTR2","OR-5", "OPERATOR", "WPLT-MTR",  "Mortar 2"),
    OpRoster("W-MMG1","OR-5", "OPERATOR", "WPLT-MMG",  "MMG 1"),
    OpRoster("W-MMG2","OR-5", "OPERATOR", "WPLT-MMG",  "MMG 2"),
]


# ── Hierarchy: idempotent get-or-create ──────────────────────────────────────

def ensure_company(api: Api, tok: str, name: str) -> int:
    for c in api.get("/companies", tok):
        if c["name"] == name:
            return c["id"]
    return api.post("/companies", tok, {"name": name})["id"]

def ensure_platoon(api: Api, tok: str, name: str, company_id: int) -> int:
    for p in api.get("/platoons", tok):
        if p["name"] == name and p["company_id"] == company_id:
            return p["id"]
    return api.post("/platoons", tok, {"name": name, "company_id": company_id})["id"]

def ensure_section(api: Api, tok: str, name: str, platoon_id: int) -> int:
    for s in api.get("/sections", tok):
        if s["name"] == name and s["platoon_id"] == platoon_id:
            return s["id"]
    return api.post("/sections", tok, {"name": name, "platoon_id": platoon_id})["id"]

def ensure_team(api: Api, tok: str, name: str, section_id: int) -> int:
    for t in api.get("/teams", tok):
        if t["name"] == name and t["section_id"] == section_id:
            return t["id"]
    return api.post("/teams", tok, {"name": name, "section_id": section_id})["id"]


def build_hierarchy(api: Api, admin_tok: str) -> dict[str, int]:
    """Create the COY/PLT/SEC/TEAM tree. Returns {team_name: team_id}."""
    coy_id = ensure_company(api, admin_tok, "RANGER COY")

    plts = {
        "HHC":  ensure_platoon(api, admin_tok, "HHC",  coy_id),
        "1PLT": ensure_platoon(api, admin_tok, "1 PLT", coy_id),
        "2PLT": ensure_platoon(api, admin_tok, "2 PLT", coy_id),
        "3PLT": ensure_platoon(api, admin_tok, "3 PLT", coy_id),
        "WPLT": ensure_platoon(api, admin_tok, "WPNS PLT", coy_id),
    }

    # One section per platoon — keep it flat.
    secs = {p: ensure_section(api, admin_tok, f"{p}-SEC", plts[p]) for p in plts}

    teams_def = [
        # (team_name, parent platoon)
        ("HHC-CMD",   "HHC"),
        ("HHC-FIRES", "HHC"),
        ("1PLT-HQ",   "1PLT"),
        ("1PLT-SQ1",  "1PLT"),
        ("1PLT-SQ2",  "1PLT"),
        ("1PLT-SQ3",  "1PLT"),
        ("2PLT-HQ",   "2PLT"),
        ("2PLT-SQ1",  "2PLT"),
        ("2PLT-SQ2",  "2PLT"),
        ("2PLT-SQ3",  "2PLT"),
        ("3PLT-HQ",   "3PLT"),
        ("3PLT-SQ1",  "3PLT"),
        ("3PLT-SQ2",  "3PLT"),
        ("3PLT-SQ3",  "3PLT"),
        ("WPLT-HQ",   "WPLT"),
        ("WPLT-MTR",  "WPLT"),
        ("WPLT-MMG",  "WPLT"),
    ]
    teams: dict[str, int] = {}
    for name, plt in teams_def:
        teams[name] = ensure_team(api, admin_tok, name, secs[plt])
    log.info("hierarchy ready: %d teams under RANGER COY", len(teams))
    return teams


# ── Operators ────────────────────────────────────────────────────────────────

def register_operators(api: Api, admin_tok: str, teams: dict[str, int],
                       password: str) -> None:
    """Register every callsign in ROSTER via admin-elevated registration.

    Existing callsigns fall back to /auth/login so re-runs of the simulator
    don't fail noisily — we always end up with a valid (callsign, token).
    """
    for r in ROSTER:
        r.team_id = teams[r.team_name]
        body = {
            "callsign": r.callsign,
            "password": password,
            "rank":     r.rank,
            "role":     r.role,
            "team_id":  r.team_id,
        }
        resp = api.c.post(
            api._p("/auth/register/admin"), json=body,
            headers={"Authorization": f"Bearer {admin_tok}"},
        )
        if resp.status_code == 201:
            r.token = resp.json()["access_token"]
        else:
            # Already exists → log in instead. If the password differs the
            # script gives up since we can't recover their token otherwise.
            r.token = api.login(r.callsign, password)

        # Resolve the operator's own id so we can wire it into the OPORD
        # recipient list later.
        me = api.get("/auth/me", r.token)
        r.op_id = me["id"]
    log.info("roster ready: %d operators", len(ROSTER))


# ── OPORD ────────────────────────────────────────────────────────────────────

def build_opord(team_callsigns: dict[str, list[str]]) -> dict:
    """Return a 5-paragraph OPORD as the /opord endpoint expects."""
    return {
        "title":          "OPORD 26-001 — OPERATION NUTS",
        "opord_number":   "26-001",
        "dtg":            H_HOUR,
        "time_zone":      "ZULU",
        "classification": "UNCLASSIFIED // FOUO",
        "references": (
            "(a) Map: NATO 1:50,000 Belgium Sheet 3513 BASTOGNE\n"
            "(b) BN WARNORD 15 dtd 180100ZMAY26\n"
            "(c) BN INTSUM 26-019\n"
            "(d) ROE Card: TF DAGGER ROE-01"
        ),
        "task_organization": (
            "RANGER COY (TF NUTS) — TASK ORGANIZATION\n"
            "  COY HQ — CDR (RANGER-6), XO (RANGER-5), 1SG (RANGER-7), FO (RANGER-FO)\n"
            "  1 PLT — SUPPORTING (1-6 PL, 1-7 PSG, 1-1/2/3 SL)\n"
            "  2 PLT — RESERVE    (2-6 PL, 2-7 PSG, 2-1/2/3 SL)\n"
            "  3 PLT — MAIN EFFORT (3-6 PL, 3-7 PSG, 3-1/2/3 SL)\n"
            "  WPNS PLT — 81mm MORTAR x2 (W-MTR1/2), M240B MMG x2 (W-MMG1/2)\n"
            "  ATTACHMENTS — 1x FO/JTAC ex BN STA Sec (RANGER-FO)\n"
            "  DET — None"
        ),
        "situation": {
            "enemy": (
                "Mechanized infantry company (-), est. 60-80 PAX, dug-in defense of "
                "Bastogne (NW0028/5.7178). Two BMP-2 confirmed vic McAuliffe Sq, "
                "one 120mm mortar at 50.0050N/5.7050E, ATGM team east of N4 "
                "(50.0080N/5.7150E), sniper/observer in the church belltower, "
                "MANPADS team mobile in town centre. Enemy COA-MOST-LIKELY: hold "
                "in current positions, attempt local CT-ATK if penetrated. "
                "COA-MOST-DANGEROUS: armoured QRF ex Houffalize ETA H+90."
            ),
            "friendly": (
                "TF DAGGER (1-75 RGR BN) attacks west to seize OBJs HAWK (us), "
                "EAGLE (B CO, Houffalize), FALCON (C CO, La Roche), KITE "
                "(D CO, Vielsalm). BN main effort = C CO (La Roche). RANGER COY "
                "is BN supporting effort but seizes a critical road junction. "
                "Adjacent: B CO on our N (boundary along 50.04N), D CO further N. "
                "Higher: BDE FSE provides priority of fires to BN MAIN EFFORT; "
                "we receive priority of fires H-5 to H+15 only."
            ),
            "civilian": (
                "Pop. ~3,500 in Bastogne. Hospital at 50.0010N/5.7170E — NO FIRE. "
                "Church / town hall at McAuliffe Sq. Civilians expected on N4 "
                "until H-1. Curfew imposed by Higher H-2."
            ),
            "weather": (
                "BMNT 0517, EENT 2147. Sky overcast 75%, ceiling 1100m. "
                "Wind 240/12 KTS gusting 18. Vis 8km, rain showers AM. "
                "Illum: 38% (waxing). NVG/TI EFFECTIVE all phases."
            ),
            "terrain": (
                "OCOKA (US ARMY ATP 2-01.3):\n"
                "  O — Town building density restricts vehicle maneuver.\n"
                "  C — N4 E-W highway is canalised through OBJ; N84 + N30 jct.\n"
                "  K — McAuliffe Sq (decisive), N4 bridge, hospital (preserve).\n"
                "  O — Wooded ridge north of town affords overwatch.\n"
                "  A — Open fields E/SE of Bastogne support an east-west attack."
            ),
        },
        "mission": (
            "RANGER COY conducts a deliberate attack NLT 191100ZMAY26 to seize "
            "OBJ BASTOGNE (NW0028/5.7178) IOT destroy enemy defending forces "
            "and enable TF DAGGER follow-on operations west along N4."
        ),
        "execution": {
            "commanders_intent": {
                "purpose": (
                    "Defeat enemy mechanized infantry company defending Bastogne "
                    "and seize the N4/N30/N84 junction, denying enemy retrograde "
                    "north and enabling BN exploitation west."
                ),
                "key_tasks": [
                    "Cross LD on H-Hour (191100ZMAY26).",
                    "Seize OBJ BASTOGNE NLT H+90 minutes.",
                    "Secure McAuliffe Square and N4 bridge intact.",
                    "Block enemy reinforcement / withdrawal vic PL DAGGER.",
                    "Preserve hospital and civilian dwellings.",
                ],
                "end_state": (
                    "OBJ BASTOGNE seized; enemy destroyed or withdrawn; "
                    "RANGER COY consolidated on LOA PL DAGGER, oriented W; "
                    "key civilian infrastructure intact; prepared to support "
                    "BN exploitation west on N4."
                ),
            },
            "concept_of_operations": {
                "form_of_maneuver": (
                    "Frontal attack with main effort 3 PLT in the centre, "
                    "supporting effort 1 PLT on the north flank, 2 PLT in "
                    "reserve at AA WOLF, WPNS PLT in SBF position east of AA."
                ),
                "scheme_of_maneuver": (
                    "Phase 1 (H-60 to H-Hour): Movement to LD. COY assembles "
                    "at AA WOLF (50.0028N/5.78E). PLT leaders verify SP times. "
                    "Phase 2 (H-Hour to H+15): Cross LD. WPNS PLT begins "
                    "preparatory fires on enemy DEF AREA + ATGM. 1 PLT and "
                    "3 PLT bound through assault positions to PL EAGLE. "
                    "Phase 3 (H+15 to H+60): Close on OBJ. SMOKE on N flank, "
                    "fires shift west to PL DAGGER. 3 PLT assaults east face, "
                    "1 PLT clears N sector, 2 PLT prepared to reinforce. "
                    "Phase 4 (H+60 to H+90): Consolidate. Establish hasty "
                    "defense on LOA PL DAGGER; CCP active at McAuliffe Sq."
                ),
                "main_effort": "3 PLT — seize OBJ BASTOGNE centre",
                "supporting_effort": "1 PLT — isolate north sector",
                "reserve": "2 PLT at AA WOLF, BPT reinforce 3 PLT or counter from S",
            },
            "tasks_to_subordinate_units": {
                "1_PLT": (
                    "SUPPORTING EFFORT. Cross LD at H-Hour. Advance on NORTH "
                    "axis. Clear north sector of Bastogne (N of 50.005N). "
                    "Isolate town from N30. Establish hasty defense W vic PL "
                    "DAGGER. ON ORDER: pass 2 PLT through."
                ),
                "2_PLT": (
                    "RESERVE. Hold at AA WOLF. BPT reinforce 3 PLT on order. "
                    "BPT counter enemy CT-ATK from south. Maintain comms "
                    "watch on COY NET."
                ),
                "3_PLT": (
                    "MAIN EFFORT. Cross LD H-Hour. Advance on CENTER axis "
                    "along N4. Seize McAuliffe Sq. Clear central sector. "
                    "Establish hasty defense west on PL DAGGER. PRIORITY "
                    "OF FIRES H-Hour to H+30."
                ),
                "WPNS_PLT": (
                    "Establish SBF position at 50.0028N/5.79E (east of AA "
                    "WOLF). 81mm: priority targets ENY MTR (FM-001), ENY "
                    "ATGM (FM-002), DEF AREA (FM-003). MMG: overwatch 1 PLT "
                    "north flank, shift fires on call."
                ),
            },
            "coordinating_instructions": [
                "H-HOUR: 191100ZMAY26.",
                "PIR: (1) ENY mortar disp loc, (2) ENY reserve comp/loc, (3) status W bridges.",
                "FFIR: friendly KIA/WIA > 10%; loss of comms > 15 min; CBRN indicators.",
                "ROE: PID required prior to engagement; civilian infra preserved; no fires within 100m of hospital (50.0010, 5.7170).",
                "MOPP: MOPP-0 at LD; MOPP-1 if CBRN indicators.",
                "Recognition: VS-17 panel orange-side up during daylight; IR strobe night.",
                "PLT boundaries: 1 PLT N of 50.0050N; 3 PLT S of 50.0050N (centre); 2 PLT in reserve.",
                "Phase Lines: PL EAGLE (intermediate), PL DAGGER (LOA, west of OBJ).",
                "TRPs: TRP-001 = ENY mortar; TRP-002 = ENY ATGM; TRP-003 = ENY DEF; TRP-004 = N flank smoke.",
            ],
        },
        "sustainment": {
            "logistics": (
                "COY CCP and Class III/V resupply at AA WOLF. PLT push-packs "
                "carried by SLs. BN LOGPAC at AA WOLF NLT H+60. Push pack "
                "BN-1 (ammo, water, batteries) arrives H+90."
            ),
            "personnel": (
                "BN AS 8 km E. KIA evac via N4 to BN AS. Replacements forward "
                "with BN-1 push pack at H+90."
            ),
            "medical": (
                "Role 1 BAS at AA WOLF. AMB attached to 1 PLT and 3 PLT. "
                "MEDEVAC LZ ALPHA (50.0050, 5.7850). DUSTOFF call: CCP 2-1, "
                "freq 38.250 MHz. Mass casualty: PRIM CCP AA WOLF, SEC CCP "
                "McAuliffe Sq once seized."
            ),
        },
        "command_signal": {
            "command": (
                "CDR (RANGER-6) moves with 3 PLT. XO (RANGER-5) at MAIN CP "
                "(AA WOLF). 1SG (RANGER-7) runs CCP. Succession of command: "
                "CDR -> XO -> 1 PLT PL -> 3 PLT PL."
            ),
            "command_post_locations": (
                "MAIN CP: AA WOLF (50.0028N/5.78E). TAC CP: with 3 PLT. "
                "Jump CP: McAuliffe Sq on seizure."
            ),
            "signal": (
                "PACE: P=SINCGARS COY NET 40.500 MHz fixed; "
                "A=HF voice 5.430 MHz USB; C=Arrow chat #ranger-coy; "
                "E=Pyro (Star cluster: GREEN=success on OBJ, RED=retrograde to AA WOLF). "
                "Cypher: COMSEC card MAY-26 ACTIVE. Brevity matrix Card B."
            ),
        },
    }


# ── Tactical graphics, enemies, POIs ─────────────────────────────────────────

def build_graphics() -> list[dict]:
    centre = LL(*BASTOGNE)
    # Attack heading 270° = bearing toward west; AA is east of OBJ
    attack_heading = (ATTACK_BEARING_FROM + 180.0) % 360.0   # 270
    perp_left  = (attack_heading - 90.0) % 360.0             # 180 (south)
    perp_right = (attack_heading + 90.0) % 360.0             # 0 (north)

    # Friendly anchors
    aa        = centre.bearing(ATTACK_BEARING_FROM, 6500)     # 6.5 km east
    aa_north  = aa.bearing(perp_right, 1200)
    aa_south  = aa.bearing(perp_left,  1200)
    ld_north  = centre.bearing(ATTACK_BEARING_FROM, 4500).bearing(perp_right, 1500)
    ld_south  = centre.bearing(ATTACK_BEARING_FROM, 4500).bearing(perp_left,  1500)
    pl_eagle_n = centre.bearing(ATTACK_BEARING_FROM, 2500).bearing(perp_right, 1500)
    pl_eagle_s = centre.bearing(ATTACK_BEARING_FROM, 2500).bearing(perp_left,  1500)
    pl_dagger_n = centre.bearing(attack_heading, 1500).bearing(perp_right, 1500)
    pl_dagger_s = centre.bearing(attack_heading, 1500).bearing(perp_left,  1500)
    bdy_e      = aa.bearing(perp_left, 0)
    bdy_w      = centre.bearing(attack_heading, 500)

    # OBJ polygon
    obj_poly = [
        centre.offset(  400, -400),
        centre.offset(  400,  400),
        centre.offset( -300,  500),
        centre.offset( -300, -500),
    ]

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

    # OBJ
    items.append(poly("OBJ_AREA", obj_poly, echelon="COY",
                      notes="OBJ BASTOGNE — RANGER COY objective"))

    # Phase lines
    items.append(line("PHASE_LINE", [ld_north, ld_south],
                      echelon="COY", notes="LD — line of departure (H-Hour)"))
    items.append(line("PHASE_LINE", [pl_eagle_n, pl_eagle_s],
                      echelon="COY", notes="PL EAGLE — intermediate phase line"))
    items.append(line("PHASE_LINE", [pl_dagger_n, pl_dagger_s],
                      echelon="COY", notes="PL DAGGER — LOA / limit of advance"))

    # Boundaries (between PLTs at 50.005N)
    items.append(line("BOUNDARY",
                      [LL(50.0050, aa.lon), LL(50.0050, centre.lon - 0.04)],
                      echelon="PL", notes="1 PLT / 3 PLT boundary"))

    # FLOT / FLET
    items.append(line("FLOT", [aa_north, aa_south],
                      echelon="COY", notes="FLOT — TF DAGGER"))
    items.append(line("FLET", [pl_eagle_n.bearing(attack_heading, 800),
                               pl_eagle_s.bearing(attack_heading, 800)],
                      affiliation="ENEMY", echelon="COY",
                      notes="FLET — enemy forward edge"))

    # Friendly axes of advance — three platoons
    axis_offsets = [
        ("1 PLT (NORTH)",   perp_right, 1100, "Supporting effort — N flank"),
        ("3 PLT (CENTER)",  perp_right,    0, "MAIN EFFORT — centre, on N4"),
        ("2 PLT (SOUTH)",   perp_left,  1100, "Reserve / BPT reinforce S flank"),
    ]
    for label, perp, off, note in axis_offsets:
        # Place arrow midway between LD and OBJ at the right cross-track offset
        anchor = centre.bearing(ATTACK_BEARING_FROM, 3000).bearing(perp, off)
        items.append(tg("ATK_AXIS", anchor, echelon="PL", rotation=attack_heading,
                        notes=f"{label} axis — {note}"))

    # WPNS PLT SBF position (east of AA WOLF)
    items.append(tg("DEF_AREA",
                    aa.bearing(ATTACK_BEARING_FROM, 800),
                    echelon="PL", rotation=attack_heading,
                    notes="WPNS PLT SBF — 81mm + M240B overwatch"))

    # Enemy graphics
    items.append(tg("DEF_AREA", centre, affiliation="ENEMY", echelon="COY",
                    rotation=ATTACK_BEARING_FROM,
                    notes="Enemy mech inf COY (-) defends BASTOGNE"))
    items.append(tg("AMBUSH",
                    centre.bearing(ATTACK_BEARING_FROM, 1600).bearing(perp_right, 300),
                    affiliation="ENEMY", echelon="SEC", rotation=attack_heading,
                    notes="Suspected enemy ambush on N4 approach"))
    items.append(tg("AMBUSH",
                    centre.bearing(ATTACK_BEARING_FROM, 1800).bearing(perp_left, 250),
                    affiliation="ENEMY", echelon="TM", rotation=attack_heading,
                    notes="Suspected sniper screen S of N4"))

    # Enemy units (SIDC MIL-STD-2525C hostile)
    enemies = [
        ("Enemy mech inf platoon (-)", "SHGPUCIZ----", centre.offset( 100,  -50)),
        ("Enemy BMP-2 section",        "SHGPUCAA----", centre.offset(  50,  150)),
        ("Enemy 120mm mortar",         "SHGPUCFHE---", centre.offset(  200, -800)),
        ("Enemy ATGM team",            "SHGPUCAA---F", centre.offset(  300, -300)),
        ("Enemy sniper (church)",      "SHGPUCFS----", centre.offset(  -50,  -30)),
        ("Enemy MANPADS team",         "SHGPUCDS----", centre.offset(  -80,   80)),
        ("Enemy MMG bunker",           "SHGPUCFW----", centre.offset(  150, -180)),
        ("Enemy technical w/ DShK",    "SHGPEVAT----", centre.offset(  -200, -200)),
    ]
    for name, sidc, ll in enemies:
        items.append({
            "type": "ENEMY", "symbol_code": sidc,
            "latitude": ll.lat, "longitude": ll.lon,
            "affiliation": "ENEMY",
            "notes": name,
            "echelon": "", "rotation": 0.0, "geometry": "",
            "visibility": "COMPANY",
        })

    # Friendly POIs / OIs (objectives of interest)
    pois = [
        ("CCP — AA WOLF",          "SFGPIME-----", aa),
        ("BAS / Role 1",           "SFGPIMS-----", aa.bearing(perp_left, 300)),
        ("LZ ALPHA (DUSTOFF)",     "SFGPIBA-----", aa.bearing(perp_right, 600)),
        ("AMMO point",             "SFGPIRP-----", aa.bearing(perp_left, 500)),
        ("POL point",              "SFGPIRP-----", aa.bearing(ATTACK_BEARING_FROM, 200)),
        ("MAIN CP / TOC",          "SFGPUH------", aa.bearing(attack_heading, 100)),
        ("N4 bridge (key terrain)", "SFGPIBE-----", centre.bearing(ATTACK_BEARING_FROM, 2800)),
        ("McAuliffe Sq (HVT)",     "SFGPIMG-----", centre),
        ("Hospital — NO FIRE",     "SFGPIMH-----", centre.offset(-150, -100)),
    ]
    for name, sidc, ll in pois:
        items.append({
            "type": "POI", "symbol_code": sidc,
            "latitude": ll.lat, "longitude": ll.lon,
            "affiliation": "FRIENDLY",
            "notes": name,
            "echelon": "", "rotation": 0.0, "geometry": "",
            "visibility": "COMPANY",
        })

    return items


# ── Fire plan ────────────────────────────────────────────────────────────────

def build_fire_plan() -> list[dict]:
    centre = LL(*BASTOGNE)
    return [
        # FM-001 — destroy enemy mortar
        {
            "latitude":  centre.offset(200, -800).lat,
            "longitude": centre.offset(200, -800).lon,
            "altitude":  450.0,
            "direction": 270.0,
            "mission_type": "FIRE_FOR_EFFECT",
            "ammunition":   "HE",
            "quantity":     12,
            "description":  "FM-001 TRP-001 — destroy ENY 120mm mortar (priority target, H-15)",
        },
        # FM-002 — destroy ATGM
        {
            "latitude":  centre.offset(300, -300).lat,
            "longitude": centre.offset(300, -300).lon,
            "altitude":  450.0,
            "direction": 270.0,
            "mission_type": "FIRE_FOR_EFFECT",
            "ammunition":   "HE",
            "quantity":     8,
            "description":  "FM-002 TRP-002 — destroy ENY ATGM team (H-10)",
        },
        # FM-003 — suppress DEF AREA, H-5 to H+0
        {
            "latitude":  centre.lat,
            "longitude": centre.lon,
            "altitude":  450.0,
            "direction": 270.0,
            "mission_type": "SUPPRESSION",
            "ammunition":   "MIXED",
            "quantity":     24,
            "description":  "FM-003 TRP-003 — suppress ENY DEF in BASTOGNE (H-5 to H+0)",
        },
        # FM-004 — SMOKE screen N flank for 1 PLT crossing PL EAGLE
        {
            "latitude":  centre.bearing(ATTACK_BEARING_FROM, 2200).offset(800, 0).lat,
            "longitude": centre.bearing(ATTACK_BEARING_FROM, 2200).offset(800, 0).lon,
            "altitude":  450.0,
            "direction": 270.0,
            "mission_type": "ADJUST_FIRE",
            "ammunition":   "SMOKE",
            "quantity":     6,
            "description":  "FM-004 TRP-004 — SMOKE screen N flank (H-2 to H+10)",
        },
    ]


# ── Movement simulation ─────────────────────────────────────────────────────

def axis_for(callsign: str) -> tuple[str, float]:
    """Map a callsign to (axis label, perpendicular cross-track offset metres
    relative to the COY centre line). Negative = south, positive = north."""
    if callsign.startswith("1-"):  return "1 PLT N", +1100
    if callsign.startswith("3-"):  return "3 PLT C", 0
    if callsign.startswith("2-"):  return "2 PLT S", -1100   # reserve, follows centre
    if callsign.startswith("W-"):  return "WPNS SBF", -200
    # COY HQ — moves with main effort (3 PLT)
    return "COY HQ", -50


def simulate_movement(api: Api, steps: int, dt: float) -> None:
    """For N steps, advance each operator from AA WOLF toward OBJ along their
    axis. WPNS PLT and 2 PLT (reserve) creep slowly — they don't go all the
    way to OBJ. POSTs to /tracking/position using each operator's own token.
    """
    centre = LL(*BASTOGNE)
    attack_heading = (ATTACK_BEARING_FROM + 180.0) % 360.0
    perp_right = (attack_heading + 90.0) % 360.0

    # Build per-operator (start, end) endpoints
    plan: dict[str, tuple[LL, LL]] = {}
    for r in ROSTER:
        axis, cross_off = axis_for(r.callsign)
        start = centre.bearing(ATTACK_BEARING_FROM, 6500).bearing(perp_right, cross_off)
        if r.callsign.startswith(("W-",)):           # SBF — stays back, advances 1.5 km
            end = start.bearing(attack_heading, 1500)
        elif r.callsign.startswith("2-"):            # reserve — moves halfway then halts
            end = start.bearing(attack_heading, 3000)
        else:
            # 1 PLT / 3 PLT / COY HQ → onto OBJ
            end = centre.bearing(perp_right, cross_off).bearing(ATTACK_BEARING_FROM, 100)
        plan[r.callsign] = (start, end)

    log.info("H-HOUR — operators stepping off (%d steps × %.1fs)", steps, dt)
    for i in range(steps + 1):
        t = i / steps
        for r in ROSTER:
            start, end = plan[r.callsign]
            here = lerp(start, end, t)
            # Light jitter so callsigns don't perfectly overlap
            jitter_lat = (hash(r.callsign + str(i)) % 7 - 3) * 1e-5
            jitter_lon = (hash(r.callsign + str(i + 1)) % 7 - 3) * 1e-5
            body = {
                "latitude":  here.lat + jitter_lat,
                "longitude": here.lon + jitter_lon,
                "altitude":  450.0,
            }
            try:
                api.post("/tracking/position", r.token, body)
            except Exception as exc:        # noqa: BLE001
                log.warning("%s position update failed: %s", r.callsign, exc)
        if i % 10 == 0:
            log.info("  step %d/%d — t=%.2f", i, steps, t)
        time.sleep(dt)
    log.info("OBJ reached — RANGER COY consolidates on PL DAGGER")


# ── Reset helper ─────────────────────────────────────────────────────────────

def reset_objects(api: Api, admin_tok: str) -> int:
    """Delete every tactical object so a re-run starts on a clean canvas."""
    objs = api.get("/tactical-objects", admin_tok)
    n = 0
    for o in objs:
        if api.delete(f"/tactical-objects/{o['id']}", admin_tok) == 204:
            n += 1
    log.info("reset: deleted %d tactical objects", n)
    return n


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="OPERATION NUTS — RANGER COY attack on Bastogne")
    # Falls back to ARROW_BACKEND_URL so deployments share the same env var
    # the Flask side uses; explicit --backend always wins.
    parser.add_argument("--backend",
                        default=os.environ.get("ARROW_BACKEND_URL", "http://localhost:6001"),
                        help="Backend base URL. Defaults to ARROW_BACKEND_URL env var, "
                             "then localhost. e.g. http://78.21.255.210:6001")
    parser.add_argument("--admin",    default="benoit", help="ADMIN callsign")
    parser.add_argument("--password", default="ranger14", help="ADMIN password")
    parser.add_argument("--op-password", default="rangers!", help="Password used for every simulated operator")
    parser.add_argument("--reset",    action="store_true",
                        help="Wipe all existing tactical objects before planting")
    parser.add_argument("--no-move",  action="store_true",
                        help="Set up the plan only — skip the movement loop")
    parser.add_argument("--steps",    type=int, default=80, help="Movement steps")
    parser.add_argument("--dt",       type=float, default=2.0, help="Seconds between steps")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    api = Api(args.backend)

    log.info("OPERATION NUTS — RANGER COY attack on BASTOGNE")
    log.info("backend=%s admin=%s", args.backend, args.admin)
    admin_tok = api.login(args.admin, args.password)

    if args.reset:
        reset_objects(api, admin_tok)

    # 1. Hierarchy
    teams = build_hierarchy(api, admin_tok)

    # 2. Operators
    register_operators(api, admin_tok, teams, args.op_password)

    # 3. OPORD
    team_callsigns: dict[str, list[str]] = {}
    for r in ROSTER:
        team_callsigns.setdefault(r.team_name, []).append(r.callsign)
    opord_body = build_opord(team_callsigns)
    opord = api.post("/opord", admin_tok, opord_body)
    log.info("OPORD %s posted: id=%s", opord["opord_number"], opord["id"])
    # Optional: publish + send to every operator so they receive it
    try:
        api.post(f"/opord/{opord['id']}/publish", admin_tok, {})
        api.post(f"/opord/{opord['id']}/send", admin_tok,
                 {"operator_ids": [r.op_id for r in ROSTER]})
        log.info("OPORD published and pushed to %d operators", len(ROSTER))
    except Exception as exc:        # noqa: BLE001
        log.warning("OPORD publish/send skipped: %s", exc)

    # 4. Tactical graphics + enemies + POIs
    objs = build_graphics()
    for o in objs:
        try:
            api.post("/tactical-objects", admin_tok, o)
        except Exception as exc:        # noqa: BLE001
            log.warning("TG post failed for %s: %s", o.get("type"), exc)
    log.info("tactical graphics + enemies + POIs planted: %d items", len(objs))

    # 5. Fire plan
    for fm in build_fire_plan():
        try:
            api.post("/fire-missions", admin_tok, fm)
        except Exception as exc:        # noqa: BLE001
            log.warning("FM post failed: %s", exc)
    log.info("fire plan submitted: 4 missions")

    # 6. Movement
    if args.no_move:
        log.info("plan-only mode: skipping movement loop")
        return
    simulate_movement(api, steps=args.steps, dt=args.dt)


if __name__ == "__main__":
    main()
