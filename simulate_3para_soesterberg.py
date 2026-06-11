#!/usr/bin/env python3
"""
Arrow — Operation MARKET AMBER: 3 PARA / SOR Airborne Assault on Soesterberg
& Attack on Amersfoort Kazerne (Bernhardkazerne)
==============================================================================

Battalion-level end-to-end simulator. Drives the full Arrow backend through a
two-phase BN operation: airborne seizure of Soesterberg Airfield ("Zoeteberg")
followed by a mounted assault on Amersfoort Kazerne.

Phases
------
  1. INSERTION  (H-Hour)    : 3 PARA / SOR jumps DZ MAROON (N of airfield, main)
                               and DZ GREEN (SE, CHARLIE CIE flanking)
  2. SEIZURE    (H+0…H+60) : ALPHA seizes terminal/hangars (OBJ AMBER),
                               BRAVO secures runway (OBJ ORANGE),
                               CHARLIE clears south perimeter + blocks N237,
                               DELTA mortars + snipers provide overwatch/suppression
  3. FLY-IN     (H+60…H+90): C-130 × 4 land on seized runway, offload YPR-765
                               IFVs; ECHO CIE CQMS marshals vehicles
  4. ADVANCE    (H+90…H+150): Column moves via N237/A28 ramps toward Amersfoort,
                               CHARLIE leads as advance guard, RECON screens
  5. ASSAULT    (H+150…H+240): ALPHA assaults Kazerne north gate (main effort),
                               BRAVO breaches west perimeter (supporting effort),
                               BHQ TAC CP holds on PL TULIP, DELTA overwatch
  6. CONSOLIDATION: Secure OBJ NASSAU (Kazerne), EPW collection, CCP active

Elements
--------
  • 64 operators from 3 PARA / SOR (using 3para_sor.json callsigns)
  • Mission  : OPORD 26-003 MARKET AMBER
  • Hierarchy: uses / creates 3 PARA / SOR company hierarchy
  • OPORD    : full 5-paragraph OPORD
  • Graphics : DZs, phase lines, OBJs, axes, boundary, FLOT/FLET, enemy + POIs
  • Fire plan: 5 missions (airfield suppression, breach, kazerne entrance,
               AT bunker, SMOKE screen)
  • CAS      : 2 × 9-liner (enemy BMP at airfield N gate H+35;
               enemy AT bunker kazerne main gate H+175) + 1 CAS asset
  • Reports  : MEDEVAC URGENT (ALPHA-112, airfield breach H+25),
               SPOT/SALUTE (enemy QRF on N237, H+60),
               MEDEVAC PRIORITY (BRAVO-112, kazerne west breach H+185)

Run
---
    uv run python simulate_3para_soesterberg.py
    uv run python simulate_3para_soesterberg.py --backend http://localhost:6001
    uv run python simulate_3para_soesterberg.py --reset
    uv run python simulate_3para_soesterberg.py --no-move
    uv run python simulate_3para_soesterberg.py --steps 100 --dt 1.5
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import time
from dataclasses import dataclass, field

import sim_utils

log = logging.getLogger("market_amber")

# ── Operation constants ───────────────────────────────────────────────────────

# Vliegbasis Soesterberg — former Dutch military airfield, ~10 km W of Amersfoort
# User callsign: "Zoeteberg airfield"
SOESTERBERG     = (52.1228, 5.2825)
KAZERNE         = (52.1560, 5.3830)   # Bernhardkazerne, Amersfoort (approx)
BN_TAC_CP_AIR   = (52.1420, 5.2790)   # BN TAC CP north of airfield (H+15)
BN_TAC_CP_KAZ   = (52.1480, 5.3650)   # BN TAC CP advance (H+140, W of Kazerne)
DZ_MAROON_REF   = (52.1420, 5.2800)   # DZ MAROON — BHQ / ALPHA / BRAVO / DELTA
DZ_GREEN_REF    = (52.1060, 5.3100)   # DZ GREEN  — CHARLIE CIE (SE flanking)
N237_BLOCK      = (52.1300, 5.3300)   # N237 blocking OP (CHARLIE advance guard)

H_HOUR   = "101800ZJUN26"
OP_NAME  = "OPERATION MARKET AMBER"
BN_NAME  = "3 PARA / SOR"


# ── Geometry ──────────────────────────────────────────────────────────────────

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
    t = max(0.0, min(1.0, t))
    return LL(a.lat + (b.lat - a.lat) * t, a.lon + (b.lon - a.lon) * t)


def lerp3(a: LL, b: LL, c: LL, t: float) -> LL:
    """Three-waypoint lerp: a→b for t∈[0,0.45), jitter at b for [0.45,0.65), b→c for [0.65,1]."""
    if t < 0.45:
        return lerp(a, b, t / 0.45)
    elif t < 0.65:
        hold_t = (t - 0.45) / 0.20
        return b.offset(math.sin(hold_t * 7) * 20, math.cos(hold_t * 5) * 15)
    else:
        return lerp(b, c, (t - 0.65) / 0.35)


Api = sim_utils.Api


# ── Roster ────────────────────────────────────────────────────────────────────
# insert: DZ_MAROON | DZ_GREEN | FLY_IN | BN_TAC

@dataclass
class OpRoster:
    callsign:  str
    rank:      str
    role:      str
    coy:       str         # hierarchy key
    team_name: str         # team name in hierarchy
    insert:    str         # DZ_MAROON | DZ_GREEN | FLY_IN | BN_TAC
    token:     str = ""
    op_id:     int = 0
    team_id:   int = 0
    password:  str = ""    # stored so movement can re-auth on 401


ROSTER: list[OpRoster] = [
    # ── BHQ ──────────────────────────────────────────────────────────────────
    OpRoster("HAMMER-6",  "OF-4", "BATTLE_CAPTAIN", "BHQ", "CO-PARTY",  "BN_TAC"),
    OpRoster("HAMMER-5",  "OF-3", "OPS",            "BHQ", "CO-PARTY",  "BN_TAC"),
    OpRoster("HAMMER-9",  "OR-9", "OPERATOR",       "BHQ", "CO-PARTY",  "BN_TAC"),
    OpRoster("GHOST-6",   "OF-2", "INTEL",          "BHQ", "S2-CELL",   "BN_TAC"),
    OpRoster("OPS-6",     "OF-3", "OPS",            "BHQ", "S3-CELL",   "BN_TAC"),
    OpRoster("FIRE-6",    "OF-2", "FO",             "BHQ", "FSC",       "BN_TAC"),
    OpRoster("RADIO-6",   "OF-1", "OPERATOR",       "BHQ", "COMMS-A",   "BN_TAC"),
    OpRoster("DOC-6",     "OF-2", "MED",            "BHQ", "AID-POST",  "BN_TAC"),

    # ── ALPHA CIE — MAIN EFFORT (airborne, DZ MAROON) ────────────────────────
    OpRoster("ALPHA-6",   "OF-2", "BATTLE_CAPTAIN", "ALPHA", "ALPHA-HQ",  "DZ_MAROON"),
    OpRoster("ALPHA-9",   "OR-8", "OPERATOR",       "ALPHA", "ALPHA-HQ",  "DZ_MAROON"),
    OpRoster("ALPHA-6A",  "OF-1", "OPS",            "ALPHA", "ALPHA-HQ",  "DZ_MAROON"),
    # 1er Peloton
    OpRoster("ALPHA-11",  "OF-1", "OPERATOR",       "ALPHA", "A1PLT-HQ",  "DZ_MAROON"),
    OpRoster("ALPHA-12",  "OR-6", "OPERATOR",       "ALPHA", "A1PLT-HQ",  "DZ_MAROON"),
    OpRoster("ALPHA-111", "OR-6", "OPERATOR",       "ALPHA", "A1SEC1",    "DZ_MAROON"),
    OpRoster("ALPHA-112", "OR-5", "OPERATOR",       "ALPHA", "A1SEC1",    "DZ_MAROON"),
    OpRoster("ALPHA-113", "OR-5", "OPERATOR",       "ALPHA", "A1SEC1",    "DZ_MAROON"),
    OpRoster("ALPHA-114", "OR-4", "OPERATOR",       "ALPHA", "A1SEC1",    "DZ_MAROON"),
    OpRoster("ALPHA-121", "OR-6", "OPERATOR",       "ALPHA", "A1SEC2",    "DZ_MAROON"),
    OpRoster("ALPHA-122", "OR-5", "OPERATOR",       "ALPHA", "A1SEC2",    "DZ_MAROON"),
    OpRoster("ALPHA-123", "OR-5", "OPERATOR",       "ALPHA", "A1SEC2",    "DZ_MAROON"),
    OpRoster("ALPHA-124", "OR-4", "OPERATOR",       "ALPHA", "A1SEC2",    "DZ_MAROON"),
    # 2eme Peloton
    OpRoster("ALPHA-21",  "OF-1", "OPERATOR",       "ALPHA", "A2PLT-HQ",  "DZ_MAROON"),
    OpRoster("ALPHA-22",  "OR-6", "OPERATOR",       "ALPHA", "A2PLT-HQ",  "DZ_MAROON"),
    OpRoster("ALPHA-211", "OR-6", "OPERATOR",       "ALPHA", "A2SEC1",    "DZ_MAROON"),
    OpRoster("ALPHA-212", "OR-5", "OPERATOR",       "ALPHA", "A2SEC1",    "DZ_MAROON"),
    OpRoster("ALPHA-213", "OR-5", "OPERATOR",       "ALPHA", "A2SEC1",    "DZ_MAROON"),
    OpRoster("ALPHA-214", "OR-4", "OPERATOR",       "ALPHA", "A2SEC1",    "DZ_MAROON"),

    # ── BRAVO CIE — SUPPORTING EFFORT (airborne, DZ MAROON) ──────────────────
    OpRoster("BRAVO-6",   "OF-2", "BATTLE_CAPTAIN", "BRAVO", "BRAVO-HQ",  "DZ_MAROON"),
    OpRoster("BRAVO-9",   "OR-8", "OPERATOR",       "BRAVO", "BRAVO-HQ",  "DZ_MAROON"),
    OpRoster("BRAVO-6A",  "OF-1", "OPS",            "BRAVO", "BRAVO-HQ",  "DZ_MAROON"),
    OpRoster("BRAVO-11",  "OF-1", "OPERATOR",       "BRAVO", "B1PLT-HQ",  "DZ_MAROON"),
    OpRoster("BRAVO-12",  "OR-6", "OPERATOR",       "BRAVO", "B1PLT-HQ",  "DZ_MAROON"),
    OpRoster("BRAVO-111", "OR-6", "OPERATOR",       "BRAVO", "B1SEC1",    "DZ_MAROON"),
    OpRoster("BRAVO-112", "OR-5", "OPERATOR",       "BRAVO", "B1SEC1",    "DZ_MAROON"),
    OpRoster("BRAVO-113", "OR-5", "OPERATOR",       "BRAVO", "B1SEC1",    "DZ_MAROON"),
    OpRoster("BRAVO-114", "OR-4", "OPERATOR",       "BRAVO", "B1SEC1",    "DZ_MAROON"),
    OpRoster("BRAVO-21",  "OF-1", "OPERATOR",       "BRAVO", "B2PLT-HQ",  "DZ_MAROON"),
    OpRoster("BRAVO-22",  "OR-6", "OPERATOR",       "BRAVO", "B2PLT-HQ",  "DZ_MAROON"),
    OpRoster("BRAVO-211", "OR-6", "OPERATOR",       "BRAVO", "B2SEC1",    "DZ_MAROON"),
    OpRoster("BRAVO-212", "OR-5", "OPERATOR",       "BRAVO", "B2SEC1",    "DZ_MAROON"),

    # ── CHARLIE CIE — FLANKING / ADVANCE GUARD (airborne, DZ GREEN) ──────────
    OpRoster("CHARLIE-6",   "OF-2", "BATTLE_CAPTAIN", "CHARLIE", "CHARLIE-HQ", "DZ_GREEN"),
    OpRoster("CHARLIE-9",   "OR-8", "OPERATOR",       "CHARLIE", "CHARLIE-HQ", "DZ_GREEN"),
    OpRoster("CHARLIE-11",  "OF-1", "OPERATOR",       "CHARLIE", "C1PLT-HQ",   "DZ_GREEN"),
    OpRoster("CHARLIE-12",  "OR-6", "OPERATOR",       "CHARLIE", "C1PLT-HQ",   "DZ_GREEN"),
    OpRoster("CHARLIE-111", "OR-6", "OPERATOR",       "CHARLIE", "C1SEC1",     "DZ_GREEN"),
    OpRoster("CHARLIE-112", "OR-5", "OPERATOR",       "CHARLIE", "C1SEC1",     "DZ_GREEN"),
    OpRoster("CHARLIE-113", "OR-5", "OPERATOR",       "CHARLIE", "C1SEC1",     "DZ_GREEN"),
    OpRoster("CHARLIE-114", "OR-4", "OPERATOR",       "CHARLIE", "C1SEC1",     "DZ_GREEN"),

    # ── DELTA CIE — SUPPORT (mortar line + snipers, DZ MAROON) ───────────────
    OpRoster("DELTA-6",   "OF-2", "BATTLE_CAPTAIN", "DELTA", "DELTA-HQ",  "DZ_MAROON"),
    OpRoster("MORT-6",    "OF-1", "OPERATOR",       "DELTA", "MORT-SEC",  "DZ_MAROON"),
    OpRoster("MORT-1",    "OR-6", "OPERATOR",       "DELTA", "MORT-SEC",  "DZ_MAROON"),
    OpRoster("MORT-2",    "OR-5", "OPERATOR",       "DELTA", "MORT-SEC",  "DZ_MAROON"),
    OpRoster("MORT-5",    "OF-1", "FO",             "DELTA", "MORT-FOO",  "DZ_MAROON"),
    OpRoster("SNIPER-1",  "OR-6", "OPERATOR",       "DELTA", "SNP-ALPHA", "DZ_MAROON"),
    OpRoster("SNIPER-2",  "OR-5", "OPERATOR",       "DELTA", "SNP-ALPHA", "DZ_MAROON"),
    OpRoster("SNIPER-3",  "OR-6", "OPERATOR",       "DELTA", "SNP-BRAVO", "DZ_MAROON"),
    OpRoster("SNIPER-4",  "OR-5", "OPERATOR",       "DELTA", "SNP-BRAVO", "DZ_MAROON"),
    OpRoster("AT-6",      "OF-1", "OPERATOR",       "DELTA", "AT-SEC",    "DZ_MAROON"),
    OpRoster("AT-1",      "OR-6", "OPERATOR",       "DELTA", "AT-SEC",    "DZ_MAROON"),

    # ── ECHO CIE — HQ / LOG (fly-in with vehicles, H+90) ────────────────────
    OpRoster("ECHO-6",    "OF-2", "BATTLE_CAPTAIN", "ECHO", "ECHO-HQ",   "FLY_IN"),
    OpRoster("LOG-6",     "OF-1", "LOG",            "ECHO", "LOG-TEAM",  "FLY_IN"),
    OpRoster("LOG-1",     "OR-7", "LOG",            "ECHO", "LOG-TEAM",  "FLY_IN"),
    OpRoster("PION-6",    "OF-1", "OPERATOR",       "ECHO", "PION-ALPHA","FLY_IN"),
    OpRoster("PION-1",    "OR-6", "OPERATOR",       "ECHO", "PION-ALPHA","FLY_IN"),
    OpRoster("RECON-6",   "OF-1", "INTEL",          "ECHO", "RECON-TM",  "DZ_MAROON"),  # jumps with main
    OpRoster("RECON-1",   "OR-6", "INTEL",          "ECHO", "RECON-TM",  "DZ_MAROON"),
    OpRoster("RECON-2",   "OR-5", "INTEL",          "ECHO", "RECON-TM",  "DZ_MAROON"),
    # Unimog section — fly-in with vehicles (log + pioneer support)
    OpRoster("UNIMOG-1",  "OR-5", "LOG",            "ECHO", "UNIMOG-SEC","FLY_IN"),
    OpRoster("UNIMOG-2",  "OR-4", "LOG",            "ECHO", "UNIMOG-SEC","FLY_IN"),
    OpRoster("UNIMOG-3",  "OR-4", "LOG",            "ECHO", "UNIMOG-SEC","FLY_IN"),

    # ── Jackal recce section — jeep-mounted screen, jumps with main ──────────
    # 4 × Jackal MWMIK (2-man crew each); fast forward screen on N237 corridor
    OpRoster("JACKAL-1",  "OR-6", "INTEL",          "ECHO", "JACKAL-SEC","DZ_MAROON"),
    OpRoster("JACKAL-2",  "OR-5", "INTEL",          "ECHO", "JACKAL-SEC","DZ_MAROON"),
    OpRoster("JACKAL-3",  "OR-6", "INTEL",          "ECHO", "JACKAL-SEC","DZ_MAROON"),
    OpRoster("JACKAL-4",  "OR-5", "INTEL",          "ECHO", "JACKAL-SEC","DZ_MAROON"),
    OpRoster("JACKAL-5",  "OR-6", "INTEL",          "ECHO", "JACKAL-SEC","DZ_MAROON"),
    OpRoster("JACKAL-6",  "OR-5", "INTEL",          "ECHO", "JACKAL-SEC","DZ_MAROON"),
    OpRoster("JACKAL-7",  "OR-6", "INTEL",          "ECHO", "JACKAL-SEC","DZ_MAROON"),
    OpRoster("JACKAL-8",  "OR-5", "INTEL",          "ECHO", "JACKAL-SEC","DZ_MAROON"),

    # ── UAV operator — BHQ S2 cell, jumps with BHQ ───────────────────────────
    OpRoster("UAV-1",     "OR-6", "INTEL",          "BHQ",  "S2-CELL",   "BN_TAC"),
]


# ── Hierarchy builder ─────────────────────────────────────────────────────────

def _gc_co(api: Api, tok: str, name: str) -> int:
    for c in api.get("/companies", tok):
        if c["name"] == name:
            return c["id"]
    return api.post("/companies", tok, {"name": name})["id"]

def _gc_plt(api: Api, tok: str, name: str, coy_id: int) -> int:
    for p in api.get("/platoons", tok):
        if p["name"] == name and p["company_id"] == coy_id:
            return p["id"]
    return api.post("/platoons", tok, {"name": name, "company_id": coy_id})["id"]

def _gc_sec(api: Api, tok: str, name: str, plt_id: int) -> int:
    for s in api.get("/sections", tok):
        if s["name"] == name and s["platoon_id"] == plt_id:
            return s["id"]
    return api.post("/sections", tok, {"name": name, "platoon_id": plt_id})["id"]

def _gc_team(api: Api, tok: str, name: str, sec_id: int) -> int:
    for t in api.get("/teams", tok):
        if t["name"] == name and t["section_id"] == sec_id:
            return t["id"]
    return api.post("/teams", tok, {"name": name, "section_id": sec_id})["id"]


def build_hierarchy(api: Api, admin_tok: str) -> dict[str, int]:
    """Ensure the 3 PARA / SOR hierarchy exists; return {team_name: team_id}."""
    teams: dict[str, int] = {}

    co = _gc_co(api, admin_tok, "3 PARA / SOR")

    # BHQ ─────────────────────────────────────────────────────────────────────
    bhq_plt = _gc_plt(api, admin_tok, "BHQ - Battalion Headquarters", co)
    bhq_cmd = _gc_sec(api, admin_tok, "Command Element",   bhq_plt)
    bhq_sig = _gc_sec(api, admin_tok, "Signals Platoon",   bhq_plt)
    bhq_med = _gc_sec(api, admin_tok, "Bn Aid Station",    bhq_plt)
    for t in ("CO-PARTY", "S2-CELL", "S3-CELL", "FSC"):
        teams[t] = _gc_team(api, admin_tok, t, bhq_cmd)
    for t in ("COMMS-A",):
        teams[t] = _gc_team(api, admin_tok, t, bhq_sig)
    for t in ("AID-POST",):
        teams[t] = _gc_team(api, admin_tok, t, bhq_med)

    # ALPHA CIE ───────────────────────────────────────────────────────────────
    a_plt = _gc_plt(api, admin_tok, "ALPHA CIE - 1st Para Company", co)
    a_hq  = _gc_sec(api, admin_tok, "Company HQ",               a_plt)
    a_1   = _gc_sec(api, admin_tok, "1er Peloton - 1st Platoon", a_plt)
    a_2   = _gc_sec(api, admin_tok, "2eme Peloton - 2nd Platoon",a_plt)
    teams["ALPHA-HQ"]  = _gc_team(api, admin_tok, "ALPHA-HQ",  a_hq)
    for t in ("A1PLT-HQ", "A1SEC1", "A1SEC2"):
        teams[t] = _gc_team(api, admin_tok, t, a_1)
    for t in ("A2PLT-HQ", "A2SEC1"):
        teams[t] = _gc_team(api, admin_tok, t, a_2)

    # BRAVO CIE ───────────────────────────────────────────────────────────────
    b_plt = _gc_plt(api, admin_tok, "BRAVO CIE - 2nd Para Company", co)
    b_hq  = _gc_sec(api, admin_tok, "Company HQ",               b_plt)
    b_1   = _gc_sec(api, admin_tok, "1er Peloton - 1st Platoon", b_plt)
    b_2   = _gc_sec(api, admin_tok, "2eme Peloton - 2nd Platoon",b_plt)
    teams["BRAVO-HQ"]  = _gc_team(api, admin_tok, "BRAVO-HQ", b_hq)
    for t in ("B1PLT-HQ", "B1SEC1"):
        teams[t] = _gc_team(api, admin_tok, t, b_1)
    for t in ("B2PLT-HQ", "B2SEC1"):
        teams[t] = _gc_team(api, admin_tok, t, b_2)

    # CHARLIE CIE ─────────────────────────────────────────────────────────────
    c_plt = _gc_plt(api, admin_tok, "CHARLIE CIE - 3rd Para Company", co)
    c_hq  = _gc_sec(api, admin_tok, "Company HQ",               c_plt)
    c_1   = _gc_sec(api, admin_tok, "1er Peloton - 1st Platoon", c_plt)
    teams["CHARLIE-HQ"] = _gc_team(api, admin_tok, "CHARLIE-HQ", c_hq)
    for t in ("C1PLT-HQ", "C1SEC1"):
        teams[t] = _gc_team(api, admin_tok, t, c_1)

    # DELTA CIE ───────────────────────────────────────────────────────────────
    d_plt = _gc_plt(api, admin_tok, "DELTA CIE - Support Company", co)
    d_hq  = _gc_sec(api, admin_tok, "Company HQ",                  d_plt)
    d_mor = _gc_sec(api, admin_tok, "Mortiers - Mortar Platoon",    d_plt)
    d_snp = _gc_sec(api, admin_tok, "Tireurs d'Elite - Sniper Section", d_plt)
    d_at  = _gc_sec(api, admin_tok, "Anti-Chars - Anti-Tank Platoon",   d_plt)
    teams["DELTA-HQ"]  = _gc_team(api, admin_tok, "DELTA-HQ",  d_hq)
    for t in ("MORT-SEC", "MORT-FOO"):
        teams[t] = _gc_team(api, admin_tok, t, d_mor)
    for t in ("SNP-ALPHA", "SNP-BRAVO"):
        teams[t] = _gc_team(api, admin_tok, t, d_snp)
    teams["AT-SEC"]    = _gc_team(api, admin_tok, "AT-SEC", d_at)

    # ECHO CIE ────────────────────────────────────────────────────────────────
    e_plt = _gc_plt(api, admin_tok, "ECHO CIE - HQ Company", co)
    e_hq  = _gc_sec(api, admin_tok, "Company HQ",                    e_plt)
    e_log = _gc_sec(api, admin_tok, "Logistique - Log Platoon",       e_plt)
    e_pio = _gc_sec(api, admin_tok, "Pionniers - Pioneer Platoon",    e_plt)
    e_rec = _gc_sec(api, admin_tok, "Reconnaissance Platoon",         e_plt)
    teams["ECHO-HQ"]    = _gc_team(api, admin_tok, "ECHO-HQ",    e_hq)
    for t in ("LOG-TEAM", "UNIMOG-SEC"):
        teams[t] = _gc_team(api, admin_tok, t, e_log)
    teams["PION-ALPHA"] = _gc_team(api, admin_tok, "PION-ALPHA", e_pio)
    for t in ("RECON-TM", "JACKAL-SEC"):
        teams[t] = _gc_team(api, admin_tok, t, e_rec)

    # UAV operator sits in S2-CELL (already created under BHQ cmd)

    log.info("hierarchy ready — %d teams", len(teams))
    return teams


# ── Operators ─────────────────────────────────────────────────────────────────

def register_operators(api: Api, admin_tok: str, teams: dict[str, int],
                       password: str) -> None:
    existing = {op["callsign"]: op["id"] for op in api.get("/operators", admin_tok)}

    for r in ROSTER:
        r.team_id = teams[r.team_name]
        if r.callsign not in existing:
            body = {
                "callsign": r.callsign, "password": password,
                "rank": r.rank, "role": r.role, "team_id": r.team_id,
            }
            resp = api.c.post(
                api._p("/auth/register/admin"), json=body,
                headers={"Authorization": f"Bearer {admin_tok}"},
            )
            if resp.status_code == 201:
                r.token    = resp.json()["access_token"]
                r.password = password
            else:
                log.warning("register %s → %d", r.callsign, resp.status_code)
                time.sleep(0.15)
                r.token = api.login(r.callsign, password)
        else:
            op_id = existing[r.callsign]
            # Reset password so we can log in with sim password
            api.c.post(
                api._p(f"/operators/{op_id}/set-password"),
                json={"password": password},
                headers={"Authorization": f"Bearer {admin_tok}"},
            )
            # Patch team assignment to match simulation
            api.c.patch(
                api._p(f"/operators/{op_id}"),
                json={"team_id": r.team_id, "role": r.role},
                headers={"Authorization": f"Bearer {admin_tok}"},
            )
            time.sleep(0.10)
            r.token    = api.login(r.callsign, password)
            r.password = password

        if r.token:
            me = api.get("/auth/me", r.token)
            r.op_id = me["id"]

    log.info("roster ready — %d operators", len(ROSTER))


# ── OPORD ─────────────────────────────────────────────────────────────────────

def build_opord() -> dict:
    return {
        "title":          "OPORD 26-003 — OPERATION MARKET AMBER",
        "opord_number":   "26-003",
        "dtg":            H_HOUR,
        "time_zone":      "ZULU",
        "classification": "UNCLASSIFIED // FOUO",
        "references": (
            "(a) Map: TPC L-2A Netherlands 1:500,000 / AMS-TPC Series 1404 Sheet L-2A\n"
            "(b) Map: 1:50,000 Netherlands Sheet 32H AMERSFOORT (Edition 6-TPC)\n"
            "(c) BDE WARNORD 26-011 dtd 091400ZJUN26\n"
            "(d) INTSUM 26-044 — Soesterberg garrison est. 40-60 PAX; "
            "mechanized plt with 2× BMP-2; Amersfoort Kazerne est. 120 PAX, "
            "AT positions confirmed w gate\n"
            "(e) AIP EHSB-AD-2 — Vliegbasis Soesterberg runway data (RWY 09/27, 2,600 m)\n"
            "(f) ROE Card: TF 3PARA ROE-03 (NL OPFOR)\n"
            "(g) BN CBRN ANNEX 26-003A — MOPP-0 throughout; kit jumps with man"
        ),
        "task_organization": (
            f"{BN_NAME} (TF MARKET AMBER) — TASK ORGANISATION\n"
            "  BHQ: HAMMER-6 CO, HAMMER-5 2IC, HAMMER-9 RSM, "
            "GHOST-6 S2, OPS-6 S3, FIRE-6 FSO/JTAC, RADIO-6 Sigs, DOC-6 MO\n"
            "  ALPHA CIE — MAIN EFFORT — airborne OBJ AMBER (airfield terminal/hangars)\n"
            "    A-6 OC, A-9 CSM, A-6A XO; 1er PLT (A11/12 + 2 sections); "
            "2eme PLT (A21/22 + 2 sections)\n"
            "  BRAVO CIE — SUPPORTING EFFORT — airborne OBJ ORANGE (runway + south taxiway)\n"
            "    B-6 OC, B-9 CSM, B-6A XO; 1er PLT (B11/12 + 2 sections); 2eme PLT\n"
            "  CHARLIE CIE — FLANKING / ADVANCE GUARD — DZ GREEN (south perimeter + N237 block)\n"
            "    C-6 OC, C-9 CSM; 1er PLT (C11/12 + sections)\n"
            "  DELTA CIE — FIRE SUPPORT — mortar line DZ MAROON; snipers overwatch; AT reserve\n"
            "    DELTA-6 OC; MORT section (MORT-6/1/2 + FOO MORT-5); "
            "SNP-ALPHA/BRAVO (4× sniper teams); AT section\n"
            "  ECHO CIE — HQ / LOGISTICS — fly-in H+90 with YPR-765 IFVs\n"
            "    ECHO-6 OC; LOG team (LOG-6/1); PION-ALPHA; RECON-TM (jumps DZ MAROON)\n"
            "  ATTACHMENTS: 2× F-16AM (ORANGE 41) loiter N of Utrecht; "
            "DUSTOFF ANGEL 31 (NH-90) at FOB Gilze-Rijen; "
            "4× C-130 CLP package on-call H+60"
        ),
        "situation": {
            "enemy": (
                "OPFOR occupying former Vliegbasis Soesterberg as forward logistics/ISR node "
                "and Amersfoort Kazerne (Bernhardkazerne) as garrison base.\n"
                "SOESTERBERG: Motorised rifle plt est. 40-60 PAX. 2× BMP-2 at north apron "
                "(52.125N/5.285E). Guard posts at main gate (west, 52.122N/5.267E), "
                "east taxiway exit (52.121N/5.302E), south fence (52.115N/5.283E). "
                "Observer/sentry at control tower. MANPADS team mobile.\n"
                "AMERSFOORT KAZERNE: Mechanised infantry coy (-) est. 120 PAX, 4× BMP-2, "
                "2× AT bunker (west gate 52.156N/5.375E; north fence 52.162N/5.385E). "
                "Mortar section (2× 82mm) within perimeter. "
                "ENEMY COA-ML: defend Kazerne in depth, withdraw into buildings; "
                "attempt to recapture airfield with QRF on N237 (ETA H+90 if alerted)."
            ),
            "friendly": (
                f"{BN_NAME} is BDE main effort for TF NEDERLAND. "
                "ALPHA CIE seizes OBJ AMBER (airfield terminal/hangars) as main effort; "
                "BRAVO CIE secures OBJ ORANGE (runway/south taxiway) for CLP; "
                "CHARLIE CIE flanks from SE via DZ GREEN, blocks N237 at H+60; "
                "DELTA provides mortar fire plan + sniper overwatch throughout; "
                "ECHO CIE fly-in H+90 with YPR-765 vehicles and log support. "
                "After airfield seizure TF conducts mounted assault on OBJ NASSAU (Kazerne). "
                "CAS: 2× F-16AM (ORANGE 41) loiter vic 52.3N/5.0E, armed LGB + gun. "
                "DUSTOFF ANGEL 31 (NH-90) on standby H-Hour."
            ),
            "civilian": (
                "Soesterberg area: museum (Nationaal Militair Museum) on airfield grounds — "
                "NO FIRE within museum complex. Village of Soesterberg 500m south. "
                "N237 has civilian traffic until H-15 curfew. "
                "Amersfoort civilian population present in city; Kazerne is in SE of city. "
                "All fires must PID; no area fires within 300m of civilian structures. "
                "N237/N221 intersection — VCP mandatory before engaging vehicle threats."
            ),
            "weather": (
                "BMNT 0354Z, EENT 2102Z. H-Hour 1800Z = mid-afternoon. "
                "Partly cloudy 30%, ceiling 2800m. Wind 280/06 KTS (westerly). "
                "Vis 20km. No precipitation. NVG: FAIR (bright afternoon). "
                "Moon rises 2215Z — H+135 min onward good NVG. "
                "Drop conditions GREEN (wind < 8 kts at altitude)."
            ),
            "terrain": (
                "SOESTERBERG: Flat open heathland, 100m buffer around runway clear. "
                "North: light forest 400m before DZ MAROON. East: open fields. "
                "South: village. West: N237 highway (key route).\n"
                "AMERSFOORT: Semi-urban approach. Kazerne is walled compound SE of city. "
                "Main approach: N237 north, Soestdijk/N233 from west. "
                "Urban terrain within Kazerne buildings — close combat likely. "
                "Railway embankment 300m north provides covered approach for ALPHA."
            ),
        },
        "mission": (
            f"{BN_NAME} (TF MARKET AMBER) conducts a two-phase BN operation NLT {H_HOUR} "
            "to seize Soesterberg Airfield (OBJ AMBER + OBJ ORANGE) by airborne assault, "
            "receive follow-on vehicles by CLP, then conduct a mounted assault to seize "
            "Amersfoort Kazerne (OBJ NASSAU) IOT destroy the OPFOR garrison and secure "
            "the key terrain for BDE follow-on forces NLT H+240."
        ),
        "execution": {
            "commanders_intent": {
                "purpose": (
                    "Seize Soesterberg Airfield intact, fly in vehicles, then destroy the "
                    "OPFOR garrison at Amersfoort Kazerne — removing all OPFOR presence "
                    "in the Utrecht / Amersfoort operational area."
                ),
                "key_tasks": [
                    f"ALPHA/BRAVO/CHARLIE jump DZ MAROON/GREEN NLT {H_HOUR}.",
                    "DELTA mortar line operational at DZ MAROON NLT H+15.",
                    "ALPHA seizes OBJ AMBER (terminal + hangars) NLT H+60.",
                    "BRAVO clears runway 09/27 for CLP NLT H+60.",
                    "CHARLIE blocks N237 southbound NLT H+60 to prevent Kazerne QRF.",
                    "CLP (4× C-130) land H+60 to H+90; YPR-765 off-loaded by H+90.",
                    "RECON screens N237 / N221 corridor from H+60 onward.",
                    "Column departs airfield NLT H+95; CHARLIE leads.",
                    "ALPHA breaches Kazerne north gate NLT H+175.",
                    "BRAVO breaches Kazerne west perimeter NLT H+175.",
                    "OBJ NASSAU secured NLT H+240; EPW collection active.",
                ],
                "end_state": (
                    "OBJ AMBER + OBJ ORANGE seized and held; "
                    "CLP runway clear for follow-on; "
                    "OBJ NASSAU (Kazerne) seized; OPFOR garrison destroyed or captured; "
                    "N237 / N221 corridor open for BDE follow-on forces; "
                    "CCP active at BN TAC CP (Kazerne approach)."
                ),
            },
            "concept_of_operations": {
                "form_of_maneuver": (
                    "Two-phase operation: Phase 1 — airborne seizure of Soesterberg; "
                    "Phase 2 — mounted assault on Amersfoort Kazerne. "
                    "Three-company converging assault on airfield; two-company assault on Kazerne."
                ),
                "scheme_of_maneuver": (
                    "Phase 1 — Airborne Seizure (H-Hour to H+90):\n"
                    "H-HOUR: First pass drops BHQ + ALPHA + BRAVO + DELTA on DZ MAROON "
                    "(52.142N/5.280E, north of airfield). "
                    "Second pass drops CHARLIE on DZ GREEN (52.106N/5.310E, SE, simultaneous). "
                    "DELTA mortar line established DZ MAROON NLT H+15. "
                    "ALPHA advances south → OBJ AMBER (terminal complex, 52.125N/5.278E); "
                    "1er PLT clears north taxiway, 2eme PLT clears hangars + fuel farm. "
                    "BRAVO advances south → OBJ ORANGE (runway 09/27 + south taxiway); "
                    "marks CLP touchdown zone with IR strobes. "
                    "CHARLIE from DZ GREEN clears south perimeter, establishes N237 VCP "
                    "at 52.130N/5.330E NLT H+60. "
                    "CLP (4× C-130H) land RWY 09 from H+60; ECHO CIE CQMS marshals YPR-765 IFVs.\n"
                    "Phase 2 — Mounted Assault on Kazerne (H+95 to H+240):\n"
                    "RECON-TM screens N237 from H+60. "
                    "Column departs airfield NLT H+95: CHARLIE (advance guard), "
                    "RECON (screens), BHQ TAC CP, ALPHA, BRAVO, DELTA AT, ECHO LOG. "
                    "Route: N237 north → left onto N221 → Kazerne approach from west. "
                    "PL TULIP: N221 / Soestdijk junction (BHQ TAC CP holds here). "
                    "PL CARNATION: 500m from Kazerne west gate. "
                    "H+150: CHARLIE secures Kazerne east approach / prevents breakout. "
                    "H+155: FIRE-6 calls fires on Kazerne north gate AT position. "
                    "H+160: ALPHA dismounts 400m from north gate, assault on foot. "
                    "H+160: BRAVO dismounts 400m from west gate, simultaneous breach. "
                    "H+175: both breach points forced; clear compound building by building. "
                    "H+240: OBJ NASSAU secured; CCP active."
                ),
                "main_effort":        "ALPHA CIE — OBJ AMBER (airfield) → Kazerne north gate",
                "supporting_effort":  "BRAVO CIE — OBJ ORANGE (runway) → Kazerne west breach",
                "reserve":            "DELTA CIE AT section; BPT reinforce ALPHA or block QRF",
            },
            "tasks_to_subordinate_units": {
                "ALPHA_CIE": (
                    "MAIN EFFORT. DZ MAROON. Seize OBJ AMBER (terminal + hangars, 52.125N/5.278E) "
                    "NLT H+60. Mark CLP pad RWY 09. Phase 2: mounted assault Kazerne north gate "
                    "(52.162N/5.385E) NLT H+175. PRIORITY OF FIRES both phases."
                ),
                "BRAVO_CIE": (
                    "SUPPORTING. DZ MAROON. Seize OBJ ORANGE (runway 09/27 + S taxiway) NLT H+60. "
                    "Clear runway of obstacles; mark CLP touchdown. "
                    "Phase 2: breach Kazerne west perimeter (52.156N/5.375E) NLT H+175. "
                    "Consolidate on OBJ NASSAU west sector."
                ),
                "CHARLIE_CIE": (
                    "FLANKING / ADVANCE GUARD. DZ GREEN. Clear south perimeter OPFOR NLT H+45. "
                    "Establish N237 VCP (52.130N/5.330E) NLT H+60; block Kazerne QRF. "
                    "Phase 2: lead advance guard on column N237 → N221. "
                    "Secure Kazerne east approach; prevent OPFOR breakout east NLT H+170."
                ),
                "DELTA_CIE": (
                    "FIRE SUPPORT. DZ MAROON. Mortar line (MORT-SEC) occupies "
                    "52.138N/5.280E NLT H+15. Fire plan: FM-001 N gate H-5, "
                    "FM-002 airfield main gate H+0, FM-003 SMOKE east fence H+20. "
                    "Snipers (SNP-A/B): overwatch OBJ AMBER H+15 to H+60; "
                    "redeploy N of Kazerne for Phase 2 overwatch. "
                    "AT-SEC: vehicle-mounted reserve; BPT engage OPFOR armour on N237."
                ),
                "ECHO_CIE": (
                    "HQ / LOGISTICS. RECON-TM jumps DZ MAROON. Screens N237 from H+60. "
                    "Main body flies in H+90. CQMS marshals YPR-765 IFVs off CLP aircraft. "
                    "PION-ALPHA checks airfield for IEDs / obstacles before CLP H+55. "
                    "LOG team establishes ALMA (ammunition/logistics area) at airfield H+90. "
                    "Supports column as echelon B from H+95."
                ),
                "BHQ": (
                    "BN TAC CP at DZ MAROON NLT H+15; advance TAC CP to PL TULIP NLT H+140. "
                    "FIRE-6 coordinates mortar fire plan + CAS (ORANGE 41). "
                    "GHOST-6 fuses PIR on QRF and AT positions. "
                    "Succession: CO → 2IC → ALPHA-6 → BRAVO-6."
                ),
            },
            "coordinating_instructions": [
                f"H-HOUR: {H_HOUR} (RWY 09 axis, westerly run-in).",
                "DZ MAROON: 52.142N/5.280E — BHQ + ALPHA + BRAVO + DELTA.",
                "DZ GREEN:  52.106N/5.310E — CHARLIE CIE (flanking from SE).",
                "PL TULIP: N221/Soestdijk junction — BHQ TAC CP Phase 2.",
                "PL CARNATION: 500m west of Kazerne gate — assault line of departure.",
                "OBJ AMBER:  terminal + hangars at 52.125N/5.278E.",
                "OBJ ORANGE: runway 09/27 + S taxiway (CLP strip).",
                "OBJ NASSAU: Amersfoort Kazerne (Bernhardkazerne compound).",
                "CLP: RWY 09 (eastbound). 4× C-130H, first land H+60. "
                "BRAVO marks touchdown IR strobes. CCT with RECON-TM.",
                "CASEVAC: LZ MAROON (DZ MAROON dual-role), DUSTOFF ANGEL 31, 282.800 MHz. "
                "Phase 2 CASEVAC: LZ TULIP (PL TULIP, BHQ TAC CP).",
                "TRPs: TRP-001=N gate tower; TRP-002=S gate; TRP-003=E fence; "
                "TRP-004=Kazerne N gate AT bunker; TRP-005=Kazerne W gate AT.",
                "PIR: (1) OPFOR armour route from Kazerne to airfield; "
                "(2) N237 QRF composition; (3) Kazerne AT positions.",
                "FFIR: KIA/WIA > 10% any coy; loss of comms > 15 min; "
                "MANPADS active; CLP unable to land H+60.",
                "ROE: PID prior; NO FIRE within 200m of Nationaal Militair Museum. "
                "Kazerne: no area fires — building clearance by fire-teams.",
                "MOPP: MOPP-0; kit carried. Upgrade if CBRN indicators (DELTA-9 CBRN cell).",
            ],
        },
        "sustainment": {
            "logistics": (
                "Jump: 3 days food/water; 600 rds 5.56; 4× AT4 per COY. "
                "YPR-765 vehicles fly in H+60; 72hr ammo/fuel load per vehicle. "
                "ALMA at airfield H+90; LOG-6 manages. "
                "Phase 2: vehicle-mounted 72hr; LOGPAC from BDE H+300."
            ),
            "personnel": (
                "BN AS at FOB Gilze-Rijen — KIA evac by DUSTOFF ANGEL 31 from LZ MAROON / LZ TULIP. "
                "EPW: Soesterberg — RANGER-7 at DZ MAROON; "
                "Kazerne — designated cell (HAMMER-9 coord)."
            ),
            "medical": (
                "Role 1 BAS at DZ MAROON (DOC-6). LZ MAROON freq 282.800 MHz DUSTOFF ANGEL 31. "
                "Phase 2 CCP: PL TULIP (BHQ TAC CP). "
                "Mass casualty: DZ MAROON primary; Kazerne — terminal foyer secondary. "
                "DOC-6 accompanies BHQ throughout; each coy has organic combat medics."
            ),
        },
        "command_signal": {
            "command": (
                "HAMMER-6 jumps DZ MAROON with BHQ. TAC CP at DZ MAROON NLT H+15. "
                "Advance TAC CP to PL TULIP from H+140. "
                "Succession: HAMMER-6 → HAMMER-5 → ALPHA-6 → BRAVO-6."
            ),
            "command_post_locations": (
                "BN TAC CP Phase 1: DZ MAROON (52.142N/5.280E). "
                "BN TAC CP Phase 2: PL TULIP (N221/Soestdijk junction, ~52.148N/5.365E). "
                "ALPHA TAC CP: with 1er PLT at OBJ AMBER on seizure. "
                "BRAVO TAC CP: OBJ ORANGE (runway threshold). "
                "CHARLIE CP: N237 VCP (52.130N/5.330E)."
            ),
            "signal": (
                "PACE: P=SINCGARS BN CMD 36.050 MHz; A=HF 7.430 MHz USB; "
                "C=Arrow chat #market-amber; E=Pyro (Green star=OBJ seized; Red=retrograde DZ MAROON). "
                "ALPHA NET: 36.100 MHz. BRAVO: 36.200. CHARLIE: 36.300. "
                "DELTA FSE: 36.400. ECHO LOG: 36.500. "
                "CAS ORANGE 41: 251.100 MHz. DUSTOFF ANGEL 31: 282.800 MHz. "
                "CCT/CLP: 132.800 MHz. COMSEC: card JUN-26 ACTIVE."
            ),
        },
    }


# ── Tactical graphics ─────────────────────────────────────────────────────────

def build_graphics(mgrs_fn) -> list[dict]:
    air     = LL(*SOESTERBERG)
    kaz     = LL(*KAZERNE)
    dz_m    = LL(*DZ_MAROON_REF)
    dz_g    = LL(*DZ_GREEN_REF)
    bn_tac  = LL(*BN_TAC_CP_AIR)
    pl_tulip = LL(*BN_TAC_CP_KAZ)

    # Key airfield points
    terminal   = air.offset(+50,  -400)    # terminal / admin building
    hangars    = air.offset(-50,  +300)    # hangars east apron
    rwy_09     = air.offset(  0, -1200)    # RWY 09 threshold (west)
    rwy_27     = air.offset(  0, +1300)    # RWY 27 threshold (east)
    tower      = air.offset(+80, -200)     # control tower
    n_gate     = air.offset(+400, -200)    # airfield north gate
    s_gate     = air.offset(-700, -100)    # airfield south gate
    e_gate     = air.offset(+50,  +1200)   # east taxiway exit
    mortar_ln  = air.offset(+1600, -100)   # mortar line (north of DZ MAROON)
    fuel_farm  = air.offset(-300, +100)    # fuel farm

    # Kazerne key points
    kaz_n_gate = kaz.offset(+250, -200)    # north gate (ALPHA target)
    kaz_w_gate = kaz.offset(  0,  -600)    # west gate (BRAVO target)
    kaz_e      = kaz.offset(  0,  +600)    # east perimeter (CHARLIE block)

    # N237 blocking point
    n237_block = LL(*N237_BLOCK)

    def tg(type_: str, ll: LL, *, affil: str = "FRIENDLY", echelon: str = "",
            notes: str = "", rotation: float = 0.0, geometry: str = "",
            sidc: str = "") -> dict:
        return {
            "type": type_, "latitude": ll.lat, "longitude": ll.lon,
            "affiliation": affil, "echelon": echelon, "notes": notes,
            "rotation": rotation, "geometry": geometry,
            "symbol_code": sidc, "visibility": "COMPANY",
        }

    def line(type_: str, pts: list[LL], **kw) -> dict:
        geom = json.dumps({"type": "line", "coords": [p.pair() for p in pts]})
        return tg(type_, pts[0], geometry=geom, **kw)

    def poly(type_: str, pts: list[LL], **kw) -> dict:
        geom = json.dumps({"type": "polygon", "coords": [p.pair() for p in pts]})
        return tg(type_, pts[0], geometry=geom, **kw)

    items: list[dict] = []

    # ── OBJECTIVES ────────────────────────────────────────────────────────────
    items.append(poly("OBJ_AREA", [
        terminal.offset(+200, -300), terminal.offset(+200, +500),
        terminal.offset(-200, +500), terminal.offset(-200, -300),
    ], echelon="COY", notes="OBJ AMBER — terminal complex + hangars (ALPHA CIE main effort)"))

    items.append(poly("OBJ_AREA", [
        air.offset(+80, -1300), air.offset(+80, +1400),
        air.offset(-80, +1400), air.offset(-80, -1300),
    ], echelon="BN", notes="OBJ ORANGE — RWY 09/27 + taxiways (BRAVO seizes for CLP)"))

    items.append(poly("OBJ_AREA", [
        kaz.offset(+400, -700), kaz.offset(+400, +700),
        kaz.offset(-400, +700), kaz.offset(-400, -700),
    ], echelon="BN", notes="OBJ NASSAU — Amersfoort Kazerne / Bernhardkazerne compound"))

    # ── DROP ZONES ────────────────────────────────────────────────────────────
    items.append(poly("OBJ_AREA", [
        dz_m.offset(+400, -600), dz_m.offset(+400, +600),
        dz_m.offset(-400, +600), dz_m.offset(-400, -600),
    ], echelon="PL", notes="DZ MAROON — BHQ / ALPHA / BRAVO / DELTA (H-Hour, 1st pass)"))

    items.append(poly("OBJ_AREA", [
        dz_g.offset(+350, -400), dz_g.offset(+350, +400),
        dz_g.offset(-350, +400), dz_g.offset(-350, -400),
    ], echelon="PL", notes="DZ GREEN — CHARLIE CIE (H-Hour, simultaneous, SE flank)"))

    # ── PHASE LINES ──────────────────────────────────────────────────────────
    items.append(line("PHASE_LINE", [
        air.offset(+500, -1500), air.offset(+500, +1600),
    ], echelon="COY",
    notes="PL MAROON — assembly line after DZ; begin move to airfield objectives"))

    items.append(line("PHASE_LINE", [
        air.offset(+600, -1500), air.offset(-800, -1500),
        air.offset(-800, +1700), air.offset(+600, +1700),
        air.offset(+600, -1500),
    ], echelon="COY",
    notes="PL AMBER — airfield perimeter fence (LOA Phase 1: A COY on seizure)"))

    items.append(line("PHASE_LINE", [
        pl_tulip.offset(0, -2500), pl_tulip.offset(0, +2500),
    ], echelon="BN",
    notes="PL TULIP — BHQ TAC CP Phase 2; assault line of departure Kazerne"))

    items.append(line("PHASE_LINE", [
        kaz_w_gate.offset(0, -600), kaz_n_gate.offset(0, +400),
    ], echelon="COY",
    notes="PL CARNATION — 500m from Kazerne gates; dismount line ALPHA + BRAVO"))

    # ── BN BOUNDARIES ────────────────────────────────────────────────────────
    items.append(line("BOUNDARY", [dz_m, kaz_n_gate],
        echelon="BN",
        notes="ALPHA COY sector boundary — west of centreline (N gate axis)"))
    items.append(line("BOUNDARY", [dz_m.offset(0, +200), kaz_w_gate],
        echelon="BN",
        notes="BRAVO COY sector boundary — east of centreline (W gate axis)"))

    # ── ATTACK AXES ──────────────────────────────────────────────────────────
    items.append(tg("ATK_AXIS", dz_m.bearing(165, 1200), echelon="COY", rotation=165,
        notes="ALPHA axis — DZ MAROON → OBJ AMBER (terminal, bearing 165°)"))
    items.append(tg("ATK_AXIS", dz_m.bearing(175, 1200), echelon="COY", rotation=175,
        notes="BRAVO axis — DZ MAROON → OBJ ORANGE (runway centreline, bearing 175°)"))
    items.append(tg("ATK_AXIS", dz_g.bearing(330, 1400), echelon="COY", rotation=330,
        notes="CHARLIE axis — DZ GREEN → S perimeter → N237 block (bearing 330°)"))
    items.append(tg("ATK_AXIS", pl_tulip.bearing(90, 2500), echelon="BN", rotation=90,
        notes="BN column route — PL TULIP → Kazerne (E, via N221)"))
    items.append(tg("ATK_AXIS", kaz_n_gate.bearing(180, 700), echelon="COY", rotation=180,
        notes="ALPHA Kazerne axis — N gate assault from north (bearing 180°)"))
    items.append(tg("ATK_AXIS", kaz_w_gate.bearing(90, 800), echelon="COY", rotation=90,
        notes="BRAVO Kazerne axis — W gate breach from west (bearing 90°)"))

    # ── WPNS / MORTAR LINE ────────────────────────────────────────────────────
    items.append(tg("DEF_AREA", mortar_ln, echelon="PL", rotation=180,
        notes="DELTA mortar line — 2× 60mm/81mm; overwatch DZ MAROON + OBJs; "
              "redeploy N of Kazerne Phase 2"))

    # ── N237 BLOCKING ─────────────────────────────────────────────────────────
    items.append(poly("DEF_AREA", [
        n237_block.offset(+400, -600), n237_block.offset(+400, +600),
        n237_block.offset(-400, +600), n237_block.offset(-400, -600),
    ], echelon="COY",
    notes="CHARLIE blocking position — N237 VCP/AT ambush; blocks Kazerne QRF to airfield"))

    # ── FLOT / FLET ──────────────────────────────────────────────────────────
    items.append(line("FLOT", [
        air.offset(+500, -1500), air.offset(+500, +1500),
    ], echelon="BN",
    notes="FLOT — 3 PARA / SOR (Phase 1: DZ MAROON assembly, PL MAROON)"))

    items.append(line("FLET", [
        air.offset(+450, -1400), air.offset(+450, +1400),
    ], affil="ENEMY", echelon="BN",
    notes="FLET — OPFOR perimeter guard estimate (airfield fence + patrols)"))

    # ── ENEMY POSITIONS — SOESTERBERG ────────────────────────────────────────
    enemies_air = [
        ("OPFOR observer — control tower",          "SHGPUCRVO---", tower),
        ("OPFOR motorised rifle plt (-)",           "SHGPUCIZ----", air.offset(+100, +50)),
        ("OPFOR BMP-2 — north apron #1",            "SHGPEVAT----", air.offset(+120, -300)),
        ("OPFOR BMP-2 — north apron #2",            "SHGPEVAT----", air.offset(+120, -100)),
        ("OPFOR MANPADS team (mobile)",              "SHGPUCDS----", air.offset(+80, +400)),
        ("OPFOR guard post — north gate",            "SHGPUCIZ----", n_gate),
        ("OPFOR guard post — south gate",            "SHGPUCIZ----", s_gate),
        ("OPFOR guard post — east taxiway",          "SHGPUCIZ----", e_gate),
        ("OPFOR MMG position — south fence",         "SHGPUCFW----", air.offset(-600, +100)),
        ("OPFOR mortar position — hangar area",      "SHGPUCF-----", hangars.offset(+200, 0)),
    ]
    for name, sidc, ll in enemies_air:
        items.append({"type": "ENEMY", "symbol_code": sidc,
            "latitude": ll.lat, "longitude": ll.lon, "affiliation": "ENEMY",
            "notes": name, "echelon": "", "rotation": 0.0, "geometry": "", "visibility": "COMPANY"})

    # ── ENEMY POSITIONS — AMERSFOORT KAZERNE ─────────────────────────────────
    enemies_kaz = [
        ("OPFOR mech inf coy (-) — Kazerne garrison",  "SHGPUCIZ----", kaz),
        ("OPFOR BMP-2 — Kazerne N perimeter #1",       "SHGPEVAT----", kaz.offset(+200, -100)),
        ("OPFOR BMP-2 — Kazerne N perimeter #2",       "SHGPEVAT----", kaz.offset(+200, +200)),
        ("OPFOR BMP-2 — Kazerne W gate",               "SHGPEVAT----", kaz_w_gate),
        ("OPFOR BMP-2 — Kazerne E side reserve",       "SHGPEVAT----", kaz_e),
        ("OPFOR AT bunker — N gate (Fagot/Kornet)",    "SHGPUCAW----", kaz_n_gate.offset(-100, 0)),
        ("OPFOR AT bunker — W gate",                   "SHGPUCAW----", kaz_w_gate.offset(0, +200)),
        ("OPFOR mortar section — barracks courtyard",  "SHGPUCF-----", kaz.offset(-100, +100)),
        ("OPFOR sniper — N water tower",               "SHGPUCRV----", kaz.offset(+350, -50)),
        ("OPFOR QRF route — N237 northbound",          "SHGPUCIZ----", n237_block.offset(0, +1500)),
    ]
    for name, sidc, ll in enemies_kaz:
        items.append({"type": "ENEMY", "symbol_code": sidc,
            "latitude": ll.lat, "longitude": ll.lon, "affiliation": "ENEMY",
            "notes": name, "echelon": "", "rotation": 0.0, "geometry": "", "visibility": "COMPANY"})

    # ── FRIENDLY POIs ─────────────────────────────────────────────────────────
    pois = [
        # Airfield
        ("BN TAC CP — DZ MAROON area",          "SFGPUH------", bn_tac),
        ("LZ MAROON — CASEVAC / DUSTOFF ANGEL 31", "SFGPIBA-----", dz_m.offset(-200, +100)),
        ("CCP Phase 1 — DZ MAROON (DOC-6)",     "SFGPIME-----", dz_m.offset(-200, -200)),
        ("ALMA — ammo/log area (LOG-6, H+90)",  "SFGPIRP-----", air.offset(+800, +200)),
        ("CLP touchzone — RWY 09 threshold",    "SFGPIBA-----", rwy_09.offset(+50, +100)),
        ("Fuel farm — NO DIRECT FIRE",          "SFGPIMH-----", fuel_farm),
        ("Museum (NMM) — NO FIRE ZONE",         "SFGPIBE-----", air.offset(+200, +500)),
        ("PION IED clearance route (pre-CLP)",  "SFGPIBE-----", rwy_09.offset(+50, +300)),
        # Kazerne approach
        ("BN TAC CP Phase 2 — PL TULIP",        "SFGPUH------", pl_tulip),
        ("CCP Phase 2 — PL TULIP (MEDEVAC)",    "SFGPIME-----", pl_tulip.offset(-200, 0)),
        ("LZ TULIP — Phase 2 CASEVAC",          "SFGPIBA-----", pl_tulip.offset(+300, -300)),
        ("CHARLIE blocking OP — N237",          "SFGPUH------", n237_block),
        ("RECON screen OP — N237/N221 jct",     "SFGPUH------", n237_block.offset(+500, +1000)),
        ("OBJ NASSAU assault LD — N gate",      "SFGPUBE-----", kaz_n_gate.offset(+500, 0)),
        ("OBJ NASSAU assault LD — W gate",      "SFGPUBE-----", kaz_w_gate.offset(0, -500)),
    ]
    for name, sidc, ll in pois:
        items.append({"type": "POI", "symbol_code": sidc,
            "latitude": ll.lat, "longitude": ll.lon, "affiliation": "FRIENDLY",
            "notes": name, "echelon": "", "rotation": 0.0, "geometry": "", "visibility": "COMPANY"})

    # ── SUB-OBJECTIVES ────────────────────────────────────────────────────────
    # Airfield sub-objectives
    items.append(poly("OBJ_AREA", [
        terminal.offset(+150, -330), terminal.offset(+150, -50),
        terminal.offset(-80,  -50),  terminal.offset(-80,  -330),
    ], echelon="PL", notes="OBJ AMBER NORTH — control tower + admin block (ALPHA-11 1er PLT)"))

    items.append(poly("OBJ_AREA", [
        hangars.offset(+150, -100), hangars.offset(+150, +400),
        hangars.offset(-150, +400), hangars.offset(-150, -100),
    ], echelon="PL", notes="OBJ AMBER EAST — hangars + east taxiway (ALPHA-21 2eme PLT)"))

    items.append(poly("OBJ_AREA", [
        rwy_09.offset(+60, +50), rwy_09.offset(+60, +600),
        rwy_09.offset(-60, +600), rwy_09.offset(-60, +50),
    ], echelon="PL", notes="OBJ ORANGE WEST — RWY 09 threshold + CLP touchdown zone (BRAVO)"))

    # Kazerne sub-objectives
    items.append(poly("OBJ_AREA", [
        kaz.offset(+400, -700), kaz.offset(+400, 0),
        kaz.offset(-50,  0),    kaz.offset(-50,  -700),
    ], echelon="COY", notes="OBJ NASSAU WEST — admin/vehicle park (BRAVO breach W gate)"))

    items.append(poly("OBJ_AREA", [
        kaz.offset(+400, 0),   kaz.offset(+400, +700),
        kaz.offset(-50,  +700), kaz.offset(-50,  0),
    ], echelon="COY", notes="OBJ NASSAU EAST — barracks/command block (ALPHA breach N gate)"))

    items.append(poly("OBJ_AREA", [
        kaz.offset(-50, -700), kaz.offset(-50,  +700),
        kaz.offset(-400, +700), kaz.offset(-400, -700),
    ], echelon="PL", notes="OBJ NASSAU SOUTH — motor pool + EPW holding (CHARLIE secures)"))

    # Route waypoints
    items.append(tg("POI", n237_block.offset(+800, +400), echelon="PL", sidc="SFGPIBE-----",
        notes="WP AMBER-1 — N237/N221 junction; column turns N toward Amersfoort"))
    items.append(tg("POI", pl_tulip.offset(0, +800), echelon="PL", sidc="SFGPIBE-----",
        notes="WP AMBER-2 — Soestdijk bridge crossing; PION-ALPHA clears for mines"))

    # ── JACKAL SCREEN POSITIONS ───────────────────────────────────────────────
    jackal_screen_1 = n237_block.offset(+1200, +800)   # screen OP east of N237 block
    jackal_screen_2 = n237_block.offset(+600, +1400)   # screen OP covering N221 approach
    jackal_screen_3 = kaz.offset(-300, +1200)           # screen OP east of Kazerne
    jackal_fwd      = pl_tulip.offset(+400, +1800)      # forward screen at PL CARNATION

    jackal_pois = [
        ("Jackal 1 — screen OP N237 east flank",  jackal_screen_1),
        ("Jackal 2 — screen OP N221 approach",    jackal_screen_2),
        ("Jackal 3 — screen E of Kazerne",        jackal_screen_3),
        ("Jackal 4 — fwd screen PL CARNATION",    jackal_fwd),
    ]
    for name, ll in jackal_pois:
        items.append({"type": "POI", "symbol_code": "SFGPUCV-----",
            "latitude": ll.lat, "longitude": ll.lon, "affiliation": "FRIENDLY",
            "notes": name, "echelon": "PL", "rotation": 0.0, "geometry": "", "visibility": "COMPANY"})

    # ── UNIMOG / VEHICLE SYMBOLS ──────────────────────────────────────────────
    alma = air.offset(+700, +200)
    unimog_pois = [
        ("Unimog 1 — ALMA stores/ammo",   alma.offset(0, 0)),
        ("Unimog 2 — ALMA fuel tanker",   alma.offset(0, +80)),
        ("Unimog 3 — med resupply truck", alma.offset(0, -80)),
        ("YPR-765 #1 — ALPHA CIE IFV",   air.offset(+300, -300)),
        ("YPR-765 #2 — BRAVO CIE IFV",   air.offset(+300, -150)),
        ("YPR-765 #3 — CHARLIE CIE IFV", air.offset(+300, 0)),
        ("YPR-765 #4 — DELTA AT reserve", air.offset(+300, +150)),
    ]
    for name, ll in unimog_pois:
        sidc = "SFGPUCV-----"
        items.append({"type": "POI", "symbol_code": sidc,
            "latitude": ll.lat, "longitude": ll.lon, "affiliation": "FRIENDLY",
            "notes": name, "echelon": "", "rotation": 0.0, "geometry": "", "visibility": "COMPANY"})

    # ── FRIENDLY UAV / DRONE ──────────────────────────────────────────────────
    uav_pos = dz_m.offset(-300, +400)   # UAV-1 GCS position (S2 cell)
    items.append({"type": "POI", "symbol_code": "SFGPCA------",
        "latitude": uav_pos.lat, "longitude": uav_pos.lon, "affiliation": "FRIENDLY",
        "notes": "UAV GCS — UAV-1 (BHQ S2 cell); RQ-11B Raven mini-UAV ISR over route corridor",
        "echelon": "", "rotation": 0.0, "geometry": "", "visibility": "COMPANY"})

    # ── ENEMY AMBUSH POSITION — N237 ─────────────────────────────────────────
    ambush_pos = n237_block.offset(+200, +900)  # ambush on N237 between VCP + Amersfoort
    items.append({"type": "ENEMY", "symbol_code": "SHGPUCIZ----",
        "latitude": ambush_pos.lat, "longitude": ambush_pos.lon, "affiliation": "ENEMY",
        "notes": "OPFOR ambush line — N237 culvert/treeline; est. 1 sect + PKM MMG + RPG × 2",
        "echelon": "PL", "rotation": 0.0, "geometry": "", "visibility": "COMPANY"})
    items.append({"type": "ENEMY", "symbol_code": "SHGPUCFW----",
        "latitude": ambush_pos.offset(+50, +80).lat,
        "longitude": ambush_pos.offset(+50, +80).lon, "affiliation": "ENEMY",
        "notes": "OPFOR PKM MMG — ambush fire position N237 E side (enfilade)",
        "echelon": "", "rotation": 0.0, "geometry": "", "visibility": "COMPANY"})

    # ── ENEMY ISR DRONE ───────────────────────────────────────────────────────
    enemy_drone = n237_block.offset(+400, +600)
    items.append({"type": "ENEMY", "symbol_code": "SHGPCA------",
        "latitude": enemy_drone.lat, "longitude": enemy_drone.lon, "affiliation": "ENEMY",
        "notes": "OPFOR ISR drone — small quadcopter (DJI-type), conducting route recon N237; "
                 "spotted by UAV-1 at H+80 (pattern of life pre-ambush); altitude ~60m AGL",
        "echelon": "", "rotation": 0.0, "geometry": "", "visibility": "COMPANY"})

    # ── 81MM MORTAR LINE (PHASE 2) ────────────────────────────────────────────
    mort_kaz = kaz.offset(+800, -400)   # mortar line north of Kazerne Phase 2
    items.append(tg("DEF_AREA", mort_kaz, echelon="PL", rotation=180,
        notes="DELTA mortar line Phase 2 — 81mm × 2 tubes; "
              "TRPs 004/005 Kazerne gates; illumination on call Phase 2 night ops"))

    return items


# ── Fire plan ─────────────────────────────────────────────────────────────────

def build_fire_plan() -> list[dict]:
    air    = LL(*SOESTERBERG)
    kaz    = LL(*KAZERNE)
    n_gate = air.offset(+400, -200)
    s_gate = air.offset(-700, -100)
    e_fence = air.offset(+100, +900)
    kaz_n  = kaz.offset(+250, -200)
    kaz_w  = kaz.offset(  0,  -600)

    return [
        {
            "latitude": n_gate.lat, "longitude": n_gate.lon,
            "altitude": 10.0, "direction": 180.0,
            "mission_type": "SUPPRESSION", "ammunition": "HE", "quantity": 8,
            "description": "FM-001 TRP-001 — suppress OPFOR N gate tower / guard post (H-5 to H+0)",
        },
        {
            "latitude": s_gate.lat, "longitude": s_gate.lon,
            "altitude": 5.0, "direction": 180.0,
            "mission_type": "SUPPRESSION", "ammunition": "HE", "quantity": 6,
            "description": "FM-002 TRP-002 — suppress OPFOR S gate before CHARLIE approach (H+0 to H+15)",
        },
        {
            "latitude": e_fence.lat, "longitude": e_fence.lon,
            "altitude": 5.0, "direction": 270.0,
            "mission_type": "ADJUST_FIRE", "ammunition": "SMOKE", "quantity": 4,
            "description": "FM-003 TRP-003 — SMOKE screen E fence before ALPHA 2eme PLT breach (H+20)",
        },
        {
            "latitude": kaz_n.lat, "longitude": kaz_n.lon,
            "altitude": 10.0, "direction": 180.0,
            "mission_type": "FIRE_FOR_EFFECT", "ammunition": "HE", "quantity": 12,
            "description": "FM-004 TRP-004 — destroy OPFOR AT bunker N gate Kazerne (H+155 prior ALPHA assault)",
        },
        {
            "latitude": kaz_w.lat, "longitude": kaz_w.lon,
            "altitude": 5.0, "direction": 90.0,
            "mission_type": "SUPPRESSION", "ammunition": "MIXED", "quantity": 8,
            "description": "FM-005 TRP-005 — 81mm suppress OPFOR W gate AT + BMP-2 before BRAVO breach (H+158)",
        },
        {
            "latitude": air.offset(-600, +100).lat, "longitude": air.offset(-600, +100).lon,
            "altitude": 5.0, "direction": 0.0,
            "mission_type": "SUPPRESSION", "ammunition": "SMOKE",  "quantity": 6,
            "description": "FM-006 TRP-S-GATE — 81mm SMOKE screen S gate; CHARLIE advance from DZ GREEN (H+05)",
        },
        {
            # N237 ambush position
            "latitude": LL(*N237_BLOCK).offset(+200, +900).lat,
            "longitude": LL(*N237_BLOCK).offset(+200, +900).lon,
            "altitude": 5.0, "direction": 270.0,
            "mission_type": "FIRE_FOR_EFFECT", "ammunition": "HE",  "quantity": 16,
            "description": "FM-007 TRP-AMBUSH — 81mm FFE on OPFOR ambush position N237 culvert; "
                           "immediate response to TIC report (H+105 est.)",
        },
        {
            # Illumination over Kazerne approach (night ops Phase 2)
            "latitude": kaz.offset(+600, 0).lat, "longitude": kaz.offset(+600, 0).lon,
            "altitude": 300.0, "direction": 180.0,
            "mission_type": "SUPPRESSION", "ammunition": "ILLUM",  "quantity": 4,
            "description": "FM-008 ILLUM-KAZ — 81mm illumination over Kazerne approach; "
                           "support ALPHA/BRAVO dismounted assault (H+160, 30-sec burn each)",
        },
        {
            # Mortar-specific: 60mm smoke for recce extract
            "latitude": LL(*N237_BLOCK).offset(+500, +1000).lat,
            "longitude": LL(*N237_BLOCK).offset(+500, +1000).lon,
            "altitude": 5.0, "direction": 90.0,
            "mission_type": "ADJUST_FIRE", "ammunition": "SMOKE",  "quantity": 3,
            "description": "FM-009 SMOKE-RECCE — 81mm SMOKE to extract JACKAL screen OP "
                           "under enemy drone surveillance N237/N221 (H+85)",
        },
    ]


# ── Vehicles ─────────────────────────────────────────────────────────────────

def build_vehicles(api: Api, admin_tok: str,
                   by_cs: dict[str, OpRoster],
                   teams: dict[str, int]) -> dict[str, int]:
    """Register all BN vehicles linked to operators/teams. Returns {callsign: id}."""

    def _v(callsign: str, vtype: str, sidc: str, notes: str,
           op: str | None = None, team: str | None = None) -> dict:
        body: dict = {
            "callsign": callsign, "vehicle_type": vtype,
            "symbol_code": sidc, "affiliation": "FRIENDLY",
            "ops_status": "OPS", "notes": notes,
        }
        if op and by_cs.get(op) and by_cs[op].op_id:
            body["operator_id"] = by_cs[op].op_id
        if team and teams.get(team):
            body["team_id"] = teams[team]
        return body

    specs = [
        # ── BHQ — Land Rover Wolf ─────────────────────────────────────────────
        _v("BN-LR-CO",  "Land Rover Wolf 130",  "SFGPUCV-----",
           "BN CO vehicle — HAMMER-6; HF/VHF comms fit; BN TAC CP",          op="HAMMER-6"),
        _v("BN-LR-XO",  "Land Rover Wolf 130",  "SFGPUCV-----",
           "BN 2IC vehicle — HAMMER-5; BN advance party Phase 2",             op="HAMMER-5"),
        _v("BN-LR-SIG", "Land Rover Wolf 130",  "SFGPUCV-----",
           "BN Sigs vehicle — RADIO-6; comms relay + BN CP",                  op="RADIO-6"),
        _v("BN-LR-MED", "Land Rover Wolf 130",  "SFGPUCV-----",
           "BN MO vehicle — DOC-6; Role 1 BAS + CCP coordination",            op="DOC-6"),

        # ── YPR-765 IFVs — fly-in H+90 ───────────────────────────────────────
        _v("ALPHA-V1",   "YPR-765 AIFV",        "SFGPUCEV----",
           "ALPHA CIE IFV — troop carrier; commander ALPHA-6; "
           "FN MAG + 25mm Oerlikon; 8 pax capacity",                          op="ALPHA-6",   team="ALPHA-HQ"),
        _v("ALPHA-V2",   "YPR-765 AIFV",        "SFGPUCEV----",
           "ALPHA CIE IFV #2 — ALPHA-11 1er PLT carrier",                     op="ALPHA-11",  team="A1PLT-HQ"),
        _v("BRAVO-V1",   "YPR-765 AIFV",        "SFGPUCEV----",
           "BRAVO CIE IFV — troop carrier; commander BRAVO-6; "
           "fly-in H+90 with ECHO CIE CLP",                                   op="BRAVO-6",   team="BRAVO-HQ"),
        _v("BRAVO-V2",   "YPR-765 AIFV",        "SFGPUCEV----",
           "BRAVO CIE IFV #2 — BRAVO-11 1er PLT carrier",                     op="BRAVO-11",  team="B1PLT-HQ"),
        _v("CHARLIE-V1", "YPR-765 AIFV",        "SFGPUCEV----",
           "CHARLIE CIE IFV — advance guard vehicle; leads column Phase 2",   op="CHARLIE-6", team="CHARLIE-HQ"),
        _v("DELTA-V1",   "YPR-765 AIFV",        "SFGPUCEV----",
           "DELTA CIE fire support IFV — AT reserve; MORT-5 FOO on board",    op="DELTA-6",   team="DELTA-HQ"),

        # ── Jackal MWMIK — recce screen ───────────────────────────────────────
        _v("JACKAL-V1",  "Jackal 2 MWMIK",      "SFGPUCV-----",
           "Jackal 1 — JACKAL-1/2 crew; HMG M2 + GPMG; fwd screen N237",     op="JACKAL-1",  team="JACKAL-SEC"),
        _v("JACKAL-V2",  "Jackal 2 MWMIK",      "SFGPUCV-----",
           "Jackal 2 — JACKAL-3/4 crew; IED mobility kill N237 ambush H+105 "
           "[INOPS — awaiting recovery UNIMOG-V3]",                            op="JACKAL-3",  team="JACKAL-SEC"),
        _v("JACKAL-V3",  "Jackal 2 MWMIK",      "SFGPUCV-----",
           "Jackal 3 — JACKAL-5/6 crew; HMG M2; flanking screen E of Kazerne",op="JACKAL-5",  team="JACKAL-SEC"),
        _v("JACKAL-V4",  "Jackal 2 MWMIK",      "SFGPUCV-----",
           "Jackal 4 — JACKAL-7/8 crew; GPMG; PL CARNATION fwd OP",          op="JACKAL-7",  team="JACKAL-SEC"),

        # ── Unimogs — logistics fly-in ────────────────────────────────────────
        _v("UNIMOG-V1",  "Mercedes Unimog U4000","SFGPUCV-----",
           "Unimog 1 — ALMA stores/ammo; UNIMOG-1 driver; LOG-6 coord",       op="UNIMOG-1",  team="UNIMOG-SEC"),
        _v("UNIMOG-V2",  "Mercedes Unimog U4000","SFGPUCV-----",
           "Unimog 2 — fuel tanker (1,500L); UNIMOG-2 driver",                op="UNIMOG-2",  team="UNIMOG-SEC"),
        _v("UNIMOG-V3",  "Mercedes Unimog U4000","SFGPUCV-----",
           "Unimog 3 — recovery/tow vehicle + med resupply; "
           "tasked recovery JACKAL-V2 (IED mobility kill N237)",               op="UNIMOG-3",  team="UNIMOG-SEC"),

        # ── DUSTOFF helicopter ────────────────────────────────────────────────
        _v("DUSTOFF-31", "NH-90 TTH (CASEVAC)",  "SFGPMFF-----",
           "DUSTOFF ANGEL 31 — NH-90 TTH; 282.800 MHz; "
           "2 litter + 4 sitting; FOB Gilze-Rijen; DOC-6 coordinates CASEVAC",op="DOC-6"),

        # ── Pioneer Unimog ────────────────────────────────────────────────────
        _v("PION-V1",    "Mercedes Unimog U4000","SFGPUCV-----",
           "Pioneer vehicle — PION-6/1; EOD/IED kit; pre-CLP route clearance",op="PION-6",    team="PION-ALPHA"),
    ]

    vid: dict[str, int] = {}
    ok = 0
    for spec in specs:
        try:
            r = api.post("/vehicles", admin_tok, spec)
            vid[spec["callsign"]] = r["id"]      # type: ignore[index]
            ok += 1
        except Exception as exc:
            log.warning("vehicle %s failed: %s", spec["callsign"], exc)

    # Mark JACKAL-V2 as INOPS immediately (IED mobility kill during setup)
    if "JACKAL-V2" in vid:
        try:
            api.patch(f"/vehicles/{vid['JACKAL-V2']}", admin_tok,
                      {"ops_status": "INOPS",
                       "notes": "IED mobility kill — N237 ambush H+105; "
                                "awaiting tow by UNIMOG-V3; crew evacuated"})
        except Exception:
            pass

    log.info("vehicles created: %d/%d  (JACKAL-V2 marked INOPS)", ok, len(specs))
    return vid


# ── LOGREP reports ────────────────────────────────────────────────────────────

def submit_logreps(api: Api, by_cs: dict[str, OpRoster],
                   admin_tok: str) -> None:
    """File two phased LOGREPs: post-airfield seizure (H+95) and post-Kazerne (H+200)."""
    log6 = by_cs.get("LOG-6")
    # Use LOG-6 token when available; fall back to admin (valid for any operator-scope endpoint)
    tok = (log6.token if log6 and log6.token else None) or admin_tok
    if not tok:
        log.warning("no token available — skipping LOGREPs")
        return

    # ── LOGREP-01 — post Phase 1 / pre-column departure (H+95) ──────────────
    logrep1: dict = {
        "type": "LOGREP",
        "payload": {
            "serial":      "26-003-LOGREP-01",
            "dtg":         "101955ZJUN26",
            "higher_hq":   "BDE LOG / TF MARKET AMBER",
            "period_from": "101800ZJUN26",
            "period_to":   "101955ZJUN26",
            "section_a": {
                "authorised":    79,
                "present":       75,
                "kia":           0,
                "wia_evacuated": 2,   # ALPHA-112 + JACKAL-3
                "wia_duty":      2,   # JACKAL-4 concussion + minor
                "missing":       0,
                "sick":          0,
                "remarks": (
                    "ALPHA-112: GSW chest, evacuated DUSTOFF ANGEL 31 to Role 2 Gilze-Rijen. "
                    "JACKAL-3: blast trauma lower limbs, evacuated same sortie. "
                    "JACKAL-4: blast concussion, returned to duty at LZ MAROON."
                ),
            },
            "section_b": {
                "class_i_days":         2.5,
                "class_iii_litres":     620,
                "class_iii_b_litres":   0,
                "class_v": [
                    {"item": "5.56mm ball",    "uom": "rds",   "on_hand": 14200, "required": 24000, "shortfall": 9800},
                    {"item": "81mm HE",        "uom": "rds",   "on_hand": 44,    "required": 80,    "shortfall": 36},
                    {"item": "81mm SMOKE",     "uom": "rds",   "on_hand": 18,    "required": 24,    "shortfall": 6},
                    {"item": "AT4 rocket",     "uom": "ea",    "on_hand": 9,     "required": 12,    "shortfall": 3},
                    {"item": "GPMG 7.62mm",   "uom": "rds",   "on_hand": 3800,  "required": 6000,  "shortfall": 2200},
                    {"item": "HMG .50 BMG",    "uom": "rds",   "on_hand": 1400,  "required": 2000,  "shortfall": 600},
                ],
                "class_viii": (
                    "CCP expended: morphine × 4 syrettes, TQ × 2, chest seal × 1, "
                    "pressure dressing × 8, cric kit × 1. Blood: O+ × 4 units "
                    "(all used — URGENT resupply required). IV fluids × 6 bags."
                ),
                "class_ix_shortfalls": "Jackal run-flat insert (×4) required for JACKAL-V2 when recovered.",
            },
            "section_c": [
                {"callsign": "JACKAL-V2", "type": "Jackal 2 MWMIK",
                 "status": "INOPS", "fault": "IED blast mobility kill — L front axle + engine bay; "
                                             "crew out; awaiting tow UNIMOG-V3"},
            ],
            "section_d": {
                "deadlined":          1,
                "short_term_repair":  0,
                "awaiting_evac":      1,
                "recovery_requested": ["JACKAL-V2 (N237 ambush site, grid 31UFT 5760 7810)"],
                "notes": (
                    "UNIMOG-V3 tasked recovery JACKAL-V2 once column clears ambush site. "
                    "PION-V1 cleared IED threat on N237 before Kazerne approach."
                ),
            },
            "section_e": {
                "cas_this_period": 4,
                "cas_total":       4,
                "evacuated":       2,
                "on_duty_wia":     2,
                "role_1_active":   True,
                "ccp_location":    "LZ MAROON, DZ MAROON area (52.138N/5.279E)",
                "dustoff_sorties": 1,
                "notes": (
                    "DUSTOFF ANGEL 31 extracted 2× litter from LZ MAROON at H+30 "
                    "and H+108 (Jackal blast). Role 1 BAS (DOC-6) operational at BN AID POST. "
                    "Blood O+ resupply PRIORITY."
                ),
            },
            "section_f": [
                {"priority": "URGENT",  "item": "Blood O+",       "quantity": 6,     "unit": "units",
                 "reason": "CCP resupply — all stock expended; 2 further cas expected Phase 2"},
                {"priority": "URGENT",  "item": "81mm HE",        "quantity": 36,    "unit": "rds",
                 "reason": "Phase 2 Kazerne fire plan FM-004/005 requires 20 rds; resupply before H+155"},
                {"priority": "PRIORITY","item": "5.56mm ball",    "quantity": 9800,  "unit": "rds",
                 "reason": "Kazerne assault resupply; current state 14,200 rds insufficient for clearing"},
                {"priority": "PRIORITY","item": "GPMG 7.62mm",    "quantity": 2200,  "unit": "rds",
                 "reason": "Jackal screen + support weapons Phase 2"},
                {"priority": "ROUTINE", "item": "AT4 rocket",     "quantity": 3,     "unit": "ea",
                 "reason": "AT reserve replacement for Phase 2 BMP threat"},
                {"priority": "ROUTINE", "item": "Jackal run-flat","quantity": 4,     "unit": "ea",
                 "reason": "JACKAL-V2 repair when recovered"},
            ],
            "section_g": (
                "Phase 1 complete — OBJ AMBER and OBJ ORANGE seized NLT H+60. "
                "CLP fly-in 4× C-130H complete H+90; YPR-765 × 6, Unimog × 3, Jackal × 4 off-loaded. "
                "1× Jackal mobility kill (IED N237 ambush H+105) — INOPS, recovery tasked. "
                "2× cas evacuated DUSTOFF ANGEL 31 (H+30 and H+108). "
                "Column departs NLT H+95. LOG-6 requests LOGPAC via second CLP sortie H+240. "
                "Priority shortfalls: Blood O+ URGENT; 81mm HE URGENT before Phase 2 fire plan."
            ),
        },
    }

    r1 = api.post("/reports", tok, logrep1)
    r1_id = r1.get("id") if r1 else None          # type: ignore[union-attr]
    log.info("LOGREP-01 filed by LOG-6 (H+95 post-airfield, id=%s)", r1_id)

    # Acknowledge and process LOGREP-01 as BN S4 (admin)
    if r1_id:
        try:
            api.patch(f"/reports/{r1_id}", admin_tok,
                      {"status": "ACKNOWLEDGED",
                       "reviewer_note": "LOGREP-01 received BN S4 (OPS-6). "
                                        "Blood O+ URGENT forwarded to BDE LOG. "
                                        "81mm resupply on second CLP confirmed. "
                                        "JACKAL-V2 recovery approved."})
        except Exception as exc:
            log.warning("LOGREP-01 ack failed: %s", exc)

    # ── LOGREP-02 — post Phase 2 / OBJ NASSAU consolidated (H+200) ───────────
    logrep2: dict = {
        "type": "LOGREP",
        "payload": {
            "serial":      "26-003-LOGREP-02",
            "dtg":         "102200ZJUN26",
            "higher_hq":   "BDE LOG / TF MARKET AMBER",
            "period_from": "101955ZJUN26",
            "period_to":   "102200ZJUN26",
            "section_a": {
                "authorised":    79,
                "present":       74,
                "kia":           0,
                "wia_evacuated": 4,   # +BRAVO-112, +BRAVO-113 added Phase 2
                "wia_duty":      1,
                "missing":       0,
                "sick":          0,
                "remarks": (
                    "BRAVO-112: GSW arm + abdomen, evacuated DUSTOFF ANGEL 31 LZ TULIP H+190. "
                    "BRAVO-113: blast concussion, evacuated same sortie. "
                    "All 4 evacuated stable at Role 2 Gilze-Rijen per last report."
                ),
            },
            "section_b": {
                "class_i_days":     1.8,
                "class_iii_litres": 180,
                "class_v": [
                    {"item": "5.56mm ball",  "uom": "rds", "on_hand": 6800,  "required": 12000, "shortfall": 5200},
                    {"item": "81mm HE",      "uom": "rds", "on_hand": 12,    "required": 40,    "shortfall": 28},
                    {"item": "AT4 rocket",   "uom": "ea",  "on_hand": 4,     "required": 8,     "shortfall": 4},
                    {"item": "GPMG 7.62mm",  "uom": "rds", "on_hand": 900,   "required": 3000,  "shortfall": 2100},
                ],
                "class_viii": (
                    "CCP phase 2 expended: morphine × 6, TQ × 3, chest seal × 2, IV × 8. "
                    "Blood stock zero — 2nd DUSTOFF resupply requested."
                ),
            },
            "section_c": [
                {"callsign": "JACKAL-V2", "type": "Jackal 2 MWMIK",
                 "status": "INOPS", "fault": "Recovered by UNIMOG-V3 H+130; "
                                             "on airfield awaiting REME recovery team"},
                {"callsign": "BRAVO-V1", "type": "YPR-765 AIFV",
                 "status": "INOPS", "fault": "RPG strike W gate Kazerne H+172; "
                                             "engine fire suppressed; 1× crew WIA (BRAVO-112)"},
            ],
            "section_d": {
                "deadlined":          2,
                "short_term_repair":  1,
                "notes": (
                    "BRAVO-V1 RPG strike — engine and L track; REME recovery + repair est. 48h. "
                    "JACKAL-V2 on airfield pad — REME recovery team requested via BDE LOG."
                ),
            },
            "section_e": {
                "cas_this_period": 4,
                "cas_total":       8,
                "evacuated":       4,
                "on_duty_wia":     1,
                "dustoff_sorties": 2,
                "notes": (
                    "DUSTOFF ANGEL 31 sortie 2: LZ TULIP H+190, extracted BRAVO-112 + BRAVO-113. "
                    "All 4 total evacuees confirmed stable at Role 2. "
                    "BN CCP (DOC-6) now at Kazerne courtyard (OBJ NASSAU). "
                    "Blood O+ zero — URGENT resupply required next LOGPAC."
                ),
            },
            "section_f": [
                {"priority": "URGENT",  "item": "Blood O+/A-",    "quantity": 8,   "unit": "units",
                 "reason": "Zero stock — EPW processing + consolidation phase"},
                {"priority": "URGENT",  "item": "5.56mm ball",    "quantity": 5200,"unit": "rds",
                 "reason": "Consolidation defence; below minimum hold"},
                {"priority": "URGENT",  "item": "81mm HE",        "quantity": 28,  "unit": "rds",
                 "reason": "DF plan on OBJ NASSAU perimeter requires 30 rds minimum"},
                {"priority": "PRIORITY","item": "AT4 rocket",     "quantity": 4,   "unit": "ea",
                 "reason": "Remaining OPFOR armour threat on N237 east"},
                {"priority": "ROUTINE", "item": "Rat packs (24h)","quantity": 100, "unit": "ea",
                 "reason": "3-day hold requirement + EPW feeding"},
            ],
            "section_g": (
                "OBJ NASSAU secured H+240. OPFOR garrison destroyed or captured — est. 45 PAX EPW, "
                "4× BMP-2 destroyed/captured in compound. "
                "2× BN vehicles deadlined (JACKAL-V2 IED, BRAVO-V1 RPG). "
                "N237 corridor open; CHARLIE holding N perimeter. "
                "BDE follow-on forces requested NLT H+360. "
                "LOG-6 requests LOGPAC (blood, 81mm, 5.56mm) on DUSTOFF-31 return sortie. "
                "REME recovery team for BRAVO-V1 and JACKAL-V2 required within 24h."
            ),
        },
    }

    r2 = api.post("/reports", tok, logrep2)
    r2_id = r2.get("id") if r2 else None          # type: ignore[union-attr]
    log.info("LOGREP-02 filed by LOG-6 (H+200 post-Kazerne, id=%s)", r2_id)

    if r2_id:
        try:
            api.patch(f"/reports/{r2_id}", admin_tok,
                      {"status": "ACKNOWLEDGED",
                       "reviewer_note": "LOGREP-02 received BN S4. "
                                        "Blood URGENT passed to BDE — LOGPAC authorised H+300. "
                                        "REME recovery team requested via BDE MAINT. "
                                        "5.56mm + 81mm on LOGPAC manifest."})
        except Exception as exc:
            log.warning("LOGREP-02 ack failed: %s", exc)


# ── CAS asset + 9-liners ──────────────────────────────────────────────────────

def build_cas(api: Api, admin_tok: str, by_cs: dict[str, OpRoster]) -> None:
    air  = LL(*SOESTERBERG)
    kaz  = LL(*KAZERNE)
    mgrs = sim_utils.mgrs

    # Register CAS asset ORANGE 41
    try:
        api.post("/cas/assets", admin_tok, {
            "callsign":      "ORANGE 41",
            "aircraft_type": "F-16AM (Falkcon)",
            "ordnance":      "2× LGB GBU-12 + 20mm M61; 2-ship",
            "frequency":     "251.100 MHz",
            "status":        "ON_STATION",
            "notes":         "RNLAF F-16AM pair; loiter vic 52.30N/5.00E; 40-min playtime per ship",
        })
        log.info("CAS asset ORANGE 41 registered")
    except Exception as e:
        log.warning("CAS asset failed: %s", e)

    fire_6 = by_cs.get("FIRE-6")
    if not fire_6 or not fire_6.token:
        return

    # 9-liner 1 — enemy BMP-2 at airfield N gate threatening ALPHA advance (H+35)
    bmp_pos = air.offset(+120, -280)
    try:
        api.c.post(api._p("/cas/requests"), json={
            "line_1": f"IP: DZ MAROON — {mgrs(LL(*DZ_MAROON_REF).lat, LL(*DZ_MAROON_REF).lon)}",
            "line_2": "Bearing 175° / 2.3 km from IP",
            "line_3": "8m MSL",
            "line_4": "2× BMP-2 — mechanised infantry carriers, moving N apron",
            "line_5_mgrs": mgrs(bmp_pos.lat, bmp_pos.lon),
            "line_5_lat":  bmp_pos.lat,
            "line_5_lon":  bmp_pos.lon,
            "line_6": "IR pointer (FIRE-6 with ALPHA 1er PLT)",
            "line_7": f"ALPHA-11 holding 400m north at {mgrs(air.offset(+500,-280).lat, air.offset(+500,-280).lon)}",
            "line_8": "West egress over open heath",
            "line_9": "TIC — 2× BMP-2 threatening ALPHA advance on OBJ AMBER; "
                      "friendlies 400m north. WP 30 secs prior marking. "
                      "MANPADS threat in area — approach from WEST. ROE PID confirmed.",
            "tic": True,
            "fo_operator_id": fire_6.op_id,
        }, headers={"Authorization": f"Bearer {fire_6.token}",
                    "X-Mission-ID": str(api.mission_id)})
        log.info("CAS 9-liner 1 filed: BMP-2 N apron Soesterberg (TIC)")
    except Exception as e:
        log.warning("CAS 9-liner 1 failed: %s", e)

    # 9-liner 2 — AT bunker Kazerne N gate (H+155, pre-assault fire)
    at_pos = kaz.offset(+250, -220)
    try:
        api.c.post(api._p("/cas/requests"), json={
            "line_1": f"IP: PL TULIP — {mgrs(LL(*BN_TAC_CP_KAZ).lat, LL(*BN_TAC_CP_KAZ).lon)}",
            "line_2": "Bearing 095° / 2.1 km from IP",
            "line_3": "14m MSL",
            "line_4": "AT bunker — Kazerne N gate; confirmed Fagot ATGM + dismount infantry",
            "line_5_mgrs": mgrs(at_pos.lat, at_pos.lon),
            "line_5_lat":  at_pos.lat,
            "line_5_lon":  at_pos.lon,
            "line_6": "Laser (LTGR — FIRE-6 designating from N)",
            "line_7": f"ALPHA-11 assault force 600m north at {mgrs(kaz.offset(+850,-200).lat, kaz.offset(+850,-200).lon)}",
            "line_8": "East egress over fields",
            "line_9": "Pre-assault fire — time on target H+155. "
                      "Kazerne buildings 200m south — NO DAMAGE WEST building (civilian). "
                      "Friendlies 600m north; ALPHA assault begins H+160. "
                      "Request LGB strike AT bunker only. MANPADS not observed in Kazerne. "
                      "ROE: positive ID bunker structure confirmed by GHOST-6 imagery.",
            "tic": False,
            "fo_operator_id": fire_6.op_id,
        }, headers={"Authorization": f"Bearer {fire_6.token}",
                    "X-Mission-ID": str(api.mission_id)})
        log.info("CAS 9-liner 2 filed: Kazerne N gate AT bunker (pre-assault)")
    except Exception as e:
        log.warning("CAS 9-liner 2 failed: %s", e)


# ── Battle reports ─────────────────────────────────────────────────────────────

def submit_reports(api: Api, by_cs: dict[str, OpRoster]) -> None:
    air    = LL(*SOESTERBERG)
    kaz    = LL(*KAZERNE)
    dz_m   = LL(*DZ_MAROON_REF)
    pl_t   = LL(*BN_TAC_CP_KAZ)

    # 1. MEDEVAC URGENT — ALPHA-112 GSW during airfield breach (H+25) ──────────
    a112 = by_cs.get("ALPHA-112")
    if a112 and a112.token:
        cas_pos = air.offset(+250, -300)
        api.post("/reports", a112.token, {
            "type": "MEDEVAC",
            "payload": {
                "line_1": "LZ MAROON — DZ MAROON secondary role (52.138N/5.279E)",
                "line_2": "DUSTOFF ANGEL 31 — 282.800 MHz UHF",
                "line_3": "1× URGENT",
                "line_4": "None (no special equip req)",
                "line_5": f"{dz_m.offset(-200, 0).lat:.4f}N {dz_m.offset(-200, 0).lon:.4f}E",
                "line_6": "IR strobe (masked NE from BMP threat)",
                "line_7": "CDAG — OPFOR BMP-2 400m south; LZ contested",
                "line_8": "N — 1× LITTER",
                "line_9": "No CBRN. E — OPFOR BMP-2 in area. ALPHA-112 at RP MAROON.",
                "patient":        "ALPHA-112 (Cpl, A1SEC1, 1er PLT ALPHA CIE)",
                "precedence":     "URGENT",
                "injury":         "GSW chest from BMP-2 co-ax fire during N taxiway crossing; "
                                  "sucking chest wound, needle decompression applied T+08",
                "status":         "Conscious, laboured breathing, BP low",
                "grid":           f"{cas_pos.lat:.4f}N {cas_pos.lon:.4f}E "
                                  f"(pickup LZ MAROON, {dz_m.offset(-200,0).lat:.4f}N {dz_m.offset(-200,0).lon:.4f}E)",
                "blood_type":     "A-",
                "reporting_unit": "ALPHA-112 / A1SEC1 / ALPHA CIE",
                "dtg":            "101825ZJUN26",
            },
        })
        log.info("MEDEVAC filed: ALPHA-112 URGENT (GSW chest, N taxiway, H+25)")

    # 2. SPOT/SALUTE — RECON-1 observes OPFOR QRF column on N237 (H+60) ───────
    recon1 = by_cs.get("RECON-1")
    if recon1 and recon1.token:
        qrf_pos = LL(*N237_BLOCK).offset(0, +3500)   # 3.5 km SE on N237
        api.post("/reports", recon1.token, {
            "type": "SPOT",
            "payload": {
                "S": "4× wheeled APC (BMP-2 / BTR-80 est.); dismounts not yet visible",
                "A": "N237 northbound toward Soesterberg Airfield at approx 50 km/h",
                "L": f"{qrf_pos.lat:.4f}N {qrf_pos.lon:.4f}E — OP FALCON (RECON-1)",
                "U": "Mechanised QRF from Amersfoort Kazerne, est. 1× plt strength",
                "T": "101900ZJUN26",
                "E": (
                    "4× BMP-2, headlights on. Lead vehicle armed HMG. "
                    "ETA CHARLIE N237 block est. 6 min at current speed. "
                    "Request: CHARLIE confirm VCP ready; CAS ORANGE 41 immediate availability; "
                    "BN fire plan TRP-QRF on N237 vic CHARLIE block if penetrated."
                ),
                "observer":      "RECON-1 (INTEL, RECON-TM, ECHO CIE)",
                "reporting_net": "ECHO LOG NET → BN CMD NET",
                "dtg":           "101900ZJUN26",
                "grid_observer": f"{LL(*N237_BLOCK).offset(+500, +1000).lat:.4f}N {LL(*N237_BLOCK).offset(+500, +1000).lon:.4f}E",
                "grid_target":   f"{qrf_pos.lat:.4f}N {qrf_pos.lon:.4f}E",
                "action_taken":  "CHARLIE-6 notified; AT-SEC on standby; ORANGE 41 contacted.",
                "latitude":      qrf_pos.lat,
                "longitude":     qrf_pos.lon,
            },
        })
        log.info("SPOT filed: RECON-1 — 4× BMP-2 QRF inbound N237 (H+60)")

    # 3. DRONE SPOT — UAV-1 detects OPFOR ISR quadcopter over N237 column (H+80) ─
    uav1 = by_cs.get("UAV-1")
    if uav1 and uav1.token:
        drone_ll = LL(*N237_BLOCK).offset(+400, +600)
        resp = api.c.post(
            api._p("/reports/drone-spot"),
            json={
                "latitude":      drone_ll.lat,
                "longitude":     drone_ll.lon,
                "drone_type":    "QUADCOPTER",
                "altitude_m":    60.0,
                "direction_deg": 270.0,
                "speed_kts":     8.0,
                "behavior":      "RECONNAISSANCE",
                "notes": (
                    "Small OPFOR ISR quad (DJI Matrice est.) orbiting over N237 column axis "
                    "at ~60m AGL, heading 270°. Pattern of life: 3 × figure-8 passes over "
                    "probable ambush position at N237 culvert vic "
                    f"{drone_ll.lat:.4f}N {drone_ll.lon:.4f}E. "
                    "Spotted by RQ-11B Raven feed (UAV-1 / BHQ S2) at 101940ZJUN26. "
                    "Assessment: OPFOR recce for ambush activation — JACKAL screen and "
                    "CHARLIE 6 notified. Recommend 81mm SMOKE to blind drone and FM-009 "
                    "executed. No engagement attempted — MANPADS status unknown."
                ),
            },
            headers={"Authorization": f"Bearer {uav1.token}",
                     "X-Mission-ID": str(api.mission_id)},
        )
        if resp.status_code in (200, 201):
            log.info("DRONE_SPOT filed: UAV-1 — OPFOR ISR quad over N237 (H+80, ambush pre-indicator)")
        else:
            log.warning("DRONE_SPOT failed: %d %s", resp.status_code, resp.text[:120])

    # 4. TIC + SPOT — JACKAL-1 reports OPFOR ambush sprung on N237 column (H+105) ─
    j1 = by_cs.get("JACKAL-1")
    if j1 and j1.token:
        ambush_ll = LL(*N237_BLOCK).offset(+200, +900)
        api.post("/reports", j1.token, {
            "type": "SPOT",
            "payload": {
                "S": "Est. 8-12 PAX OPFOR dismounts + 1× PKM MMG + 2× RPG; "
                     "IED detonated on road as lead Jackal passed",
                "A": "Linear ambush N237, east side of road (treeline + culvert); "
                     "sustained fire from east, RPG fire from south berm",
                "L": f"{ambush_ll.lat:.4f}N {ambush_ll.lon:.4f}E — JACKAL-1 OP (5m south of ambush)",
                "U": "OPFOR rifle section + support weapons; no armour observed",
                "T": "102005ZJUN26",
                "E": (
                    "IED detonated under JACKAL-2 at H+105 — vehicle mobility kill, "
                    "2× crew casualties (JACKAL-3/4 minor blast injuries, ambulatory). "
                    "JACKAL-1 returning suppressive fire east; JACKAL-5/6 bounding "
                    "to flanking position. CHARLIE-12 notified. "
                    "REQUEST: FM-007 (81mm HE FFE on ambush position IMMEDIATE); "
                    "CAS ORANGE 41 if 81mm unavailable; MEDEVAC for JACKAL-3."
                ),
                "observer":      "JACKAL-1 (INTEL, JACKAL-SEC, ECHO CIE)",
                "reporting_net": "ECHO LOG NET → BN CMD NET 36.050 MHz",
                "dtg":           "102005ZJUN26",
                "grid_observer": f"{ambush_ll.offset(0, -200).lat:.4f}N {ambush_ll.offset(0, -200).lon:.4f}E",
                "grid_target":   f"{ambush_ll.lat:.4f}N {ambush_ll.lon:.4f}E",
                "action_taken":  "Suppressive fire; JACKAL element bounding; 81mm requested.",
                "latitude":      ambush_ll.lat,
                "longitude":     ambush_ll.lon,
            },
        })
        log.info("SPOT+TIC filed: JACKAL-1 — OPFOR ambush on N237, IED + PKM + RPG (H+105)")

    # 5. MEDEVAC — JACKAL-3 blast injury from N237 IED (H+106) ────────────────
    j3 = by_cs.get("JACKAL-3")
    if j3 and j3.token:
        pl_t = LL(*BN_TAC_CP_KAZ)
        api.post("/reports", j3.token, {
            "type": "MEDEVAC",
            "payload": {
                "line_1": "LZ TULIP — PL TULIP (BHQ TAC CP Phase 2)",
                "line_2": "DUSTOFF ANGEL 31 — 282.800 MHz UHF",
                "line_3": "2× PRIORITY",
                "line_4": "None",
                "line_5": f"{pl_t.lat:.4f}N {pl_t.lon:.4f}E",
                "line_6": "White strobe (LZ will be cleared prior to landing)",
                "line_7": "CLEAR — LZ 2.1km west of ambush; Kazerne area",
                "line_8": "A — 2× AMBULATORY",
                "line_9": "No CBRN. OPFOR ambush area — 2km E of LZ.",
                "patient":        "JACKAL-3 (crew, blast trauma from IED N237) + "
                                  "JACKAL-4 (crew, blast concussion + laceration)",
                "precedence":     "PRIORITY",
                "injury":         "JACKAL-3: blast trauma lower limbs (IED detonation under Jackal-2); "
                                  "bilateral leg lacerations, suspected tib/fib fracture L leg; "
                                  "tourniquet applied × 1, morphine given T+02. "
                                  "JACKAL-4: concussion + face lacerations, ambulatory.",
                "status":         "JACKAL-3 conscious, in pain, c-spine precaution; JACKAL-4 ambulatory",
                "grid":           f"{LL(*N237_BLOCK).offset(+200, +900).lat:.4f}N "
                                  f"{LL(*N237_BLOCK).offset(+200, +900).lon:.4f}E "
                                  f"(pickup LZ TULIP {pl_t.lat:.4f}N {pl_t.lon:.4f}E)",
                "blood_type":     "O+",
                "reporting_unit": "JACKAL-3 / JACKAL-SEC / ECHO CIE",
                "dtg":            "102006ZJUN26",
            },
        })
        log.info("MEDEVAC filed: JACKAL-3/4 PRIORITY (IED blast N237, H+106)")

    # 6. MEDEVAC PRIORITY — BRAVO-112 GSW during Kazerne W gate breach (H+185) ─
    b112 = by_cs.get("BRAVO-112")
    if b112 and b112.token:
        breach_pos = kaz.offset(0, -550)
        api.post("/reports", b112.token, {
            "type": "MEDEVAC",
            "payload": {
                "line_1": "LZ TULIP — PL TULIP (52.148N/5.365E)",
                "line_2": "DUSTOFF ANGEL 31 — 282.800 MHz UHF",
                "line_3": "1× PRIORITY",
                "line_4": "None",
                "line_5": f"{pl_t.lat:.4f}N {pl_t.lon:.4f}E",
                "line_6": "White strobe (LZ cleared of OPFOR)",
                "line_7": "CLEAR — LZ 1.8 km west of Kazerne W gate",
                "line_8": "A — 2× AMBULATORY",
                "line_9": "No CBRN. N — area W gate cleared by BRAVO-11.",
                "patient":        "BRAVO-112 (Cpl, B1SEC1, BRAVO CIE) + BRAVO-113 (walking wounded)",
                "precedence":     "PRIORITY",
                "injury":         "BRAVO-112: GSW left arm + fragment wound abdomen at W gate breach; "
                                  "tourniquet arm, pressure dressing abdomen, morphine admin. "
                                  "BRAVO-113: blast concussion + laceration from IED at W gate.",
                "status":         "BRAVO-112 conscious, pale, BP borderline; BRAVO-113 ambulatory",
                "grid":           f"{breach_pos.lat:.4f}N {breach_pos.lon:.4f}E "
                                  f"(pickup LZ TULIP {pl_t.lat:.4f}N {pl_t.lon:.4f}E)",
                "blood_type":     "B+",
                "reporting_unit": "BRAVO-112 / B1SEC1 / BRAVO CIE",
                "dtg":            "102025ZJUN26",
            },
        })
        log.info("MEDEVAC filed: BRAVO-112 PRIORITY (GSW + fragment, Kazerne W gate, H+185)")

    # ── DUSTOFF pickup confirmations (DOC-6 files follow-up reports) ──────────
    doc6 = by_cs.get("DOC-6")
    if doc6 and doc6.token:
        dz_m = LL(*DZ_MAROON_REF)
        pl_t = LL(*BN_TAC_CP_KAZ)

        # Pickup 1 — ALPHA-112 + JACKAL-3 from LZ MAROON
        api.post("/reports", doc6.token, {
            "type": "SPOT",
            "payload": {
                "S": "DUSTOFF ANGEL 31 (NH-90 TTH) arrived LZ MAROON",
                "A": "CASEVAC sortie 1 — 2× litter patients on board; departed LZ MAROON",
                "L": f"{dz_m.offset(-200,0).lat:.4f}N {dz_m.offset(-200,0).lon:.4f}E — LZ MAROON",
                "U": "ALPHA-112 (GSW chest, T1 URGENT) + JACKAL-3 (blast trauma, T2 PRIORITY)",
                "T": "101835ZJUN26",
                "E": (
                    "ANGEL 31 landed LZ MAROON at 101830ZJUN26 from FOB Gilze-Rijen. "
                    "ALPHA-112 (T1 URGENT) + JACKAL-3 (T2 PRIORITY) loaded 4 min. "
                    "Departed 101834ZJUN26 direct Role 2 Gilze-Rijen. ETA Role 2 102005Z. "
                    "LZ MAROON clear. DOC-6 BN AID POST operational. Blood O+ stock zero."
                ),
                "observer":      "DOC-6 (MO, AID-POST, BHQ)",
                "dtg":           "101835ZJUN26",
                "grid_observer": f"{dz_m.offset(-200,0).lat:.4f}N {dz_m.offset(-200,0).lon:.4f}E",
                "grid_target":   f"{dz_m.offset(-200,0).lat:.4f}N {dz_m.offset(-200,0).lon:.4f}E",
                "latitude":      dz_m.offset(-200, 0).lat,
                "longitude":     dz_m.offset(-200, 0).lon,
                "action_taken":  "ANGEL 31 departed. CCP standing down to minimum. Blood O+ URGENT request to BDE.",
            },
        })
        log.info("CASEVAC SORTIE 1 confirmed: ANGEL 31 picked up ALPHA-112 + JACKAL-3 from LZ MAROON")

        # Pickup 2 — BRAVO-112 + BRAVO-113 from LZ TULIP
        api.post("/reports", doc6.token, {
            "type": "SPOT",
            "payload": {
                "S": "DUSTOFF ANGEL 31 arrived LZ TULIP — 2nd CASEVAC sortie",
                "A": "2× patients loaded; LZ TULIP (PL TULIP, BHQ TAC CP Phase 2)",
                "L": f"{pl_t.lat:.4f}N {pl_t.lon:.4f}E — LZ TULIP",
                "U": "BRAVO-112 (GSW arm/abdomen T2 PRIORITY) + BRAVO-113 (blast concussion T3 ROUTINE)",
                "T": "102035ZJUN26",
                "E": (
                    "ANGEL 31 re-tasked from FOB after LOGPAC; arrived LZ TULIP 102030ZJUN26. "
                    "BRAVO-112 (GSW arm + abdomen) + BRAVO-113 (blast concussion) loaded 6 min. "
                    "Departed 102036ZJUN26 direct Role 2 Gilze-Rijen. ETA Role 2 102150Z. "
                    "LZ TULIP clear. ANGEL 31 on 45-min turn-round at Role 2. "
                    "Blood O+ × 4 units delivered to DOC-6 on inbound leg (LOGPAC partial)."
                ),
                "observer":      "DOC-6 (MO, AID-POST, BHQ — advance BN TAC CP PL TULIP)",
                "dtg":           "102036ZJUN26",
                "grid_observer": f"{pl_t.lat:.4f}N {pl_t.lon:.4f}E",
                "grid_target":   f"{pl_t.lat:.4f}N {pl_t.lon:.4f}E",
                "latitude":      pl_t.lat,
                "longitude":     pl_t.lon,
                "action_taken":  "ANGEL 31 departed LZ TULIP. Blood O+ × 4 received. CCP moved to Kazerne courtyard.",
            },
        })
        log.info("CASEVAC SORTIE 2 confirmed: ANGEL 31 picked up BRAVO-112 + BRAVO-113 from LZ TULIP")


# ── Movement simulation ───────────────────────────────────────────────────────

def simulate_movement(api: Api, steps: int, dt: float) -> None:
    """Three-phase movement: jump → airfield → column → kazerne assault."""
    air    = LL(*SOESTERBERG)
    kaz    = LL(*KAZERNE)
    dz_m   = LL(*DZ_MAROON_REF)
    dz_g   = LL(*DZ_GREEN_REF)
    bn_tac = LL(*BN_TAC_CP_AIR)
    pl_t   = LL(*BN_TAC_CP_KAZ)

    # Per-operator endpoint map: (start, airfield_objective, kazerne_objective)
    plan: dict[str, tuple[LL, LL, LL]] = {}

    for r in ROSTER:
        cs = r.callsign
        # Deterministic per-operator spread (avoid piling up on same point)
        np = (hash(cs)       % 21 - 10) * 30   # north jitter
        ep = (hash(cs + "e") % 21 - 10) * 25   # east jitter
        fk = (hash(cs + "k") % 11 -  5) * 40   # kazerne jitter

        # ── start point (DZ or fly-in) ────────────────────────────────────────
        if r.insert == "DZ_MAROON":
            start = dz_m.offset(np, ep)
        elif r.insert == "DZ_GREEN":
            start = dz_g.offset(np, ep)
        elif r.insert == "FLY_IN":
            # Fly-in operators materialise at airfield logistics area
            start = air.offset(+700 + np // 2, +100 + ep // 2)
        else:  # BN_TAC
            start = bn_tac.offset(np // 2, ep // 2)

        # ── airfield objective (Phase 1 end) ──────────────────────────────────
        if cs.startswith("ALPHA"):
            mid = air.offset(-30 + np // 3, -380 + ep // 3)   # terminal/hangars
        elif cs.startswith("BRAVO"):
            mid = air.offset(-50 + np // 3, +300 + ep // 3)   # runway east side
        elif cs.startswith("CHARLIE"):
            mid = LL(*N237_BLOCK).offset(np // 3, ep // 3)    # N237 block (via S perimeter)
        elif cs.startswith("MORT") or cs == "DELTA-6":
            mid = air.offset(+1600 + np // 3, -100 + ep // 3) # mortar line N of DZ
        elif cs.startswith("SNIPER"):
            mid = air.offset(+300 + np, +600 + ep)            # sniper overwatch E of airfield
        elif cs.startswith("AT"):
            mid = dz_m.offset(-300 + np, ep)                   # AT reserve W of airfield
        elif cs in ("LOG-6", "LOG-1", "PION-6", "PION-1", "ECHO-6"):
            mid = air.offset(+700 + np // 3, +100 + ep // 3)   # ALMA / logistics
        elif cs.startswith("UNIMOG"):
            mid = air.offset(+700 + np // 3, +100 + ep // 3)   # ALMA (fly-in)
        elif cs.startswith("JACKAL"):
            # Jackals move faster — race ahead to screen position on N237 corridor
            mid = LL(*N237_BLOCK).offset(+600 + np, +1000 + ep)
        elif cs.startswith("RECON"):
            mid = LL(*N237_BLOCK).offset(+500 + np, +1000 + ep) # recon OP N237/N221
        elif cs == "UAV-1":
            mid = dz_m.offset(-300 + np, +400 + ep)             # UAV GCS stays near BHQ
        elif r.insert == "BN_TAC":
            mid = bn_tac.offset(ep // 2, np // 2)
        else:
            mid = air.offset(+100 + np, ep)

        # ── kazerne objective (Phase 2 end) ───────────────────────────────────
        if cs.startswith("ALPHA"):
            fin = kaz.offset(+250 + fk, -200 + fk // 2)       # north gate assault
        elif cs.startswith("BRAVO"):
            fin = kaz.offset(fk, -550 + fk // 2)              # west gate breach
        elif cs.startswith("CHARLIE"):
            fin = kaz.offset(-50 + fk, +600 + fk)             # east block / perimeter
        elif cs.startswith("MORT") or cs == "DELTA-6":
            fin = kaz.offset(+700 + fk, -300 + fk)            # mortar line N of kazerne
        elif cs.startswith("SNIPER"):
            fin = kaz.offset(+500 + fk, fk)                   # sniper overwatch N/NE
        elif cs.startswith("AT"):
            fin = pl_t.offset(fk, +200 + fk)                  # AT reserve at PL TULIP
        elif cs in ("LOG-6", "LOG-1", "PION-6", "PION-1", "ECHO-6"):
            fin = pl_t.offset(-300 + fk, fk)                  # echelon B at PL TULIP
        elif cs.startswith("UNIMOG"):
            fin = pl_t.offset(-300 + fk, fk + 100)            # Unimog at echelon B
        elif cs.startswith("JACKAL"):
            # Jackals far screen — push well ahead east of Kazerne
            fin = kaz.offset(-150 + fk, +1200 + fk)
        elif cs.startswith("RECON"):
            fin = kaz.offset(-200 + fk, +1500 + fk)           # recon OP E of Kazerne
        elif cs == "UAV-1":
            fin = pl_t.offset(+100 + fk, -200 + fk)           # UAV GCS near advance BHQ
        elif r.insert == "BN_TAC":
            fin = pl_t.offset(fk // 2, np // 2)
        else:
            fin = kaz.offset(fk, fk)

        plan[cs] = (start, mid, fin)

    log.info("H-HOUR %s — BN movement: %d operators / %d steps × %.1fs",
             H_HOUR, len(ROSTER), steps, dt)

    for i in range(steps + 1):
        t = i / steps
        for r in ROSTER:
            if not r.token:
                continue
            start, mid, fin = plan[r.callsign]
            here = lerp3(start, mid, fin, t)
            body = {"latitude": here.lat, "longitude": here.lon, "altitude": 10.0}
            try:
                resp = api.c.post(api._p("/tracking/position"),
                                  json=body, headers=api._hdr(r.token))
                if resp.status_code == 401 and r.password:
                    # Token expired — silent re-auth, no lockout risk
                    try:
                        r.token = api.login(r.callsign, r.password)
                        api.c.post(api._p("/tracking/position"),
                                   json=body, headers=api._hdr(r.token))
                    except Exception:
                        r.token = ""
            except Exception as exc:
                log.warning("%s tracking: %s", r.callsign, exc)

        if i % 10 == 0:
            phase = (
                "PHASE 1 — airborne assault on Soesterberg" if t < 0.45 else
                "PHASE 1-2 — consolidation + CLP fly-in"   if t < 0.65 else
                "PHASE 2 — mounted assault on Kazerne"
            )
            log.info("  step %3d/%d  t=%.2f  %s", i, steps, t, phase)
        time.sleep(dt)

    log.info("OBJ NASSAU SECURED — 3 PARA / SOR consolidating on Kazerne")


# ── Reset helpers ──────────────────────────────────────────────────────────────

def reset_objects(api: Api, admin_tok: str) -> None:
    objs = api.get("/tactical-objects", admin_tok)
    deleted = sum(1 for o in objs
                  if api.delete(f"/tactical-objects/{o['id']}", admin_tok) == 204)
    log.info("reset: deleted %d tactical objects", deleted)


def reset_vehicles(api: Api, admin_tok: str) -> None:
    vehs = api.get("/vehicles", admin_tok)
    deleted = sum(1 for v in vehs
                  if api.delete(f"/vehicles/{v['id']}", admin_tok) == 204)   # type: ignore[index]
    log.info("reset vehicles: deleted %d", deleted)


def _build_by_cs_from_db(api: Api, admin_tok: str,
                          teams: dict[str, int]) -> dict[str, "OpRoster"]:
    """Build by_cs from server DB — 1 API call, no per-operator logins needed.

    Used by --patch mode to skip the slow operator registration loop.
    """
    all_ops = api.get("/operators", admin_tok)
    by_cs: dict[str, OpRoster] = {}
    for db_op in all_ops:                                    # type: ignore[union-attr]
        cs = db_op["callsign"]                               # type: ignore[index]
        match = next((r for r in ROSTER if r.callsign == cs), None)
        if match:
            match.op_id   = db_op["id"]                     # type: ignore[index]
            match.team_id = teams.get(match.team_name, 0)
            by_cs[cs]     = match
    log.info("patch: resolved %d/%d operators from DB", len(by_cs), len(ROSTER))
    return by_cs


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"{OP_NAME} — {BN_NAME} airborne assault on Soesterberg + attack Amersfoort Kazerne")
    parser.add_argument("--backend",
                        default=os.environ.get("ARROW_BACKEND_URL", "https://78.21.255.210:6200/api"),
                        help="Backend URL (default: ARROW_BACKEND_URL env, else production)")
    parser.add_argument("--admin",        default="benoit",   help="Admin callsign")
    parser.add_argument("--password",     default="ranger14", help="Admin password")
    parser.add_argument("--op-password",  default="Para3SOR!", help="Operator password")
    parser.add_argument("--reset",        action="store_true",
                        help="Delete all tactical objects before run")
    parser.add_argument("--reset-vehicles", action="store_true",
                        help="Delete all vehicles before run")
    parser.add_argument("--no-move",      action="store_true", help="Skip GPS simulation")
    parser.add_argument("--no-reports",   action="store_true", help="Skip MEDEVAC/SPOT/CAS/LOGREP")
    parser.add_argument("--steps",        type=int,   default=100, help="Movement steps")
    parser.add_argument("--dt",           type=float, default=2.0, help="Seconds between steps")
    parser.add_argument("--mission-name", default="Operation MARKET AMBER")
    parser.add_argument("--patch",        action="store_true",
                        help="Fast patch: skip operator registration; only add vehicles "
                             "and tactical objects to the existing mission.")
    parser.add_argument("--move-only",    action="store_true",
                        help="Skip all setup; just log in each operator and run movement.")
    parser.add_argument("--loop",         action="store_true",
                        help="Run movement in a continuous loop forever. "
                             "Re-logs in all operators at the start of each iteration "
                             "to keep tokens fresh. Ctrl-C to stop.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")

    api = Api(args.backend)
    log.info("%s — %s", OP_NAME, BN_NAME)
    log.info("backend=%s  mode=%s", args.backend, "PATCH" if args.patch else "FULL")

    admin_tok = api.login(args.admin, args.password)

    # Adopt / create mission (fast — always needed)
    api.create_mission(
        admin_tok, args.mission_name,
        description=(
            f"{BN_NAME} airborne seizure of Soesterberg Airfield (OBJ AMBER + OBJ ORANGE), "
            "CLP fly-in of YPR-765 vehicles, then mounted assault on Amersfoort Kazerne (OBJ NASSAU)."
        ),
        map_center_lat=52.1400, map_center_lng=5.3000, map_zoom=12,
    )
    log.info("mission ready (id=%s)", api.mission_id)

    if args.reset_vehicles:
        reset_vehicles(api, admin_tok)

    def _login_all(op_password: str) -> int:
        """Log in all roster operators; returns count with valid tokens."""
        for r in ROSTER:
            try:
                r.token    = api.login(r.callsign, op_password)
                r.password = op_password
                me = api.get("/auth/me", r.token)
                r.op_id = me["id"]          # type: ignore[index]
                time.sleep(0.05)
            except Exception:
                r.token = ""
        return sum(1 for r in ROSTER if r.token)

    # ── LOOP mode — login ONCE, then loop movement forever (Ctrl-C to stop) ───
    if args.loop:
        log.info("LOOP MODE — Ctrl-C to stop  |  steps=%d  dt=%.2fs", args.steps, args.dt)
        ok = _login_all(args.op_password)
        log.info("initial login: %d/%d operators  (tokens refresh on 401 only)",
                 ok, len(ROSTER))
        iteration = 0
        try:
            while True:
                iteration += 1
                log.info("=== LOOP %d START ===", iteration)
                simulate_movement(api, steps=args.steps, dt=args.dt)
                log.info("=== LOOP %d COMPLETE — restarting ===", iteration)
        except KeyboardInterrupt:
            log.info("loop stopped after %d iteration(s)", iteration)
        return

    # ── MOVE-ONLY mode — login each operator, skip all setup, run movement ─────
    if args.move_only:
        ok = _login_all(args.op_password)
        log.info("--move-only: %d/%d operators logged in", ok, len(ROSTER))
        simulate_movement(api, steps=args.steps, dt=args.dt)
        return

    # ── PATCH mode — skip registration, just add vehicles + objects ────────────
    if args.patch:
        if args.reset:
            reset_objects(api, admin_tok)

        teams = build_hierarchy(api, admin_tok)      # idempotent — fast
        by_cs = _build_by_cs_from_db(api, admin_tok, teams)

        # Vehicles (linked to operators by op_id from DB)
        build_vehicles(api, admin_tok, by_cs, teams)

        # Tactical graphics (objectives + all graphics)
        graphics = build_graphics(sim_utils.mgrs)
        posted = 0
        for g in graphics:
            try:
                api.post("/tactical-objects", admin_tok, g)
                posted += 1
            except Exception as exc:
                log.warning("TG failed: %s", exc)
        log.info("tactical graphics posted: %d/%d", posted, len(graphics))

        if not args.no_reports:
            build_cas(api, admin_tok, by_cs)
            submit_reports(api, by_cs)
            submit_logreps(api, by_cs, admin_tok)
            log.info("reports + LOGREPs filed")

        log.info("--patch complete")
        return

    # ── FULL mode ─────────────────────────────────────────────────────────────
    if args.reset:
        reset_objects(api, admin_tok)

    # 1 — Hierarchy
    teams = build_hierarchy(api, admin_tok)

    # 2 — Operators (slow — ~50s; each set-password+login updates that op's session_jti)
    register_operators(api, admin_tok, teams, args.op_password)
    by_cs = {r.callsign: r for r in ROSTER}
    # Re-login admin so our token is fresh after all the per-operator logins above
    admin_tok = api.login(args.admin, args.password)
    log.info("admin token refreshed")

    # 3 — OPORD
    try:
        opord = api.post("/opord", admin_tok, build_opord())
        log.info("OPORD %s posted (id=%s)", opord.get("opord_number"), opord.get("id"))  # type: ignore
        api.post(f"/opord/{opord['id']}/publish", admin_tok, {})                          # type: ignore
        api.post(f"/opord/{opord['id']}/send", admin_tok,
                 {"operator_ids": [r.op_id for r in ROSTER if r.op_id]})
        log.info("OPORD distributed to %d operators", sum(1 for r in ROSTER if r.op_id))
    except Exception as exc:
        log.warning("OPORD skipped: %s", exc)

    # 4 — Tactical graphics (80 items: objectives, sub-objectives, enemies, vehicles, POIs)
    graphics = build_graphics(sim_utils.mgrs)
    posted = sum(
        1 for g in graphics
        if _try_post(api, "/tactical-objects", admin_tok, g)
    )
    log.info("tactical graphics posted: %d/%d", posted, len(graphics))

    # 5 — Fire plan (9 missions: 5 suppression + smoke + FFE + illum + recce smoke)
    fm_list = build_fire_plan()
    fm_ok = sum(1 for fm in fm_list if _try_post(api, "/fire-missions", admin_tok, fm))
    log.info("fire plan posted: %d/%d missions", fm_ok, len(fm_list))

    # 6 — Vehicles (20 vehicles linked to operators)
    build_vehicles(api, admin_tok, by_cs, teams)

    # 7 — CAS + battle reports + LOGREPs
    if not args.no_reports:
        build_cas(api, admin_tok, by_cs)
        submit_reports(api, by_cs)
        submit_logreps(api, by_cs, admin_tok)
        log.info("all reports filed: 3× MEDEVAC, 2× SPOT, 1× DRONE_SPOT, 2× CAS, 2× LOGREP")

    # 8 — GPS movement simulation
    if args.no_move:
        log.info("--no-move: plan complete")
        return
    simulate_movement(api, steps=args.steps, dt=args.dt)


def _try_post(api: Api, path: str, tok: str, body: dict) -> bool:
    try:
        api.post(path, tok, body)
        return True
    except Exception as exc:
        log.warning("POST %s failed: %s", path, exc)
        return False


if __name__ == "__main__":
    main()
