#!/usr/bin/env python3
"""
Arrow — Operation SEAGULL: RANGER COY airborne assault on Oostende Airport
==========================================================================

End-to-end company-level simulator. Stands up everything an operations cell
needs to brief, rehearse and "fight" a rapid airborne seizure of Oostende
Airport (EBOS) against the live Arrow backend:

  1. Hierarchy  : RANGER COY → 4 Platoons → Sections → Teams  (identical to NUTS)
  2. Roster     : 25 operators via /auth/register/admin
  3. OPORD      : Full 5-paragraph OPORD 26-002 SEAGULL
  4. Graphics   : DZ OSPREY, DZ FALCON, OBJ TERMINAL, OBJ APRON, phase lines
                  PL WAVE / PL SURF, ATK axes, enemy positions, POIs, CLP pad
  5. Enemy      : Motorised rifle platoon defending airport; technicals,
                  MANPADS, observer in control tower, perimeter posts
  6. POIs       : CCP, BAS, LZ OSPREY (CASEVAC), CLP landing pad, AMMO / POL,
                  TAC CP, control tower (key terrain), terminal (HVT)
  7. Fires      : 4 planned fire missions (suppress tower, destroy vehicles,
                  suppress east perimeter, SMOKE screen on west)
  8. Movement   : Two-DZ converging attack — 1 PLT + COY HQ + WPNS insert
                  via DZ OSPREY (north); 2 PLT + 3 PLT via DZ FALCON (east).
                  Everyone converges on OBJ TERMINAL and the runway.

Run:
    uv run python simulate_oostende_airborne.py
    uv run python simulate_oostende_airborne.py --backend http://78.21.255.210:6200/api
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

AIRPORT      = (51.1989, 2.8622)   # Oostende Airport (EBOS) reference point
H_HOUR       = "262100ZMAY26"      # Night insertion
OP_NAME      = "OPERATION SEAGULL"

# Runway 08/26 at EBOS is essentially E-W; terminal on north side
RWY_HEADING  = 80.0    # magnetic 08 → enemy faces W toward the sea
ATK_BEARING  = 315.0   # attack bearing FROM north/east (converging)


# ── Geometry helpers (identical to bastogne) ─────────────────────────────────

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


# ── Roster (same callsigns as NUTS / Bastogne) ────────────────────────────────

@dataclass
class OpRoster:
    callsign:  str
    rank:      str
    role:      str       # OPERATOR | BATTLE_CAPTAIN | ADMIN
    team_name: str
    duty:      str
    dz:        str       # OSPREY | FALCON
    token:     str = ""
    op_id:     int = 0
    team_id:   int = 0


ROSTER: list[OpRoster] = [
    # COY HQ — insert DZ OSPREY
    OpRoster("RANGER-6",  "OF-3", "BATTLE_CAPTAIN", "HHC-CMD",   "CO",        "OSPREY"),
    OpRoster("RANGER-5",  "OF-2", "BATTLE_CAPTAIN", "HHC-CMD",   "XO",        "OSPREY"),
    OpRoster("RANGER-7",  "OR-8", "OPERATOR",       "HHC-CMD",   "1SG",       "OSPREY"),
    OpRoster("RANGER-FO", "OF-1", "OPERATOR",       "HHC-FIRES", "FO/JTAC",   "OSPREY"),
    # 1 PLT — DZ OSPREY; secures north perimeter + terminal (north face)
    OpRoster("1-6",   "OF-1", "OPERATOR", "1PLT-HQ",  "PL",     "OSPREY"),
    OpRoster("1-7",   "OR-7", "OPERATOR", "1PLT-HQ",  "PSG",    "OSPREY"),
    OpRoster("1-1",   "OR-6", "OPERATOR", "1PLT-SQ1", "SL",     "OSPREY"),
    OpRoster("1-2",   "OR-6", "OPERATOR", "1PLT-SQ2", "SL",     "OSPREY"),
    OpRoster("1-3",   "OR-6", "OPERATOR", "1PLT-SQ3", "SL",     "OSPREY"),
    # 2 PLT — DZ FALCON; RESERVE, secures east runway threshold (RWY 26 end)
    OpRoster("2-6",   "OF-1", "OPERATOR", "2PLT-HQ",  "PL",     "FALCON"),
    OpRoster("2-7",   "OR-7", "OPERATOR", "2PLT-HQ",  "PSG",    "FALCON"),
    OpRoster("2-1",   "OR-6", "OPERATOR", "2PLT-SQ1", "SL",     "FALCON"),
    OpRoster("2-2",   "OR-6", "OPERATOR", "2PLT-SQ2", "SL",     "FALCON"),
    OpRoster("2-3",   "OR-6", "OPERATOR", "2PLT-SQ3", "SL",     "FALCON"),
    # 3 PLT — DZ FALCON; MAIN EFFORT, seizes terminal building from east
    OpRoster("3-6",   "OF-1", "OPERATOR", "3PLT-HQ",  "PL",     "FALCON"),
    OpRoster("3-7",   "OR-7", "OPERATOR", "3PLT-HQ",  "PSG",    "FALCON"),
    OpRoster("3-1",   "OR-6", "OPERATOR", "3PLT-SQ1", "SL",     "FALCON"),
    OpRoster("3-2",   "OR-6", "OPERATOR", "3PLT-SQ2", "SL",     "FALCON"),
    OpRoster("3-3",   "OR-6", "OPERATOR", "3PLT-SQ3", "SL",     "FALCON"),
    # WPNS PLT — DZ OSPREY; establishes mortar line N of airport + MMG overwatch
    OpRoster("W-6",    "OF-1", "OPERATOR", "WPLT-HQ",  "PL",      "OSPREY"),
    OpRoster("W-MTR1", "OR-5", "OPERATOR", "WPLT-MTR", "Mortar 1","OSPREY"),
    OpRoster("W-MTR2", "OR-5", "OPERATOR", "WPLT-MTR", "Mortar 2","OSPREY"),
    OpRoster("W-MMG1", "OR-5", "OPERATOR", "WPLT-MMG", "MMG 1",   "OSPREY"),
    OpRoster("W-MMG2", "OR-5", "OPERATOR", "WPLT-MMG", "MMG 2",   "OSPREY"),
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
    coy_id = ensure_company(api, admin_tok, "RANGER COY")
    plts = {
        "HHC":  ensure_platoon(api, admin_tok, "HHC",      coy_id),
        "1PLT": ensure_platoon(api, admin_tok, "1 PLT",    coy_id),
        "2PLT": ensure_platoon(api, admin_tok, "2 PLT",    coy_id),
        "3PLT": ensure_platoon(api, admin_tok, "3 PLT",    coy_id),
        "WPLT": ensure_platoon(api, admin_tok, "WPNS PLT", coy_id),
    }
    secs = {p: ensure_section(api, admin_tok, f"{p}-SEC", plts[p]) for p in plts}
    teams_def = [
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


# ── Operators ─────────────────────────────────────────────────────────────────

def register_operators(api: Api, admin_tok: str, teams: dict[str, int],
                       password: str) -> None:
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
            "(b) BN WARNORD 08 dtd 251700ZMAY26\n"
            "(c) BN INTSUM 26-025 — airport garrison est. 30-40 PAX\n"
            "(d) EBOS Aerodrome Chart (mil edition) AIP EBOS-AD-2\n"
            "(e) ROE Card: TF DAGGER ROE-01"
        ),
        "task_organization": (
            "RANGER COY (TF SEAGULL) — TASK ORGANIZATION\n"
            "  COY HQ — CDR (RANGER-6), XO (RANGER-5), 1SG (RANGER-7), "
            "FO/JTAC (RANGER-FO)\n"
            "  1 PLT — SUPPORTING  — DZ OSPREY (NORTH)\n"
            "           (1-6 PL, 1-7 PSG, 1-1/2/3 SL)\n"
            "  2 PLT — RESERVE     — DZ FALCON (EAST)\n"
            "           (2-6 PL, 2-7 PSG, 2-1/2/3 SL)\n"
            "  3 PLT — MAIN EFFORT — DZ FALCON (EAST)\n"
            "           (3-6 PL, 3-7 PSG, 3-1/2/3 SL)\n"
            "  WPNS PLT — 81mm MORTAR ×2 (W-MTR1/2), M240B MMG ×2 "
            "(W-MMG1/2) — DZ OSPREY\n"
            "  ATTACHMENTS — 1× FO/JTAC ex BN STA (RANGER-FO); "
            "CAS on-call (2× F/A-18E, loiter 30 min)\n"
            "  DET — Combat Controller Team (CCT) embeds with RANGER-FO "
            "for CLP approach control"
        ),
        "situation": {
            "enemy": (
                "Motorised rifle platoon (-), est. 30-40 PAX, occupying "
                "Oostende Airport (EBOS) as a forward logistics node. "
                "Two technical vehicles (DShK-mounted) on south apron "
                "(51.1975N/2.862E). One MANPADS team mobile, last seen "
                "vic control tower. Three perimeter guard posts at west "
                "fence (51.199N/2.843E), south fence, and east gate. "
                "Observer with optics in control tower (51.200N/2.858E). "
                "Enemy COA-MOST-LIKELY: delay on perimeter, withdraw "
                "toward N33 if airfield compromised. "
                "COA-MOST-DANGEROUS: reinforced by QRF from Brugge (ETA H+60)."
            ),
            "friendly": (
                "TF DAGGER (1-75 RGR BN) conducts simultaneous raids along "
                "the Belgian coast. RANGER COY is BN main effort — seized "
                "airport enables CLP air landing of follow-on battalion "
                "equipment (H+120). B CO secures N33 to east; C CO "
                "blocks A10/E40 west of Brugge to prevent QRF. "
                "CAS available: 2× F/A-18E (callsign WASP 11) loiter vic "
                "51.30N/3.00E, armed with JDAM and Mk-82."
            ),
            "civilian": (
                "Civilian airfield — EBOS active 0600-2200L. Night insertion "
                "minimises civilian presence. Airport staff estimated 5-10 "
                "in terminal at H-Hour (security personnel). "
                "Fire control measures: NO FIRE within 100m of terminal "
                "glass facade (civilian / structural damage). Fuel farm "
                "at south apron — avoid direct fire to prevent secondary."
            ),
            "weather": (
                "BMNT 0516Z, EENT 2148Z. H-Hour 2100Z = 47 min before "
                "EENT. Partly cloudy 40%, ceiling 2400m. "
                "Wind 270/08 KTS (westerly off North Sea). Vis 12km. "
                "No precipitation. Sea state 2 (Beaufort). "
                "NVG conditions: GOOD. Moon illumination: 12% (new moon "
                "in 3 days) — near-total darkness favours assault."
            ),
            "terrain": (
                "OCOKA:\n"
                "  O — Open runway environment, no cover within 300m of "
                "runway 08/26 centre-line.\n"
                "  C — Perimeter fence canalises dismounted approach; "
                "three entry gates (N, E, S) are key nodes.\n"
                "  K — Control tower (obs), terminal building (key "
                "terrain), fuel farm (avoid), CLP pad (RWY 08 threshold).\n"
                "  O — Dunes 800m north offer covered DZ and mortar "
                "line; harbour mouth 1.5 km west.\n"
                "  A — Open ground east of airport supports DZ FALCON "
                "and 3 PLT/2 PLT approach."
            ),
        },
        "mission": (
            "RANGER COY conducts an airborne assault NLT 262100ZMAY26 to "
            "seize and hold Oostende Airport (OBJ SEAGULL, 51.1989N/2.8622E) "
            "IOT destroy/capture enemy garrison and enable CLP air-landing of "
            "TF DAGGER follow-on forces NLT H+120."
        ),
        "execution": {
            "commanders_intent": {
                "purpose": (
                    "Rapidly seize EBOS airport intact, eliminating the "
                    "enemy garrison and securing the runway for immediate "
                    "follow-on air-landing operations by BN main body."
                ),
                "key_tasks": [
                    "Insert via DZ OSPREY (1 PLT/WPNS/HQ) and DZ FALCON "
                    "(2 PLT/3 PLT) NLT H-Hour 262100ZMAY26.",
                    "Suppress enemy control tower and south apron technicals "
                    "with WPNS PLT before 3 PLT assault.",
                    "3 PLT seizes OBJ TERMINAL NLT H+45.",
                    "1 PLT clears north perimeter and secures north gate NLT H+30.",
                    "2 PLT secures RWY 26 threshold (east) and blocks N33 entry.",
                    "Runway clear of obstacles and CLP pad marked NLT H+90.",
                    "Preserve terminal structure and fuel farm.",
                ],
                "end_state": (
                    "OBJ SEAGULL seized; enemy destroyed or captured; "
                    "RANGER COY consolidated on PL SURF (airport perimeter); "
                    "runway 08/26 clear; CLP pad lit and marked for C-130 "
                    "approach; airport infrastructure intact."
                ),
            },
            "concept_of_operations": {
                "form_of_maneuver": (
                    "Converging airborne assault from two DZs with simultaneous "
                    "north and east attacks. WPNS PLT provides preparatory and "
                    "on-call fires from north dune line."
                ),
                "scheme_of_maneuver": (
                    "Phase 1 — Insertion (H-60 to H-Hour): C-130 drops 1 PLT, "
                    "WPNS PLT and COY HQ at DZ OSPREY (dunes north of airport). "
                    "2nd pass drops 2 PLT and 3 PLT at DZ FALCON (open fields "
                    "east of airport). Assembly NLT H+10 each DZ.\n"
                    "Phase 2 — Isolation (H-Hour to H+20): WPNS PLT occupies "
                    "mortar line at north fence. Engages TRP-001 (tower) and "
                    "TRP-002 (south apron vehicles). MMG overwatches north gate. "
                    "1 PLT clears north perimeter and breaches north fence.\n"
                    "Phase 3 — Assault (H+20 to H+60): 3 PLT (MAIN EFFORT) "
                    "breaches east fence, advances west, seizes OBJ TERMINAL. "
                    "2 PLT peels south, secures east runway threshold and east "
                    "gate — BPT block QRF from N33. 1 PLT sweeps runway 08 "
                    "threshold area, links up with COY HQ.\n"
                    "Phase 4 — Consolidate (H+60 to H+120): Clear terminal "
                    "methodically. CCP active at DZ OSPREY. Mark CLP pad. "
                    "RANGER-FO coordinates CAS for QRF if required.\n"
                    "Phase 5 — CLP (H+120): Guide first C-130 onto runway 08. "
                    "Establish hasty defence on PL SURF (airport perimeter)."
                ),
                "main_effort":      "3 PLT — seize OBJ TERMINAL from east",
                "supporting_effort":"1 PLT — isolate north perimeter, cross-attack toward terminal",
                "reserve":          "2 PLT at east threshold; BPT reinforce 3 PLT or block QRF",
            },
            "tasks_to_subordinate_units": {
                "1_PLT": (
                    "SUPPORTING EFFORT. Insert DZ OSPREY H-Hour. Assemble NLT "
                    "H+10. Advance south to north perimeter fence. Breach via "
                    "north gate or assault breach. Clear north taxiway area. "
                    "Link up with 3 PLT on OBJ TERMINAL NLT H+45. ON ORDER: "
                    "establish vehicle checkpoint on N34 (north access road)."
                ),
                "2_PLT": (
                    "RESERVE / BLOCKING. Insert DZ FALCON H-Hour. Assemble "
                    "NLT H+10. Advance to RWY 26 threshold (east). Secure east "
                    "gate. BPT block N33 against QRF from Brugge. BPT reinforce "
                    "3 PLT if OBJ TERMINAL not seized by H+45."
                ),
                "3_PLT": (
                    "MAIN EFFORT. Insert DZ FALCON H-Hour. Assemble NLT H+10. "
                    "Advance west on south axis. Breach east perimeter fence. "
                    "Seize OBJ TERMINAL (clear terminal building, control tower, "
                    "south apron) NLT H+45. PRIORITY OF FIRES H-Hour to H+45. "
                    "Mark CLP pad at RWY 08 threshold on seizure."
                ),
                "WPNS_PLT": (
                    "Insert DZ OSPREY H-Hour. Occupy mortar line at 51.2070N/"
                    "2.862E (north fence line). 81mm: TRP-001 (control tower), "
                    "TRP-002 (south apron vehicles), TRP-003 (east fence before "
                    "3 PLT breach). MMG: overwatch DZ OSPREY approach lane; "
                    "shift to north gate on 1 PLT entry. Protect DZ OSPREY for "
                    "CASEVAC (LZ OSPREY)."
                ),
            },
            "coordinating_instructions": [
                f"H-HOUR: {H_HOUR}.",
                "DZ OSPREY: 51.2120N/2.8622E — 1 PLT, WPNS PLT, COY HQ.",
                "DZ FALCON: 51.1989N/2.8900E — 2 PLT, 3 PLT.",
                "Assembly time at each DZ: NLT H+10.",
                "PL WAVE: intermediate phase line, north perimeter fence + east fence.",
                "PL SURF: final LOA, airport boundary (perimeter fence / fence road).",
                "PIR: (1) QRF composition/route from Brugge; (2) MANPADS team "
                "location; (3) runway obstructions.",
                "FFIR: KIA/WIA > 8%; loss of comms > 10 min; MANPADS active.",
                "ROE: PID prior to engagement; NO FIRE within 100m of terminal "
                "glass / fuel farm; civilians in terminal — challenge first.",
                "MOPP: MOPP-0 throughout (no CBRN indicators); MOPP kit in ruck.",
                "Recognition: IR strobe on helmet rear; IR VS-17 panel DZ OIC.",
                "CLP approach: runway 08 (westbound landing). Threshold marked "
                "by IR strobes L/R. CCT controls approach. Expect C-130 × 4.",
                "CASEVAC: LZ OSPREY (DZ OSPREY secondary role) freq 38.250 MHz.",
                "TRPs: TRP-001 = control tower; TRP-002 = south apron vehicles; "
                "TRP-003 = east fence breach pt; TRP-004 = SMOKE north gate.",
            ],
        },
        "sustainment": {
            "logistics": (
                "All operators jump-loaded: 3 days food/water, 600 rds 5.56, "
                "2× AT4. COY CCP at DZ OSPREY. Class III/V resupply via first "
                "CLP aircraft (H+120). Forward surgical team on 2nd CLP aircraft."
            ),
            "personnel": (
                "BN AS at Dunkirk (FR) — KIA evac by helo from LZ OSPREY. "
                "DUSTOFF on standby throughout H-Hour to H+120."
            ),
            "medical": (
                "Role 1 BAS at DZ OSPREY (1SG RANGER-7 runs CCP). "
                "CASEVAC LZ: DZ OSPREY (secondary role after 1 PLT clear). "
                "DUSTOFF callsign ANGEL 21 on freq 282.800 MHz (UHF). "
                "Mass casualty: CCP DZ OSPREY primary, terminal foyer secondary."
            ),
        },
        "command_signal": {
            "command": (
                "CDR (RANGER-6) jumps with COY HQ at DZ OSPREY, links with "
                "3 PLT at PL WAVE. XO (RANGER-5) at DZ OSPREY until H+20, "
                "then forward to terminal on seizure. 1SG (RANGER-7) runs "
                "CCP at DZ OSPREY throughout. Succession: CDR → XO → "
                "1 PLT PL → 3 PLT PL."
            ),
            "command_post_locations": (
                "TAC CP: with 3 PLT (OBJ TERMINAL on seizure). "
                "MAIN CP: DZ OSPREY (XO until H+20). "
                "Jump CP: control tower foyer once cleared."
            ),
            "signal": (
                "PACE: P=SINCGARS COY NET 38.100 MHz fixed; "
                "A=HF voice 5.430 MHz USB; C=Arrow chat #seagull-coy; "
                "E=Pyro (Green star = terminal seized; Red star = retrograde "
                "to DZ OSPREY). CAS net: WASP 11 on 251.000 MHz. "
                "CCT-CLP approach net: 132.600 MHz. "
                "COMSEC: card MAY-26 ACTIVE (same as NUTS)."
            ),
        },
    }


# ── Tactical graphics ─────────────────────────────────────────────────────────

def build_graphics() -> list[dict]:
    apt   = LL(*AIRPORT)     # airport reference

    # Key geometry
    terminal    = apt.offset(+180, -230)    # terminal building (NW of centre)
    tower       = apt.offset(+150, -300)    # control tower (west side)
    rwy_08      = apt.offset(   0, -900)    # RWY 08 threshold (west)
    rwy_26      = apt.offset(   0, +900)    # RWY 26 threshold (east)
    south_apron = apt.offset(-250, -200)    # south apron / fuel farm area
    east_gate   = apt.offset(   0, +750)    # east perimeter gate
    north_gate  = apt.offset(+550, -100)    # north gate
    west_gate   = apt.offset(   0, -850)    # west gate

    # Drop zones
    dz_osprey_c = apt.offset(+1350, +100)   # DZ OSPREY centre (north, in dunes)
    dz_falcon_c = apt.offset(+100,  +1500)  # DZ FALCON centre (east, open fields)

    # Phase lines
    pl_wave_n   = apt.offset(+600, -1100)   # PL WAVE north anchor
    pl_wave_s   = apt.offset(+600, +1100)   # (north perimeter fence line)
    pl_surf_nw  = apt.offset(+600, -1100)   # PL SURF = airport perimeter
    pl_surf_ne  = apt.offset(+600, +1100)
    pl_surf_se  = apt.offset(-500, +1100)
    pl_surf_sw  = apt.offset(-500, -1100)

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
    terminal_poly = [
        terminal.offset(+120, -150),
        terminal.offset(+120, +250),
        terminal.offset(-100, +250),
        terminal.offset(-100, -150),
    ]
    items.append(poly("OBJ_AREA", terminal_poly, echelon="COY",
                      notes="OBJ TERMINAL — RANGER COY main objective (terminal + tower)"))

    runway_poly = [
        apt.offset(+60, -900),
        apt.offset(+60, +900),
        apt.offset(-60, +900),
        apt.offset(-60, -900),
    ]
    items.append(poly("OBJ_AREA", runway_poly, echelon="PL",
                      notes="OBJ RUNWAY — secure runway 08/26 for CLP air-landing"))

    # ── Drop zones ────────────────────────────────────────────────────────────
    dz_osp_poly = [
        dz_osprey_c.offset(+300, -400),
        dz_osprey_c.offset(+300, +400),
        dz_osprey_c.offset(-300, +400),
        dz_osprey_c.offset(-300, -400),
    ]
    items.append(poly("OBJ_AREA", dz_osp_poly, echelon="PL",
                      notes="DZ OSPREY — 1 PLT / WPNS PLT / COY HQ (H-Hour insertion)"))

    dz_fal_poly = [
        dz_falcon_c.offset(+350, -350),
        dz_falcon_c.offset(+350, +350),
        dz_falcon_c.offset(-350, +350),
        dz_falcon_c.offset(-350, -350),
    ]
    items.append(poly("OBJ_AREA", dz_fal_poly, echelon="PL",
                      notes="DZ FALCON — 2 PLT / 3 PLT (H-Hour insertion, 2nd pass)"))

    # ── Phase lines ───────────────────────────────────────────────────────────
    items.append(line("PHASE_LINE", [pl_wave_n, pl_wave_s],
                      echelon="COY",
                      notes="PL WAVE — assemble at DZ; begin movement to airport"))
    items.append(line("PHASE_LINE",
                      [pl_surf_nw, pl_surf_ne, pl_surf_se, pl_surf_sw, pl_surf_nw],
                      echelon="COY",
                      notes="PL SURF — LOA: airport perimeter (final consolidation line)"))

    # ── Platoon attack axes ───────────────────────────────────────────────────
    # 1 PLT: DZ OSPREY (north) → terminal (from north)
    items.append(tg("ATK_AXIS",
                    LL(dz_osprey_c.lat, dz_osprey_c.lon).bearing(180, 600),
                    echelon="PL", rotation=180,
                    notes="1 PLT axis — south from DZ OSPREY to north gate / terminal"))
    # 3 PLT: DZ FALCON (east) → terminal (from east, westbound = 270°)
    items.append(tg("ATK_AXIS",
                    LL(dz_falcon_c.lat, dz_falcon_c.lon).bearing(270, 800),
                    echelon="PL", rotation=270,
                    notes="3 PLT axis — MAIN EFFORT west from DZ FALCON to OBJ TERMINAL"))
    # 2 PLT: DZ FALCON → east threshold (holds short = reserve)
    items.append(tg("ATK_AXIS",
                    dz_falcon_c.bearing(250, 600),
                    echelon="PL", rotation=250,
                    notes="2 PLT axis — RESERVE / east threshold (RWY 26 end + N33 block)"))

    # ── WPNS PLT fire position ────────────────────────────────────────────────
    items.append(tg("DEF_AREA",
                    apt.offset(+620, -100),
                    echelon="PL", rotation=180,
                    notes="WPNS PLT mortar line — 81mm + MMG overwatch from north dunes"))

    # ── Boundaries ───────────────────────────────────────────────────────────
    items.append(line("BOUNDARY",
                      [apt.offset(+1400, +0), apt.offset(-200, +0)],
                      echelon="PL",
                      notes="1 PLT / 3 PLT boundary — 1 PLT west of line, 3 PLT east"))

    # ── FLOT / FLET ──────────────────────────────────────────────────────────
    items.append(line("FLOT",
                      [apt.offset(+600, -1100), apt.offset(+600, +1100)],
                      echelon="COY",
                      notes="FLOT — RANGER COY (after DZ assembly, PL WAVE)"))
    items.append(line("FLET",
                      [apt.offset(+550, -1000), apt.offset(+550, +1000)],
                      affiliation="ENEMY", echelon="COY",
                      notes="FLET — enemy perimeter guard line (estimated)"))

    # ── Enemy positions ───────────────────────────────────────────────────────
    enemies = [
        ("Enemy observer — control tower",    "SHGPUCRVO---", tower),
        ("Enemy motorised rifle plt (-)",     "SHGPUCIZ----", apt.offset(+100, -50)),
        ("Enemy technical (DShK) #1",         "SHGPEVAT----", south_apron.offset(0, +80)),
        ("Enemy technical (DShK) #2",         "SHGPEVAT----", south_apron.offset(0, -80)),
        ("Enemy MANPADS team (mobile)",        "SHGPUCDS----", apt.offset(+50, +200)),
        ("Enemy perimeter post — west gate",   "SHGPUCIZ----", west_gate),
        ("Enemy perimeter post — east gate",   "SHGPUCIZ----", east_gate),
        ("Enemy perimeter post — south fence", "SHGPUCIZ----", apt.offset(-500, 0)),
        ("Enemy MMG bunker — north apron",     "SHGPUCFW----", apt.offset(+300, -400)),
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

    # ── Friendly POIs ────────────────────────────────────────────────────────
    pois = [
        ("CCP — DZ OSPREY",              "SFGPIME-----", dz_osprey_c.offset(-200, +100)),
        ("BAS / Role 1",                 "SFGPIMS-----", dz_osprey_c.offset(-200, -200)),
        ("LZ OSPREY (CASEVAC/DUSTOFF)",  "SFGPIBA-----", dz_osprey_c.offset(+150,   0)),
        ("AMMO point",                   "SFGPIRP-----", dz_osprey_c.offset(-100, +300)),
        ("TAC CP (with 3 PLT on OBJ)",   "SFGPUH------", terminal.offset(-50, +100)),
        ("OBJ TERMINAL — HVT",           "SFGPIMG-----", terminal),
        ("Control tower — key terrain",  "SFGPIBE-----", tower),
        ("CLP pad — RWY 08 threshold",   "SFGPIBA-----", rwy_08),
        ("Fuel farm — NO DIRECT FIRE",   "SFGPIMH-----", south_apron.offset(-100, +200)),
        ("North gate — breach point",    "SFGPIBE-----", north_gate),
        ("East gate — 2 PLT block",      "SFGPIBE-----", east_gate),
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


# ── Fire plan ─────────────────────────────────────────────────────────────────

def build_fire_plan() -> list[dict]:
    apt      = LL(*AIRPORT)
    tower    = apt.offset(+150, -300)
    s_apron  = apt.offset(-250, -200)
    e_fence  = apt.offset(+100, +700)
    n_gate   = apt.offset(+550, -100)

    return [
        {
            "latitude":     tower.lat,
            "longitude":    tower.lon,
            "altitude":     10.0,
            "direction":    180.0,
            "mission_type": "SUPPRESSION",
            "ammunition":   "HE",
            "quantity":     6,
            "description":  "FM-001 TRP-001 — suppress enemy observer control tower (H-5 to H+0)",
        },
        {
            "latitude":     s_apron.lat,
            "longitude":    s_apron.lon,
            "altitude":     5.0,
            "direction":    180.0,
            "mission_type": "FIRE_FOR_EFFECT",
            "ammunition":   "HE",
            "quantity":     12,
            "description":  "FM-002 TRP-002 — destroy enemy technical vehicles south apron (H-3)",
        },
        {
            "latitude":     e_fence.lat,
            "longitude":    e_fence.lon,
            "altitude":     5.0,
            "direction":    270.0,
            "mission_type": "SUPPRESSION",
            "ammunition":   "MIXED",
            "quantity":     8,
            "description":  "FM-003 TRP-003 — suppress east fence perimeter before 3 PLT breach (H+18)",
        },
        {
            "latitude":     n_gate.lat,
            "longitude":    n_gate.lon,
            "altitude":     5.0,
            "direction":    180.0,
            "mission_type": "ADJUST_FIRE",
            "ammunition":   "SMOKE",
            "quantity":     4,
            "description":  "FM-004 TRP-004 — SMOKE screen north gate for 1 PLT breach (H+15 to H+25)",
        },
    ]


# ── Movement ──────────────────────────────────────────────────────────────────

def simulate_movement(api: Api, steps: int, dt: float) -> None:
    """Converging assault: DZ OSPREY (north) and DZ FALCON (east) close on airport."""
    apt         = LL(*AIRPORT)
    terminal    = apt.offset(+180, -230)
    tower       = apt.offset(+150, -300)
    rwy_26      = apt.offset(0,    +900)
    mortar_line = apt.offset(+620, -100)
    dz_osprey   = apt.offset(+1350, +100)
    dz_falcon   = apt.offset(+100, +1500)

    # Per-callsign (start, end) with spread so operators don't stack
    plan: dict[str, tuple[LL, LL]] = {}
    for r in ROSTER:
        cs = r.callsign
        if r.dz == "OSPREY":
            # Spread across DZ OSPREY
            spread = (hash(cs) % 11 - 5) * 30
            start  = dz_osprey.offset(
                (hash(cs + "n") % 11 - 5) * 25,
                spread,
            )
        else:
            spread = (hash(cs) % 11 - 5) * 30
            start  = dz_falcon.offset(
                (hash(cs + "n") % 11 - 5) * 25,
                spread,
            )

        if cs.startswith("1-") or cs in ("RANGER-6", "RANGER-5", "RANGER-7", "RANGER-FO"):
            # 1 PLT and COY HQ → terminal/tower from north
            end = terminal.offset(
                (hash(cs + "e") % 7 - 3) * 20,
                (hash(cs + "f") % 7 - 3) * 20,
            )
        elif cs.startswith("3-"):
            # 3 PLT MAIN EFFORT → terminal from east
            end = terminal.offset(
                (hash(cs + "e") % 7 - 3) * 20,
                (hash(cs + "f") % 7 - 3) * 20,
            )
        elif cs.startswith("2-"):
            # 2 PLT RESERVE → east runway threshold (holds position)
            end = rwy_26.offset(
                (hash(cs + "e") % 7 - 3) * 25,
                (hash(cs + "f") % 7 - 3) * 25,
            )
        elif cs.startswith("W-"):
            # WPNS PLT → mortar line at north fence (doesn't advance onto airfield)
            end = mortar_line.offset(
                (hash(cs + "e") % 7 - 3) * 30,
                (hash(cs + "f") % 7 - 3) * 30,
            )
        else:
            end = terminal

        plan[cs] = (start, end)

    log.info("H-HOUR — dual DZ assault (%d steps × %.1fs)", steps, dt)
    for i in range(steps + 1):
        t = i / steps
        for r in ROSTER:
            start, end = plan[r.callsign]
            here = lerp(start, end, t)
            body = {
                "latitude":  here.lat,
                "longitude": here.lon,
                "altitude":  5.0,
            }
            try:
                api.post("/tracking/position", r.token, body)
            except Exception as exc:
                log.warning("%s: %s", r.callsign, exc)
        if i % 10 == 0:
            log.info("  step %d/%d — t=%.2f", i, steps, t)
        time.sleep(dt)
    log.info("OBJ SEAGULL seized — RANGER COY consolidating on PL SURF")


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
        description="OPERATION SEAGULL — RANGER COY airborne assault on Oostende Airport")
    parser.add_argument("--backend",
                        default=os.environ.get("ARROW_BACKEND_URL", "http://localhost:6001"),
                        help="Backend URL (default: ARROW_BACKEND_URL env, else localhost)")
    parser.add_argument("--admin",       default="benoit",    help="ADMIN callsign")
    parser.add_argument("--password",    default="ranger14",  help="ADMIN password")
    parser.add_argument("--op-password", default="rangers!",  help="Operator password")
    parser.add_argument("--reset",       action="store_true", help="Delete all tactical objects first")
    parser.add_argument("--no-move",     action="store_true", help="Plan-only — skip GPS simulation")
    parser.add_argument("--steps",       type=int,   default=80,  help="Movement steps")
    parser.add_argument("--dt",          type=float, default=2.0, help="Seconds between steps")
    parser.add_argument("--mission-name", default="Operation SEAGULL",
                        help="Mission name to create or adopt")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    api = Api(args.backend)

    log.info("OPERATION SEAGULL — RANGER COY airborne assault on OOSTENDE AIRPORT (EBOS)")
    log.info("backend=%s  admin=%s", args.backend, args.admin)
    admin_tok = api.login(args.admin, args.password)
    api.create_mission(admin_tok, args.mission_name, description=
                       "Airborne seizure of Oostende Airport (EBOS) to enable CLP air-landing.",
                       map_center_lat=AIRPORT[0], map_center_lng=AIRPORT[1], map_zoom=14)

    if args.reset:
        reset_objects(api, admin_tok)

    # 1. Hierarchy
    teams = build_hierarchy(api, admin_tok)

    # 2. Operators
    register_operators(api, admin_tok, teams, args.op_password)

    # 3. OPORD
    opord = api.post("/opord", admin_tok, build_opord())
    log.info("OPORD %s posted (id=%s)", opord["opord_number"], opord["id"])
    try:
        api.post(f"/opord/{opord['id']}/publish", admin_tok, {})
        api.post(f"/opord/{opord['id']}/send", admin_tok,
                 {"operator_ids": [r.op_id for r in ROSTER]})
        log.info("OPORD published and sent to %d operators", len(ROSTER))
    except Exception as exc:
        log.warning("OPORD publish/send skipped: %s", exc)

    # 4. Tactical graphics
    objs = build_graphics()
    for o in objs:
        try:
            api.post("/tactical-objects", admin_tok, o)
        except Exception as exc:
            log.warning("TG post failed [%s]: %s", o.get("type"), exc)
    log.info("tactical graphics + enemies + POIs planted: %d items", len(objs))

    # 5. Fire plan
    for fm in build_fire_plan():
        try:
            api.post("/fire-missions", admin_tok, fm)
        except Exception as exc:
            log.warning("FM post failed: %s", exc)
    log.info("fire plan posted: 4 missions")

    # 6. Movement
    if args.no_move:
        log.info("--no-move: plan complete — skipping GPS simulation")
        return
    simulate_movement(api, steps=args.steps, dt=args.dt)


if __name__ == "__main__":
    main()
