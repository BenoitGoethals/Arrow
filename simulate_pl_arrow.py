#!/usr/bin/env python3
"""
Arrow Simulator -- Op DENDERMONDE-AALST  (PL Arrow formation)
=============================================================
30 operators, 1 platoon, arrow formation, human walking speed (5 km/h).
Marches Dendermonde -> Aalst, then reverses and loops.

Hierarchy
  Bravo Company
  L- 1 PLT
       +- HQ SEC   3 ops: plt comd (BATTLE_CAPTAIN), plt sgt, signaller/drone op
       +- 1 SEC    9 ops: 3 teams x 3 -- tip of the arrow (lead)
       +- 2 SEC    9 ops: 3 teams x 3 -- left flank, echeloned back
       L- 3 SEC    9 ops: 3 teams x 3 -- right flank, echeloned back

Live events generated while the platoon marches
  Enemy on road  8 OPFOR units along the route, shuffling every ~30 s
  Drone spots    HQ signaller posts UAV SPOT every ~90 s real time
  TIC alerts     forward operators fire TIC when within 400 m of enemy
  CASEVAC        plt sgt submits 9-line after ~40 pct of TIC events
  OPORD          full 5-paragraph OPORD published at startup

Key fix: operators are explicitly assigned to the mission so the web map
WS filter (which drops updates where operator.mission_id != active mission)
does not silently discard position updates.

Usage
  uv run python simulate_pl_arrow.py
  uv run python simulate_pl_arrow.py --backend http://78.21.255.210:6001
  uv run python simulate_pl_arrow.py --speed 20   # recommended: 20x faster
  uv run python simulate_pl_arrow.py --reset       # wipe sim ops first
  uv run python simulate_pl_arrow.py --no-move     # plan-only, no GPS sim
  uv run python simulate_pl_arrow.py --steps 60 --dt 1.5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import os
import random
from dataclasses import dataclass, field
from typing import Optional

import httpx
import sim_utils

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="PL Arrow -- Dendermonde -> Aalst")
parser.add_argument("--backend",
                    default=(os.environ.get("ARROW_BACKEND_URL")
                             or sim_utils.load_saved_backend()
                             or "http://localhost:6001"),
                    help="Backend base URL. Defaults to ARROW_BACKEND_URL env var, then localhost.")
parser.add_argument("--speed", type=float, default=None,
                    help="Time multiplier (1=real time, 20=20x faster)")
parser.add_argument("--reset", action="store_true",
                    help="Delete all sim operators before starting")
parser.add_argument("--seed-admin", default="benoit")
parser.add_argument("--seed-admin-password", default="ranger14")
parser.add_argument("--mission-name", default="Op Dendermonde-Aalst")
parser.add_argument("--admin",    default=None,
                    help="Alias for --seed-admin (ADMIN callsign)")
parser.add_argument("--password", default=None,
                    help="Alias for --seed-admin-password (ADMIN password)")
parser.add_argument("--no-move",  action="store_true",
                    help="Plant OPORD and enemies only, skip the movement simulation")
parser.add_argument("--steps",    type=int, default=None,
                    help="Movement steps. If given with --dt, derives speed and limits run duration.")
parser.add_argument("--dt",       type=float, default=None,
                    help="Seconds between steps. If given with --steps, derives speed and total duration.")
ARGS = parser.parse_args()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("sim.arrow")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE         = ARGS.backend.rstrip("/")
SIM_PASSWORD = "Arrow2525!"
WALK_MS      = 5_000 / 3_600   # 5 km/h in m/s
UPDATE_S     = 10.0             # real seconds between position pushes
OPFOR_S      = 30.0             # real seconds between enemy jitter steps
DRONE_S      = 90.0             # real seconds between drone SPOT reports
TIC_CHECK_S  = 15.0             # real seconds between TIC proximity checks
TIC_RANGE_M  = 400.0            # metres -- trigger TIC when this close to enemy
MISSION_ID: int | None = None

# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------

LAT_DEG_PER_M = 1.0 / 111_000.0


def _lon_deg_per_m(lat: float) -> float:
    return 1.0 / (111_000.0 * math.cos(math.radians(lat)))


def dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = (lat2 - lat1) * 111_000
    dlon = (lon2 - lon1) * 111_000 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)


def step_towards(lat: float, lon: float,
                 tlat: float, tlon: float,
                 speed_ms: float, dt: float) -> tuple[float, float]:
    d = dist_m(lat, lon, tlat, tlon)
    if d < 0.5:
        return tlat, tlon
    move   = min(speed_ms * dt, d)
    dlat_m = (tlat - lat) * 111_000
    dlon_m = (tlon - lon) * 111_000 * math.cos(math.radians(lat))
    brg    = math.atan2(dlon_m, dlat_m)
    return (
        lat + move * math.cos(brg) * LAT_DEG_PER_M,
        lon + move * math.sin(brg) * _lon_deg_per_m(lat),
    )


def march_bearing(lat: float, lon: float, tlat: float, tlon: float) -> float:
    dlat_m = (tlat - lat) * 111_000
    dlon_m = (tlon - lon) * 111_000 * math.cos(math.radians(lat))
    return math.atan2(dlon_m, dlat_m)


def formation_pos(centre_lat: float, centre_lon: float,
                  fwd_m: float, right_m: float,
                  bearing_rad: float) -> tuple[float, float]:
    """Offset centre by fwd_m along bearing and right_m to the right."""
    right_brg = bearing_rad + math.pi / 2
    lat = (centre_lat
           + fwd_m   * math.cos(bearing_rad) * LAT_DEG_PER_M
           + right_m * math.cos(right_brg)   * LAT_DEG_PER_M)
    lon = (centre_lon
           + fwd_m   * math.sin(bearing_rad) * _lon_deg_per_m(centre_lat)
           + right_m * math.sin(right_brg)   * _lon_deg_per_m(centre_lat))
    return lat, lon


def offset_point(lat: float, lon: float,
                 north_m: float, east_m: float) -> tuple[float, float]:
    return (lat + north_m * LAT_DEG_PER_M,
            lon + east_m  * _lon_deg_per_m(lat))


def grid(lat: float, lon: float) -> str:
    return f"{lat:.5f},{lon:.5f}"


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

WAYPOINTS: list[tuple[float, float]] = [
    (51.0281, 4.1011),   # 0  Dendermonde -- Grote Markt
    (51.0050, 4.0820),   # 1  Lebbeke outskirts
    (50.9700, 4.0610),   # 2  Burst / approach Aalst
    (50.9378, 4.0376),   # 3  Aalst -- Grote Markt
    (50.9700, 4.0610),   # 4  Burst (return leg)
    (51.0050, 4.0820),   # 5  Lebbeke (return)
    (51.0281, 4.1011),   # 6  Dendermonde (loop anchor -- skipped in ring)
]

# ---------------------------------------------------------------------------
# Formation offsets  (forward_m, right_m) from platoon centre
# Bearing-relative: +fwd = toward next WP,  +right = right of march direction
# ---------------------------------------------------------------------------

# fmt: off
_HQ_OFFSETS: list[tuple[float, float]] = [
    (   0,    0),   # HQ-1  plt comd  (BATTLE_CAPTAIN)
    ( -12,  -10),   # HQ-2  plt sgt
    ( -12,  +10),   # HQ-3  signaller / drone op
]

_1SEC_OFFSETS: list[tuple[float, float]] = [
    (+220,    0),   # 1-1-1  sec comd -- arrowhead tip
    (+205,   -8),   # 1-1-2
    (+205,   +8),   # 1-1-3
    (+195,  -20),   # 1-2-1  TL left
    (+180,  -28),   # 1-2-2
    (+180,  -12),   # 1-2-3
    (+195,  +20),   # 1-3-1  TL right
    (+180,  +12),   # 1-3-2
    (+180,  +28),   # 1-3-3
]

_2SEC_OFFSETS: list[tuple[float, float]] = [
    ( -80, -160),   # 2-1-1  sec comd -- left flank front
    ( -95, -168),   # 2-1-2
    ( -95, -152),   # 2-1-3
    (-110, -185),   # 2-2-1  TL outer
    (-125, -193),   # 2-2-2
    (-125, -177),   # 2-2-3
    (-110, -135),   # 2-3-1  TL inner
    (-125, -143),   # 2-3-2
    (-125, -127),   # 2-3-3
]

_3SEC_OFFSETS: list[tuple[float, float]] = [   # mirror of _2SEC
    ( -80, +160),   # 3-1-1  sec comd -- right flank front
    ( -95, +152),   # 3-1-2
    ( -95, +168),   # 3-1-3
    (-110, +135),   # 3-2-1  TL inner
    (-125, +127),   # 3-2-2
    (-125, +143),   # 3-2-3
    (-110, +185),   # 3-3-1  TL outer
    (-125, +177),   # 3-3-2
    (-125, +193),   # 3-3-3
]
# fmt: on

# ---------------------------------------------------------------------------
# Enemy road laydown  (8 units along the N41/N9 corridor)
# ---------------------------------------------------------------------------

_ROAD_ENEMY: list[dict] = [
    dict(lat=51.0060, lon=4.0810, etype="INFANTRY",    sidc="SHGPUCI-----",
         desc="EN inf section -- blocking position at Lebbeke crossroads",
         jitter_m=80),
    dict(lat=51.0045, lon=4.0835, etype="VEHICLE",     sidc="SHGPEV------",
         desc="Technical w/ HMG -- covering approach from Dendermonde",
         jitter_m=60),
    dict(lat=50.9880, lon=4.0720, etype="INFANTRY",    sidc="SHGPUCI-----",
         desc="EN ambush position -- tree-line south of N9",
         jitter_m=100),
    dict(lat=50.9860, lon=4.0690, etype="SNIPER",      sidc="SHGPUCIS----",
         desc="EN sniper pair -- elevated position overlooking road",
         jitter_m=30),
    dict(lat=50.9710, lon=4.0615, etype="ARMOR",       sidc="SHGPUCA-----",
         desc="EN BMP -- hull-down at Burst junction",
         jitter_m=50),
    dict(lat=50.9730, lon=4.0580, etype="ARTILLERY",   sidc="SHGPUCF-----",
         desc="EN 81 mm mortar baseplate -- fire support element",
         jitter_m=120),
    dict(lat=50.9520, lon=4.0480, etype="INFANTRY",    sidc="SHGPUCI-----",
         desc="EN inf section -- prepared positions, Aalst northern approach",
         jitter_m=70),
    dict(lat=50.9450, lon=4.0420, etype="AIR_DEFENSE", sidc="SHGPUCD-----",
         desc="EN MANPADS -- covering Aalst rooftop",
         jitter_m=40),
]

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SimOp:
    callsign: str
    rank:     str
    role:     str
    fwd_m:    float
    right_m:  float
    token:    str   = ""
    op_id:    int   = 0
    lat:      float = 0.0
    lon:      float = 0.0


@dataclass
class SimSection:
    name:      str
    operators: list[SimOp] = field(default_factory=list)


@dataclass
class OpforUnit:
    obj_id:    int
    orig_lat:  float
    orig_lon:  float
    lat:       float
    lon:       float
    etype:     str
    sidc:      str
    desc:      str
    jitter_m:  float
    tic_fired: bool = False


# ---------------------------------------------------------------------------
# Build platoon
# ---------------------------------------------------------------------------

def _build_platoon() -> tuple[list[SimOp], list[SimSection]]:
    sections: list[SimSection] = []
    all_ops:  list[SimOp]      = []

    # HQ section
    hq = SimSection(name="HQ SEC")
    for (cs, rank, role), (fwd, rgt) in zip(
        [("1PLT-HQ1", "OF-1", "BATTLE_CAPTAIN"),
         ("1PLT-HQ2", "OR-7", "OPERATOR"),
         ("1PLT-HQ3", "OR-4", "OPERATOR")],
        _HQ_OFFSETS,
    ):
        op = SimOp(callsign=cs, rank=rank, role=role, fwd_m=fwd, right_m=rgt)
        hq.operators.append(op)
        all_ops.append(op)
    sections.append(hq)

    # Rifle sections
    for sec_num, (sec_name, offsets) in enumerate(
        [("1 SEC", _1SEC_OFFSETS),
         ("2 SEC", _2SEC_OFFSETS),
         ("3 SEC", _3SEC_OFFSETS)], start=1,
    ):
        sec = SimSection(name=sec_name)
        for i, (fwd, rgt) in enumerate(offsets):
            team_num = (i // 3) + 1
            mbr_num  = (i %  3) + 1
            callsign = f"1PLT-{sec_num}{team_num}{mbr_num}"
            rank     = ("OR-6" if (team_num == 1 and mbr_num == 1)
                        else "OR-5" if mbr_num == 1 else "OR-3")
            op = SimOp(callsign=callsign, rank=rank, role="OPERATOR",
                       fwd_m=fwd, right_m=rgt)
            sec.operators.append(op)
            all_ops.append(op)
        sections.append(sec)

    return all_ops, sections


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

async def _api(client: httpx.AsyncClient, method: str, path: str,
               token: str = "", **kwargs) -> Optional[dict]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if MISSION_ID:
        headers["X-Mission-ID"] = str(MISSION_ID)
    try:
        r = await client.request(method, f"{BASE}{path}",
                                 headers=headers, timeout=10, **kwargs)
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code in (204, 409):
            return {}
        log.warning("%-6s %-40s -> %d  %s", method, path, r.status_code, r.text[:80])
    except Exception as exc:
        log.warning("%-6s %-40s -> %s", method, path, exc)
    return None


async def _login(client: httpx.AsyncClient, callsign: str,
                 password: str = SIM_PASSWORD) -> Optional[str]:
    try:
        r = await client.post(f"{BASE}/auth/login",
                              data={"username": callsign, "password": password},
                              timeout=10)
        if r.status_code == 200:
            return r.json().get("access_token")
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def bootstrap(client: httpx.AsyncClient,
                    all_ops: list[SimOp],
                    sections: list[SimSection]) -> str:
    log.info("-- Bootstrap -----------------------------------------------")

    seed_token = await _login(client, ARGS.seed_admin, ARGS.seed_admin_password)
    if not seed_token:
        raise RuntimeError(
            f"Cannot login as {ARGS.seed_admin!r}. "
            "Ensure the backend is running and the seed admin exists."
        )
    log.info("Logged in as seed admin '%s'", ARGS.seed_admin)
    admin_token = seed_token

    if ARGS.reset:
        log.info("-- Reset: removing previous sim operators --")
        existing = await _api(client, "GET", "/operators", token=admin_token) or []
        sim_cs   = {op.callsign for op in all_ops}
        for row in existing:
            if row.get("callsign") in sim_cs:
                await _api(client, "DELETE", f"/operators/{row['id']}",
                           token=admin_token)
                log.info("  Deleted %s", row["callsign"])

    # Company
    companies = await _api(client, "GET", "/companies", token=admin_token) or []
    company   = next((c for c in companies if c["name"] == "Bravo Company"), None)
    if not company:
        company = await _api(client, "POST", "/companies", token=admin_token,
                             json={"name": "Bravo Company"})
        if not company:
            raise RuntimeError("Failed to create Bravo Company -- check admin role")
        log.info("Created Bravo Company (id=%d)", company["id"])
    company_id = company["id"]

    # Platoon
    platoons_resp = await _api(client, "GET", "/platoons", token=admin_token) or []
    platoon = next((p for p in platoons_resp
                    if p["name"] == "1 PLT" and p["company_id"] == company_id), None)
    if not platoon:
        platoon = await _api(client, "POST", "/platoons", token=admin_token,
                             json={"name": "1 PLT", "company_id": company_id})
        if not platoon:
            raise RuntimeError("Failed to create 1 PLT")
        log.info("  Created 1 PLT (id=%d)", platoon["id"])
    platoon_id = platoon["id"]

    # Sections + teams
    sections_resp   = await _api(client, "GET", "/sections", token=admin_token) or []
    sec_name_to_id  = {s["name"]: s["id"] for s in sections_resp
                       if s["platoon_id"] == platoon_id}
    teams_resp      = await _api(client, "GET", "/teams", token=admin_token) or []
    team_name_to_id = {t["name"]: t["id"] for t in teams_resp}

    for sec in sections:
        if sec.name not in sec_name_to_id:
            r = await _api(client, "POST", "/sections", token=admin_token,
                           json={"name": sec.name, "platoon_id": platoon_id})
            if r:
                sec_name_to_id[sec.name] = r["id"]
                log.info("    Created section %s (id=%d)", sec.name, r["id"])

        sec_id  = sec_name_to_id.get(sec.name)
        n_teams = 1 if sec.name == "HQ SEC" else 3
        for t in range(1, n_teams + 1):
            tname = f"{sec.name}-T{t}"
            if tname not in team_name_to_id:
                r = await _api(client, "POST", "/teams", token=admin_token,
                               json={"name": tname, "section_id": sec_id})
                if r:
                    team_name_to_id[tname] = r["id"]
                    log.info("      Created team %s (id=%d)", tname, r["id"])

    # Register operators
    log.info("-- Registering operators --")
    existing_ops = {o["callsign"]: o
                    for o in (await _api(client, "GET", "/operators",
                                         token=admin_token) or [])}
    for sec in sections:
        n_teams  = 1 if sec.name == "HQ SEC" else 3
        per_team = len(sec.operators) // n_teams
        for i, op in enumerate(sec.operators):
            team_num  = (i // per_team) + 1
            team_name = f"{sec.name}-T{team_num}"
            team_id   = team_name_to_id.get(team_name)
            ex        = existing_ops.get(op.callsign)
            if not ex:
                r = await _api(client, "POST", "/auth/register/admin",
                               token=admin_token, json={
                                   "callsign": op.callsign,
                                   "password": SIM_PASSWORD,
                                   "rank":     op.rank,
                                   "role":     op.role,
                                   "team_id":  team_id,
                               })
                if r:
                    # /auth/register/admin returns a token directly -- no login needed
                    op.token = r.get("access_token", "")
                    log.info("  Registered %-14s (%s) -> %s",
                             op.callsign, op.rank, team_name)
            else:
                op.op_id = ex["id"]
                if team_id and ex.get("team_id") != team_id:
                    await _api(client, "PATCH", f"/operators/{ex['id']}",
                               token=admin_token, json={"team_id": team_id})

    # Resolve all op_ids
    all_rows = {o["callsign"]: o
                for o in (await _api(client, "GET", "/operators",
                                      token=admin_token) or [])}
    for op in all_ops:
        if row := all_rows.get(op.callsign):
            op.op_id = row["id"]

    log.info("-- Bootstrap complete -- %d operators ready --", len(all_ops))
    return admin_token


# ---------------------------------------------------------------------------
# Login all operators
# ---------------------------------------------------------------------------

async def login_all(client: httpx.AsyncClient, all_ops: list[SimOp]) -> None:
    # Operators registered in this run already have a token from the register
    # response -- skip them.  Only login pre-existing operators.
    need_login = [op for op in all_ops if not op.token]
    already    = len(all_ops) - len(need_login)
    log.info("-- Tokens: %d from registration, %d need login --",
             already, len(need_login))

    # /auth/login is rate-limited to 10/minute per IP.
    # Send batches of 9 with a 62 s gap between batches so we never exceed the limit.
    BATCH = 9
    ok = fail = 0
    for i in range(0, len(need_login), BATCH):
        batch  = need_login[i:i + BATCH]
        tokens = await asyncio.gather(*[_login(client, op.callsign) for op in batch])
        for op, tok in zip(batch, tokens):
            if tok:
                op.token = tok
                ok += 1
            else:
                log.warning("  Login failed: %s", op.callsign)
                fail += 1
        if i + BATCH < len(need_login):
            log.info("  Rate-limit pause 62 s before next login batch ...")
            await asyncio.sleep(62.0)

    log.info("  Tokens ready: %d from reg + %d from login  (%d failed)",
             already, ok, fail)


# ---------------------------------------------------------------------------
# OPORD
# ---------------------------------------------------------------------------

async def plant_opord(client: httpx.AsyncClient, admin_token: str) -> None:
    opord_no = "OPORD 26-201"
    existing = await _api(client, "GET", "/opord", token=admin_token) or []
    if any(isinstance(o, dict) and o.get("opord_number") == opord_no
           for o in existing):
        log.info("OPORD %s already present -- skipping.", opord_no)
        return

    body = {
        "title":          "1 PLT Bravo Coy -- Advance Dendermonde to Aalst",
        "opord_number":   opord_no,
        "dtg":            "281800ZMAY26",
        "time_zone":      "ZULU",
        "classification": "UNCLASSIFIED//EXERCISE",
        "references": (
            "a. Topographic Map 1:25 000 -- Dendermonde/Aalst sheet NGI 22/5-6\n"
            "b. BDE OPORD 26-04 (Op IRON DENDER)\n"
            "c. Bravo Coy Standing SOPs -- Edition 2026\n"
            "d. Rules of Engagement Card ROMEO-3"
        ),
        "task_organization": (
            "1 PLT (Main Effort)\n"
            "  HQ SEC  -- Plt Comd (1PLT-HQ1), Plt Sgt (1PLT-HQ2), Drone Op (1PLT-HQ3)\n"
            "  1 SEC   -- Lead Section, 3 x 3-man teams  [arrowhead tip]\n"
            "  2 SEC   -- Left Flank Section, 3 x 3-man teams\n"
            "  3 SEC   -- Right Flank Section, 3 x 3-man teams\n"
            "OPCON: UAV Raven call-sign SHADOW-1 to plt comd for route recce\n"
            "OPCON: 1 x sniper pair from BN recce (on call)"
        ),
        "situation": {
            "terrain": (
                "Ground flat to gently rolling, drained by the Dender river. "
                "Route N41/N9 through Lebbeke and Burst to Aalst. "
                "Key terrain: Lebbeke crossroads (EN blocking), Burst junction (armour). "
                "Limited cover on farmland; tree-lines provide short-range concealment. "
                "Urban Aalst offers prepared EN positions and rooftop firing points."
            ),
            "weather": (
                "BMNT 0452 / Sunrise 0528 / Sunset 2012 / EENT 2048 (28 May 26). "
                "Overcast, 14 C, wind SW 10-15 km/h, vis 8 km."
            ),
            "enemy_cds": (
                "EN inf coy(-) with armour (BMP, technical) and 81 mm mortars. "
                "Blocking at Lebbeke crossroads and Burst junction. "
                "MANPADS on Aalst northern approach."
            ),
            "enemy_mlcoa": (
                "Defend in depth along N41/N9; ambush between Lebbeke and Burst; "
                "mortars registered on road junctions; canalize plt and engage with "
                "armour hull-down at Burst."
            ),
            "enemy_mdcoa": (
                "Fighting withdrawal to Aalst urban area; FIBUA defence; "
                "MANPADS to deny air support."
            ),
            "higher": (
                "Bravo Coy advances Dendermonde-Aalst to seize Aalst Grote Markt "
                "NLT H+4h IOT enable BN passage of lines. 1 PLT is Main Effort."
            ),
            "adjacent": "2 PLT left (N414). 3 PLT right (R20). BN reserve Dendermonde.",
            "civil": "ROE ROMEO-3. Minimise collateral damage. CIMIC if civilian movement needed.",
            "attachments": "UAV Raven to plt comd. Sniper pair on call. Medical team at FUP.",
            "assumptions": "EN per ISUM-45. No EN air. CAS 30-min strip alert.",
        },
        "mission": (
            "1 PLT Bravo Coy advances in PL Arrow formation from Dendermonde NLT H+00 "
            "along N41/N9 to seize Aalst Grote Markt NLT H+04, IOT enable Bravo Coy "
            "consolidation and BN continuation of advance."
        ),
        "execution": {
            "intent_purpose":   "Destroy or bypass EN blocking elements to open the Dendermonde-Aalst axis.",
            "intent_key_tasks": (
                "1. Clear Lebbeke crossroads.\n"
                "2. Defeat EN ambush between Lebbeke and Burst.\n"
                "3. Neutralise EN armour at Burst junction.\n"
                "4. Seize Aalst Grote Markt."
            ),
            "intent_end_state": (
                "EN destroyed or withdrawn; plt consolidated Aalst Grote Markt; "
                "route open for follow-on; CASEVAC lanes clear."
            ),
            "conops_maneuver": (
                "PLT in Arrow formation (1 SEC lead, 2 SEC left, 3 SEC right). "
                "PHASE I: Advance PL DENDER (Lebbeke). "
                "PHASE II: Clear Lebbeke crossroads (1 SEC assault, 2/3 SEC SBF). "
                "PHASE III: Bypass/assault Burst; suppress EN armour. "
                "PHASE IV: Enter Aalst; seize Grote Markt."
            ),
            "conops_fires": (
                "Plt Comd designates via UAV SHADOW-1. "
                "81 mm on call Bravo Coy HQ. CAS ARROW 21 on 30-min alert. "
                "Smoke PL DENDER."
            ),
            "conops_main_effort": "1 SEC leads; 2/3 SEC mutual support.",
            "conops_phasing":     "ADVANCE -> LEBBEKE CLEAR -> BURST BYPASS -> AALST SEIZE.",
            "tasks": (
                "1 SEC (ME): Lead in formation; clear Lebbeke; 200 m vanguard.\n"
                "2 SEC (SE-L): Left flank; SBF Lebbeke; cover Burst bypass.\n"
                "3 SEC (SE-R): Right flank; SBF Lebbeke; cover Burst bypass.\n"
                "HQ SEC: C2; SHADOW-1 tasking; CASEVAC coord; comms Coy HQ."
            ),
            "coord_timings":  "H-30 SP Dendermonde. H+00 PL START. H+45 PL DENDER. H+04 Aalst.",
            "coord_ccir":     "PIR: EN reinforce axis. FFIR: <50% eff; CASEVAC; CAS request.",
            "coord_roe":      "ROE ROMEO-3. PID required. NFA: churches, hospitals, schools.",
            "coord_risk":     "MEDIUM -- fratricide during Lebbeke clearance. Control: VS-17.",
            "coord_fscm":     "FSCL PL AALST. NFA within 50 m Lebbeke church.",
        },
        "sustainment": {
            "supply":      "Class I: 1 MRE/man SP. Class III: topped Dendermonde. Class V: basic+25%.",
            "transport":   "Foot movement. 1 x Land Rover HQ/CASEVAC.",
            "maintenance": "Report VOR to Coy HQ.",
            "personnel":   "Strength report H-15 and PL DENDER.",
            "epw":         "5 Ss and T. Tag EPW-1+. Hold at Coy HQ.",
            "casevac":     "CCP FUP Dendermonde (H-30/H+30), then fwd CCP Lebbeke post PHASE II. 9-Line PLT net.",
            "medevac":     "ROLE 1 Dendermonde. ROLE 2 Bravo BAS. DUSTOFF PEGASUS-4, 20-min notice.",
        },
        "command_signal": {
            "command":         "Plt Comd with 1 SEC during ADVANCE; Lebbeke CP during PHASE II.",
            "succession":      "Plt Comd -> Plt Sgt -> 1 SEC comd -> 2 SEC comd -> 3 SEC comd.",
            "control":         "SITREP every 30 min PLT net. Immediate report on TIC.",
            "pace_primary":    "VHF SINCGARS -- PLT 38.450 / SEC 39.100 / COY 40.250",
            "pace_alternate":  "Motorola DP4800 UHF 467.500",
            "pace_contingency":"Iridium -- plt comd only",
            "pace_emergency":  "Pyro: green star = rally; red smoke = CASEVAC; WP = withdraw",
            "callsigns":   "ARROW 6 (Plt Comd), ARROW 5 (Plt Sgt), ARROW 1/2/3 (secs), SHADOW 1 (UAV).",
            "password":    "Challenge: DENDER / Reply: ARROW / Running: COBRA",
        },
    }

    r = await _api(client, "POST", "/opord", token=admin_token, json=body)
    if not (r and isinstance(r, dict) and "id" in r):
        log.warning("OPORD plant failed.")
        return
    opord_id = r["id"]
    await _api(client, "POST", f"/opord/{opord_id}/snapshots/render",
               token=admin_token,
               json={"label": "1 PLT AO -- Dendermonde to Aalst",
                     "bbox": [50.920, 4.020, 51.045, 4.120], "zoom": 13,
                     "annotations": "PL Arrow advance axis -- N41/N9 corridor"})
    await _api(client, "POST", f"/opord/{opord_id}/publish", token=admin_token)
    log.info("OPORD %s published (id=%d)", opord_no, opord_id)


# ---------------------------------------------------------------------------
# Enemy road contacts
# ---------------------------------------------------------------------------

async def plant_enemy(client: httpx.AsyncClient,
                      admin_token: str) -> list[OpforUnit]:
    log.info("-- Planting %d OPFOR units along route --", len(_ROAD_ENEMY))
    units: list[OpforUnit] = []
    for e in _ROAD_ENEMY:
        r = await _api(client, "POST", "/tactical-objects", token=admin_token,
                       json={
                           "type":        "ENEMY",
                           "symbol_code": e["sidc"],
                           "affiliation": "ENEMY",
                           "latitude":    round(e["lat"], 6),
                           "longitude":   round(e["lon"], 6),
                           "notes":       e["desc"],
                           "visibility":  "COMPANY",
                           "rotation":    0.0,
                           "geometry":    "",
                       })
        if r and isinstance(r, dict) and "id" in r:
            units.append(OpforUnit(
                obj_id=r["id"],
                orig_lat=e["lat"], orig_lon=e["lon"],
                lat=e["lat"],      lon=e["lon"],
                etype=e["etype"],  sidc=e["sidc"],
                desc=e["desc"],    jitter_m=e["jitter_m"],
            ))
            log.info("  OPFOR %-12s  %.5f,%.5f", e["etype"], e["lat"], e["lon"])
    return units


async def run_opfor_jitter(client: httpx.AsyncClient,
                           admin_token: str,
                           units: list[OpforUnit],
                           speed_mult: float) -> None:
    real_interval = OPFOR_S / speed_mult
    await asyncio.sleep(real_interval * 0.5)
    while True:
        for u in units:
            ang    = random.uniform(0, 2 * math.pi)
            step_m = random.uniform(10, u.jitter_m * 0.4)
            new_lat, new_lon = offset_point(u.lat, u.lon,
                                            step_m * math.cos(ang),
                                            step_m * math.sin(ang))
            if dist_m(u.orig_lat, u.orig_lon, new_lat, new_lon) > u.jitter_m:
                continue
            await _api(client, "DELETE", f"/tactical-objects/{u.obj_id}",
                       token=admin_token)
            r = await _api(client, "POST", "/tactical-objects", token=admin_token,
                           json={
                               "type": "ENEMY", "symbol_code": u.sidc,
                               "affiliation": "ENEMY",
                               "latitude":  round(new_lat, 6),
                               "longitude": round(new_lon, 6),
                               "notes":     u.desc,
                               "visibility": "COMPANY",
                               "rotation": 0.0, "geometry": "",
                           })
            if r and isinstance(r, dict) and "id" in r:
                u.obj_id       = r["id"]
                u.lat, u.lon   = new_lat, new_lon
        await asyncio.sleep(real_interval)


# ---------------------------------------------------------------------------
# Drone SPOT reports
# ---------------------------------------------------------------------------

_DRONE_NOTES = [
    "UAV SHADOW-1: infantry element in tree-line, est section strength",
    "UAV SHADOW-1: vehicle stationary at junction, possible OP",
    "UAV SHADOW-1: mortar crew of 3, tube oriented NE",
    "UAV SHADOW-1: personnel digging in at farm building, approx 6 pax",
    "UAV SHADOW-1: technical w/ HMG hull-down behind berm",
    "UAV SHADOW-1: sniper pair on rooftop, range est 400 m",
    "UAV SHADOW-1: log vehicle offloading ammo at farm track",
    "UAV SHADOW-1: inf element moving to alternate position, direction S",
]


async def run_drone_spots(client: httpx.AsyncClient,
                          all_ops: list[SimOp],
                          units: list[OpforUnit],
                          speed_mult: float) -> None:
    real_interval = DRONE_S / speed_mult
    await asyncio.sleep(real_interval * 0.3)
    count    = 0
    drone_op = next((o for o in all_ops if o.callsign == "1PLT-HQ3"), None)
    if not drone_op:
        return
    while True:
        await asyncio.sleep(real_interval)
        if not drone_op.token or drone_op.lat == 0 or not units:
            continue
        target = random.choice(units)
        notes  = random.choice(_DRONE_NOTES)
        count += 1
        payload = {
            "grid":        grid(target.lat, target.lon),
            "direction":   random.choice(["N","NE","E","SE","S","SW","W","NW"]),
            "distance":    int(dist_m(drone_op.lat, drone_op.lon,
                                      target.lat, target.lon)),
            "description": notes,
        }
        r = await _api(client, "POST", "/reports", token=drone_op.token,
                       json={"type": "SPOT", "payload": payload})
        if r:
            log.info("SHADOW-1 SPOT #%-3d  %-12s  %.0f m away",
                     count, target.etype, payload["distance"])
        await _api(client, "POST", "/messages", token=drone_op.token,
                   json={"content": f"SHADOW-1: {notes} -- grid {payload['grid']}",
                         "message_type": "BROADCAST"})


# ---------------------------------------------------------------------------
# TIC + CASEVAC
# ---------------------------------------------------------------------------

_CASEVAC_INJURIES = [
    "GSW upper arm -- Category A (Priority)",
    "Blast fragmentation -- Category A (Immediate)",
    "GSW abdomen -- Category A (Immediate)",
    "Concussion and laceration -- Category B (Delayed)",
    "GSW leg -- Category A (Priority), tourniquet applied",
]


async def run_tic(client: httpx.AsyncClient,
                  all_ops: list[SimOp],
                  units: list[OpforUnit],
                  speed_mult: float) -> None:
    real_interval = TIC_CHECK_S / speed_mult
    cas_count = 0
    while True:
        await asyncio.sleep(real_interval)
        for u in units:
            if u.tic_fired:
                fwd_ops = [o for o in all_ops if o.lat != 0 and o.fwd_m > 100]
                if fwd_ops and all(dist_m(o.lat, o.lon, u.lat, u.lon) > TIC_RANGE_M * 3
                                   for o in fwd_ops):
                    u.tic_fired = False
                continue

            closest = min(
                (o for o in all_ops if o.token and o.lat != 0 and o.fwd_m > 150),
                key=lambda o: dist_m(o.lat, o.lon, u.lat, u.lon),
                default=None,
            )
            if not closest:
                continue
            d = dist_m(closest.lat, closest.lon, u.lat, u.lon)
            if d > TIC_RANGE_M:
                continue

            u.tic_fired = True
            cas_count  += 1
            log.info("TIC! %-10s  %.0f m from %-12s  (#%d)",
                     closest.callsign, d, u.etype, cas_count)

            # TIC alert
            await _api(client, "POST", "/alerts", token=closest.token,
                       json={"type": "TIC",
                             "latitude":  round(closest.lat, 6),
                             "longitude": round(closest.lon, 6)})

            # Contact broadcast
            await _api(client, "POST", "/messages", token=closest.token,
                       json={"content": (
                                 f"CONTACT -- {u.etype} grid {grid(u.lat, u.lon)}, "
                                 f"est {int(d)} m, engaging"
                             ),
                             "message_type": "BROADCAST"})

            # SPOT report
            await _api(client, "POST", "/reports", token=closest.token,
                       json={"type": "SPOT",
                             "payload": {
                                 "grid":        grid(u.lat, u.lon),
                                 "direction":   "DIRECT",
                                 "distance":    int(d),
                                 "description": f"TIC -- {u.etype}: {u.desc}",
                             }})

            # CASEVAC (~40 % chance)
            if random.random() < 0.4:
                injury  = random.choice(_CASEVAC_INJURIES)
                cas_g   = grid(closest.lat, closest.lon)
                plt_sgt = next((o for o in all_ops
                                if o.callsign == "1PLT-HQ2" and o.token), closest)
                r = await _api(client, "POST", "/reports", token=plt_sgt.token,
                               json={"type": "CASEVAC", "payload": {
                                   "line_1_callsign":    closest.callsign,
                                   "line_2_freq":        "38.450",
                                   "line_3_patients":    "1 litter, 0 ambulatory",
                                   "line_4_special":     "None",
                                   "line_5_nationality": "A -- Belgian military",
                                   "line_6_security":    "N -- no enemy in area",
                                   "line_7_marking":     "D -- VS-17 panel",
                                   "line_8_category":    "A -- urgent",
                                   "line_9_ztf":         "None",
                                   "grid":               cas_g,
                                   "injury":             injury,
                                   "latitude":           round(closest.lat, 6),
                                   "longitude":          round(closest.lon, 6),
                               }})
                if r:
                    log.info("CASEVAC #%d  %s  %s", cas_count, closest.callsign, injury[:45])
                await _api(client, "POST", "/messages", token=plt_sgt.token,
                           json={"content": (
                               f"9-LINE CASEVAC: 1 x {injury[:40]}, "
                               f"grid {cas_g} -- request DUSTOFF"
                           ), "message_type": "BROADCAST"})


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------

async def run_platoon(client: httpx.AsyncClient,
                      all_ops: list[SimOp],
                      speed_mult: float) -> None:
    real_dt = UPDATE_S / speed_mult
    centre_lat, centre_lon = WAYPOINTS[0]
    wp_idx  = 1
    bearing = march_bearing(centre_lat, centre_lon,
                            WAYPOINTS[wp_idx][0], WAYPOINTS[wp_idx][1])
    for op in all_ops:
        op.lat, op.lon = formation_pos(centre_lat, centre_lon,
                                       op.fwd_m, op.right_m, bearing)

    log.info("-- Platoon stepping off from Dendermonde --")
    total_steps = 0

    while True:
        target_lat, target_lon = WAYPOINTS[wp_idx]
        leg = "Dendermonde->Aalst" if wp_idx <= 3 else "Aalst->Dendermonde"

        while dist_m(centre_lat, centre_lon, target_lat, target_lon) > 5:
            new_clat, new_clon = step_towards(
                centre_lat, centre_lon, target_lat, target_lon,
                WALK_MS, real_dt * speed_mult,
            )
            bearing = march_bearing(new_clat, new_clon, target_lat, target_lon)
            centre_lat, centre_lon = new_clat, new_clon

            tasks = []
            for op in all_ops:
                if not op.token:
                    continue
                op.lat, op.lon = formation_pos(centre_lat, centre_lon,
                                               op.fwd_m, op.right_m, bearing)
                op.lat += random.gauss(0, 0.3) * LAT_DEG_PER_M
                op.lon += random.gauss(0, 0.3) * _lon_deg_per_m(op.lat)
                tasks.append(_api(client, "POST", "/tracking/position",
                                  token=op.token,
                                  json={"latitude":  round(op.lat, 6),
                                        "longitude": round(op.lon, 6),
                                        "altitude":  round(random.uniform(6, 18), 1)}))
            if tasks:
                await asyncio.gather(*tasks)

            total_steps += 1
            if total_steps % 6 == 0:
                d_left = dist_m(centre_lat, centre_lon, target_lat, target_lon)
                log.info("%-22s  %.0f m to WP%d", leg, d_left, wp_idx)

            await asyncio.sleep(real_dt)

        log.info("Reached WP%d  %.5f,%.5f", wp_idx, target_lat, target_lon)
        wp_idx = (wp_idx + 1) % len(WAYPOINTS)
        if wp_idx == 0:
            wp_idx = 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    global MISSION_ID

    # Apply --admin/--password aliases
    if ARGS.admin:
        ARGS.seed_admin = ARGS.admin
    if ARGS.password:
        ARGS.seed_admin_password = ARGS.password

    # Derive speed from --steps/--dt if --speed not explicitly given
    if ARGS.speed is None:
        if ARGS.dt is not None:
            ARGS.speed = UPDATE_S / ARGS.dt
        else:
            ARGS.speed = 1.0  # default

    all_ops, sections = _build_platoon()
    log.info("=== Op Dendermonde-Aalst -- PL Arrow simulator ===")
    log.info("Backend: %s  |  Operators: %d  |  Speed: %.1fx",
             BASE, len(all_ops), ARGS.speed)
    log.info("Walk %.1f km/h  update=%.0fs  drone=%.0fs  TIC=%.0fs",
             WALK_MS * 3.6,
             UPDATE_S    / ARGS.speed,
             DRONE_S     / ARGS.speed,
             TIC_CHECK_S / ARGS.speed)

    async with httpx.AsyncClient() as client:
        admin_token = await bootstrap(client, all_ops, sections)

        mid_lat = (WAYPOINTS[0][0] + WAYPOINTS[3][0]) / 2
        mid_lon = (WAYPOINTS[0][1] + WAYPOINTS[3][1]) / 2
        MISSION_ID = await sim_utils.create_mission_async(
            client, BASE, admin_token, ARGS.mission_name,
            description="PL Arrow -- 1 PLT Bravo Coy, Dendermonde -> Aalst, 5 km/h",
            map_center_lat=mid_lat, map_center_lng=mid_lon, map_zoom=13,
        )
        if MISSION_ID:
            log.info("Mission id=%d", MISSION_ID)

        await plant_opord(client, admin_token)
        enemy_units = await plant_enemy(client, admin_token)

        await login_all(client, all_ops)

        if ARGS.no_move:
            log.info("plan-only mode: skipping movement loop")
            return

        log.info("=== Simulation running -- Ctrl-C to stop ===")
        try:
            await asyncio.gather(
                run_platoon(client, all_ops, ARGS.speed),
                run_opfor_jitter(client, admin_token, enemy_units, ARGS.speed),
                run_drone_spots(client, all_ops, enemy_units, ARGS.speed),
                run_tic(client, all_ops, enemy_units, ARGS.speed),
            )
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    _timeout: float | None = (
        ARGS.steps * ARGS.dt
        if ARGS.steps is not None and ARGS.dt is not None
        else None
    )

    async def _run() -> None:
        try:
            if _timeout:
                await asyncio.wait_for(main(), timeout=_timeout)
            else:
                await main()
        except asyncio.TimeoutError:
            log.info("steps×dt duration elapsed — simulation complete")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("Simulator stopped.")
