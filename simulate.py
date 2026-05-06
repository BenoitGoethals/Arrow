#!/usr/bin/env python3
"""
Arrow Tactical Simulator — Operation Dendermonde
=================================================
Boots a full company (Delta Coy, ~40 operators) and drives them through
the real terrain of Dendermonde, Belgium in section-level formations.

Unit structure
  Delta Company
  ├─ DELTA-6 (company commander, ADMIN)
  └─ 3 Platoons (Alpha / Bravo / Charlie)
       └─ each: platoon commander (BATTLE_CAPTAIN) + 2 Sections
            └─ each section: 2 Teams × 3 soldiers

Movement model
  Approach to contact:  5.0 km/h (soldier walk)
  In objective area:    1.5 km/h (infiltration)
  Position update every 10 s (real time), scaled by --speed

Enemy / report generation
  Every 5 minutes (real time) one forward operator marks a contact or POI.

Usage
  uv run python simulate.py
  uv run python simulate.py --backend http://192.168.1.10:6001 --speed 6
  uv run python simulate.py --reset   # wipe sim operators first
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import random
from dataclasses import dataclass, field
from typing import Optional

import httpx

# ── CLI ───────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Arrow tactical simulator")
parser.add_argument("--backend", default="http://localhost:6001")
parser.add_argument("--speed", type=float, default=1.0,
                    help="Time multiplier: 6 = 6× faster, 1 = real time")
parser.add_argument("--reset", action="store_true",
                    help="Delete all sim operators before starting")
ARGS = parser.parse_args()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("sim")

# ── Simulation constants ──────────────────────────────────────────────────────

BASE = ARGS.backend.rstrip("/")
SIM_PASSWORD   = "Arrow2525!"
WALK_MS        = 5000 / 3600          # 5 km/h in m/s
INFIL_MS       = 1500 / 3600          # 1.5 km/h in m/s
UPDATE_S       = 10.0                 # real seconds between position pushes
ENEMY_S        = 300.0                # real seconds between enemy marks
SECTION_STAGGER_S = 120.0            # section 2 starts this many (real) seconds later

# ── Geographic helpers ────────────────────────────────────────────────────────

LAT_DEG_PER_M = 1 / 111_000.0

def lon_deg_per_m(lat: float) -> float:
    return 1 / (111_000.0 * math.cos(math.radians(lat)))

def dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = (lat2 - lat1) * 111_000
    dlon = (lon2 - lon1) * 111_000 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)

def step_towards(lat: float, lon: float,
                 tlat: float, tlon: float,
                 speed_ms: float, dt: float) -> tuple[float, float]:
    """Move (lat,lon) toward (tlat,tlon) at speed_ms for dt seconds."""
    d = dist_m(lat, lon, tlat, tlon)
    if d < 0.5:
        return tlat, tlon
    move = min(speed_ms * dt, d)
    dlat = (tlat - lat) * 111_000
    dlon = (tlon - lon) * 111_000 * math.cos(math.radians(lat))
    brg  = math.atan2(dlon, dlat)
    return (
        lat + move * math.cos(brg) * LAT_DEG_PER_M,
        lon + move * math.sin(brg) * lon_deg_per_m(lat),
    )

def jitter(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    """Offset a coordinate by fixed north/east meters (formation spread)."""
    return (
        lat + north_m * LAT_DEG_PER_M,
        lon + east_m  * lon_deg_per_m(lat),
    )

# ── Unit tree definition ──────────────────────────────────────────────────────

# Formation offsets per position in section [section_leader, r1, r2, tl, r3, r4]
# (north_m, east_m) — section moves northward by default
_FORMATION: list[tuple[float, float]] = [
    (  8,  0),   # S1-T1: section leader (front centre)
    (  0, -8),   # S1-T1: rifleman left
    (  0,  8),   # S1-T1: rifleman right
    (-12, -4),   # S1-T2: team leader (rear left)
    (-12,  4),   # S1-T2: rifleman right
    (-20,  0),   # S1-T2: rifleman rear
]

@dataclass
class SimOp:
    callsign: str
    rank: str
    role: str
    formation_idx: int          # index into _FORMATION
    token:   str  = ""
    op_id:   int  = 0
    lat:     float = 0.0
    lon:     float = 0.0

@dataclass
class SimSection:
    name:          str
    platoon_code:  str          # ALPHA / BRAVO / CHARLIE
    section_num:   int          # 1 or 2
    operators:     list[SimOp] = field(default_factory=list)

def _build_sections() -> tuple[list[SimOp], list[SimSection]]:
    """Return (all_operators, all_sections) for Delta Company."""
    all_ops:      list[SimOp]      = []
    all_sections: list[SimSection] = []

    platoons = [
        ("ALPHA",   "1st Platoon (Alpha)"),
        ("BRAVO",   "2nd Platoon (Bravo)"),
        ("CHARLIE", "3rd Platoon (Charlie)"),
    ]

    for plt_code, _ in platoons:
        for sec_num in (1, 2):
            sec = SimSection(
                name         = f"{sec_num}st Section {plt_code.capitalize()}",
                platoon_code = plt_code,
                section_num  = sec_num,
            )
            # Two teams, three soldiers each
            for team_num in (1, 2):
                for mbr_num in (1, 2, 3):
                    form_idx = (team_num - 1) * 3 + (mbr_num - 1)
                    is_sl    = sec_num == 1 and team_num == 1 and mbr_num == 1
                    is_tl    = mbr_num == 1 and not is_sl
                    callsign = f"{plt_code}-{sec_num}{team_num}{mbr_num}"
                    rank     = "OR-6" if is_sl else ("OR-5" if is_tl else "OR-3")
                    op = SimOp(callsign=callsign, rank=rank, role="OPERATOR",
                               formation_idx=form_idx)
                    sec.operators.append(op)
                    all_ops.append(op)

            all_sections.append(sec)

    # Platoon commanders & company commander (not in sections, move freely)
    for plt_code, _ in platoons:
        op = SimOp(callsign=f"{plt_code}-6", rank="OF-1",
                   role="BATTLE_CAPTAIN", formation_idx=0)
        all_ops.append(op)

    cmd = SimOp(callsign="DELTA-6", rank="OF-3", role="ADMIN", formation_idx=0)
    all_ops.append(cmd)

    return all_ops, all_sections

# ── Dendermonde routes ────────────────────────────────────────────────────────
# Three platoon axes through real Dendermonde terrain.
# phase_infil_start: waypoint index where speed drops to infiltration pace.

ROUTES: dict[str, dict] = {
    "ALPHA": {
        "phase_infil_start": 2,
        "waypoints": [
            (51.0185, 4.0975),   # 0  Staging south (Baasrode industrial)
            (51.0220, 4.0990),   # 1  South approach, N449
            (51.0260, 4.1005),   # 2  Entering city, Gentsestraat  ← infil
            (51.0285, 4.1010),   # 3  Grote Markt
            (51.0315, 4.1030),   # 4  North centre (Zwijveke)
            (51.0352, 4.1055),   # 5  Objective: Bogaerdpark north
            (51.0328, 4.1020),   # 6  Consolidation / pull-back
            (51.0185, 4.0975),   # 7  Loop: return to staging
        ],
    },
    "BRAVO": {
        "phase_infil_start": 2,
        "waypoints": [
            (51.0185, 4.0875),   # 0  Staging southwest (Grembergen)
            (51.0215, 4.0898),   # 1  West approach
            (51.0255, 4.0928),   # 2  Scheldt riverside  ← infil
            (51.0290, 4.0942),   # 3  Riverside west bank
            (51.0328, 4.0960),   # 4  North riverside
            (51.0362, 4.0990),   # 5  Objective: north bridge (Scheldebrug)
            (51.0340, 4.0952),   # 6  Consolidation west
            (51.0185, 4.0875),   # 7  Loop
        ],
    },
    "CHARLIE": {
        "phase_infil_start": 2,
        "waypoints": [
            (51.0185, 4.1135),   # 0  Staging southeast (Lebbeke)
            (51.0222, 4.1155),   # 1  East approach
            (51.0260, 4.1162),   # 2  Industrial east  ← infil
            (51.0288, 4.1140),   # 3  East of city centre
            (51.0322, 4.1112),   # 4  Northeast
            (51.0358, 4.1088),   # 5  Objective northeast
            (51.0332, 4.1055),   # 6  Consolidation east
            (51.0185, 4.1135),   # 7  Loop
        ],
    },
}

# Route for command element (follows centre axis loosely)
CMD_WAYPOINTS: list[tuple[float, float]] = [
    (51.0195, 4.0980),
    (51.0250, 4.0995),
    (51.0300, 4.1010),
    (51.0340, 4.1030),
    (51.0300, 4.1010),
    (51.0195, 4.0980),
]

# ── Enemy / report catalogue ─────────────────────────────────────────────────

_EVENTS = [
    dict(kind="enemy", type="INFANTRY",  sidc="SHGPUCI-----", weight=4,
         notes="Infantry element observed, approx squad strength"),
    dict(kind="enemy", type="ARMOR",     sidc="SHGPUCA-----", weight=2,
         notes="Armoured vehicle sighted, direction of movement unknown"),
    dict(kind="enemy", type="VEHICLE",   sidc="SHGPEV------", weight=3,
         notes="Unknown vehicle, possible recce element"),
    dict(kind="enemy", type="ARTILLERY", sidc="SHGPUCF-----", weight=1,
         notes="Suspected artillery or mortar position"),
    dict(kind="enemy", type="SNIPER",    sidc="SHGPUCIS----", weight=1,
         notes="Sniper fire received from elevated position"),
    dict(kind="enemy", type="UNKNOWN",   sidc="SUGPU-------", weight=2,
         notes="Unknown contact, further observation required"),
    dict(kind="poi",   type="POI",       sidc="SNGPI-------", weight=3,
         notes="Point of interest — possible cache / ORP"),
    dict(kind="report", type="SPOT",    sidc="",              weight=2,
         notes=""),
]
_EVENT_WEIGHTS = [e["weight"] for e in _EVENTS]

SPOT_DIRECTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
SPOT_DISTANCES  = [50, 100, 150, 200, 300, 400, 500]

# ── HTTP helpers ──────────────────────────────────────────────────────────────

async def api(client: httpx.AsyncClient, method: str, path: str,
              token: str = "", **kwargs) -> Optional[dict]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = await client.request(method, f"{BASE}{path}",
                                 headers=headers, timeout=10, **kwargs)
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 409:
            return None   # already exists
        log.warning("%-6s %-30s → %d  %s", method, path, r.status_code, r.text[:80])
        return None
    except Exception as exc:
        log.warning("%-6s %-30s → %s", method, path, exc)
        return None

async def login(client: httpx.AsyncClient, callsign: str) -> Optional[str]:
    try:
        r = await client.post(f"{BASE}/auth/login",
                              data={"username": callsign, "password": SIM_PASSWORD},
                              timeout=10)
        if r.status_code == 200:
            return r.json()["access_token"]
    except Exception:
        pass
    return None

# ── Bootstrap ─────────────────────────────────────────────────────────────────

async def bootstrap(client: httpx.AsyncClient,
                    all_ops: list[SimOp],
                    sections: list[SimSection]) -> str:
    """
    Ensure Delta Company + full hierarchy exists.
    Register operators if needed, assign them to their teams.
    Returns admin token.
    """
    log.info("── Bootstrap ─────────────────────────────────────────")

    # 1. Admin account
    admin_op = next(o for o in all_ops if o.role == "ADMIN")
    admin_token = await login(client, admin_op.callsign)
    if not admin_token:
        r = await api(client, "POST", "/auth/register", json={
            "callsign": admin_op.callsign, "password": SIM_PASSWORD,
            "rank": admin_op.rank, "role": "ADMIN",
        })
        if r:
            admin_token = r["access_token"]
            log.info("Registered %s (ADMIN)", admin_op.callsign)
        else:
            raise RuntimeError("Cannot create admin operator")
    admin_op.token = admin_token

    # 2. Company
    companies = await api(client, "GET", "/companies") or []
    company = next((c for c in companies if c["name"] == "Delta Company"), None)
    if not company:
        company = await api(client, "POST", "/companies", token=admin_token,
                            json={"name": "Delta Company"})
        log.info("Created Delta Company (id=%d)", company["id"])
    company_id = company["id"]

    # 3. Platoons → sections → teams
    #    We walk through sections and build the tree lazily.
    plt_ids:  dict[str, int] = {}   # code → id
    sec_ids:  dict[str, int] = {}   # "{code}-{num}" → id

    platoons_resp = await api(client, "GET", "/platoons") or []
    for p in platoons_resp:
        for code, name in [("ALPHA","1st Platoon (Alpha)"),
                           ("BRAVO","2nd Platoon (Bravo)"),
                           ("CHARLIE","3rd Platoon (Charlie)")]:
            if p["name"] == name:
                plt_ids[code] = p["id"]

    for code, name in [("ALPHA","1st Platoon (Alpha)"),
                       ("BRAVO","2nd Platoon (Bravo)"),
                       ("CHARLIE","3rd Platoon (Charlie)")]:
        if code not in plt_ids:
            r = await api(client, "POST", "/platoons", token=admin_token,
                          json={"name": name, "company_id": company_id})
            if r:
                plt_ids[code] = r["id"]
                log.info("  Created platoon %s (id=%d)", name, r["id"])

    sections_resp = await api(client, "GET", "/sections") or []
    for s in sections_resp:
        for sec in sections:
            if s["name"] == sec.name:
                sec_ids[f"{sec.platoon_code}-{sec.section_num}"] = s["id"]

    teams_resp = await api(client, "GET", "/teams") or []
    team_name_to_id: dict[str, int] = {t["name"]: t["id"] for t in teams_resp}

    for sec in sections:
        sec_key = f"{sec.platoon_code}-{sec.section_num}"
        if sec_key not in sec_ids:
            r = await api(client, "POST", "/sections", token=admin_token,
                          json={"name": sec.name,
                                "platoon_id": plt_ids[sec.platoon_code]})
            if r:
                sec_ids[sec_key] = r["id"]
                log.info("    Created section %s (id=%d)", sec.name, r["id"])

        sec_id = sec_ids.get(sec_key)
        if not sec_id:
            continue

        # Two teams per section
        for team_num in (1, 2):
            team_name = f"Team {sec.platoon_code}-{sec.section_num}{team_num}"
            if team_name not in team_name_to_id:
                r = await api(client, "POST", "/teams", token=admin_token,
                              json={"name": team_name, "section_id": sec_id})
                if r:
                    team_name_to_id[team_name] = r["id"]
                    log.info("      Created team %s (id=%d)", team_name, r["id"])

    # 4. Register all non-admin operators + assign to teams
    log.info("── Registering operators ─────────────────────────────")
    existing_ops = {o["callsign"]: o for o in (await api(client, "GET", "/operators",
                                                          token=admin_token) or [])}

    for sec in sections:
        sec_key = f"{sec.platoon_code}-{sec.section_num}"
        for team_idx, op in enumerate(sec.operators):
            team_num  = (team_idx // 3) + 1
            team_name = f"Team {sec.platoon_code}-{sec.section_num}{team_num}"
            team_id   = team_name_to_id.get(team_name)

            if op.callsign not in existing_ops:
                r = await api(client, "POST", "/auth/register", json={
                    "callsign": op.callsign, "password": SIM_PASSWORD,
                    "rank": op.rank, "role": op.role,
                })
                if r:
                    log.info("  Registered %-14s (%s)", op.callsign, op.rank)
                    existing_ops[op.callsign] = {"id": None}  # re-fetch below

            # Assign to team via admin patch
            op_row = existing_ops.get(op.callsign)
            if op_row and team_id and op_row.get("team_id") != team_id:
                ops_fresh = await api(client, "GET", "/operators",
                                      token=admin_token) or []
                op_row = next((o for o in ops_fresh
                               if o["callsign"] == op.callsign), None)
                if op_row:
                    await api(client, "PATCH", f"/operators/{op_row['id']}",
                              token=admin_token, json={"team_id": team_id})
                    op.op_id = op_row["id"]

    # 5. Register platoon commanders
    for plt_code, _ in [("ALPHA",""), ("BRAVO",""), ("CHARLIE","")]:
        callsign = f"{plt_code}-6"
        bc_op = next((o for o in all_ops if o.callsign == callsign), None)
        if bc_op and callsign not in existing_ops:
            r = await api(client, "POST", "/auth/register", json={
                "callsign": callsign, "password": SIM_PASSWORD,
                "rank": "OF-1", "role": "BATTLE_CAPTAIN",
            })
            if r:
                log.info("  Registered %-14s (BATTLE_CAPTAIN)", callsign)

    log.info("── Bootstrap complete ────────────────────────────────")
    return admin_token

# ── Login all operators ───────────────────────────────────────────────────────

async def login_all(client: httpx.AsyncClient, all_ops: list[SimOp]) -> None:
    log.info("── Logging in %d operators ───────────────────────────", len(all_ops))
    tasks = [login(client, op.callsign) for op in all_ops]
    tokens = await asyncio.gather(*tasks)
    ok, fail = 0, 0
    for op, tok in zip(all_ops, tokens):
        if tok:
            op.token = tok
            ok += 1
        else:
            log.warning("  Login failed for %s", op.callsign)
            fail += 1
    log.info("  %d OK  %d failed", ok, fail)

    # Resolve op_ids
    admin_op = next((o for o in all_ops if o.role == "ADMIN"), None)
    if admin_op and admin_op.token:
        rows = await api(client, "GET", "/operators", token=admin_op.token) or []
        callsign_to_id = {r["callsign"]: r["id"] for r in rows}
        for op in all_ops:
            op.op_id = callsign_to_id.get(op.callsign, 0)

# ── Movement coroutines ───────────────────────────────────────────────────────

async def run_section(client: httpx.AsyncClient,
                      sec: SimSection,
                      speed_mult: float,
                      stagger_s: float) -> None:
    """Move all operators in this section along their platoon route."""
    route = ROUTES[sec.platoon_code]
    waypoints    = route["waypoints"]
    infil_start  = route["phase_infil_start"]
    real_dt      = UPDATE_S / speed_mult

    # Wait for stagger
    if stagger_s > 0:
        await asyncio.sleep(stagger_s / speed_mult)

    # Seed starting positions
    start = waypoints[0]
    for i, op in enumerate(sec.operators):
        off = _FORMATION[min(i, len(_FORMATION) - 1)]
        op.lat, op.lon = jitter(start[0], start[1], off[0], off[1])

    wp_idx = 0
    log.info("Section %-20s → departing WP0 %s", sec.name,
             "walk" if wp_idx < infil_start else "infil")

    while True:
        target_lat, target_lon = waypoints[wp_idx]
        speed = INFIL_MS if wp_idx >= infil_start else WALK_MS

        # Advance until waypoint reached
        while True:
            # Move section centre first, then apply formation offsets per op
            centre_lat, centre_lon = (
                sec.operators[0].lat, sec.operators[0].lon
            )
            new_clat, new_clon = step_towards(
                centre_lat, centre_lon,
                target_lat, target_lon,
                speed, real_dt * speed_mult,   # real distance in real dt
            )
            dlat = new_clat - centre_lat
            dlon = new_clon - centre_lon

            tasks = []
            for i, op in enumerate(sec.operators):
                if not op.token:
                    continue
                off = _FORMATION[min(i, len(_FORMATION) - 1)]
                op.lat = op.lat + dlat + random.gauss(0, 0.2) * LAT_DEG_PER_M
                op.lon = op.lon + dlon + random.gauss(0, 0.2) * lon_deg_per_m(op.lat)
                tasks.append(api(client, "POST", "/tracking/position",
                                 token=op.token,
                                 json={"latitude": op.lat,
                                       "longitude": op.lon,
                                       "altitude": round(random.uniform(4, 12), 1)}))
            if tasks:
                await asyncio.gather(*tasks)

            await asyncio.sleep(real_dt)

            if dist_m(new_clat, new_clon, target_lat, target_lon) < 5:
                break

        wp_idx = (wp_idx + 1) % len(waypoints)
        log.info("Section %-20s → WP%d  %s", sec.name, wp_idx,
                 "infil" if wp_idx >= infil_start else "walk")

async def run_command(client: httpx.AsyncClient,
                      all_ops: list[SimOp],
                      speed_mult: float) -> None:
    """Move platoon commanders and company CO along the centre axis."""
    cmd_ops = [o for o in all_ops if o.role in ("ADMIN", "BATTLE_CAPTAIN")]
    real_dt  = UPDATE_S / speed_mult
    wp_idx   = 0

    for i, op in enumerate(cmd_ops):
        wp = CMD_WAYPOINTS[0]
        op.lat = wp[0] + i * 0.0003
        op.lon = wp[1] + i * 0.0002

    while True:
        tlat, tlon = CMD_WAYPOINTS[wp_idx]
        while True:
            tasks = []
            for op in cmd_ops:
                if not op.token:
                    continue
                op.lat, op.lon = step_towards(op.lat, op.lon, tlat, tlon,
                                              WALK_MS, real_dt * speed_mult)
                op.lat += random.gauss(0, 0.3) * LAT_DEG_PER_M
                op.lon += random.gauss(0, 0.3) * lon_deg_per_m(op.lat)
                tasks.append(api(client, "POST", "/tracking/position",
                                 token=op.token,
                                 json={"latitude": op.lat, "longitude": op.lon}))
            if tasks:
                await asyncio.gather(*tasks)
            await asyncio.sleep(real_dt)
            if dist_m(op.lat, op.lon, tlat, tlon) < 10:
                break

        wp_idx = (wp_idx + 1) % len(CMD_WAYPOINTS)

# ── Enemy / report coroutine ──────────────────────────────────────────────────

async def run_enemy_marker(client: httpx.AsyncClient,
                           sections: list[SimSection],
                           speed_mult: float) -> None:
    """Every ENEMY_S real seconds pick a random front operator and mark a contact."""
    real_interval = ENEMY_S / speed_mult
    await asyncio.sleep(real_interval * 0.3)   # initial offset

    marker_count = 0
    while True:
        await asyncio.sleep(real_interval)

        # Pick a random forward section
        live_sections = [s for s in sections
                         if any(o.token and o.lat != 0 for o in s.operators)]
        if not live_sections:
            continue

        sec  = random.choice(live_sections)
        op   = random.choice([o for o in sec.operators if o.token and o.lat != 0])
        evt  = random.choices(_EVENTS, weights=_EVENT_WEIGHTS)[0]

        # Place the contact slightly ahead of the operator
        spread_m = random.uniform(50, 300)
        brg_rad  = random.uniform(0, 2 * math.pi)
        clat = op.lat + spread_m * math.cos(brg_rad) * LAT_DEG_PER_M
        clon = op.lon + spread_m * math.sin(brg_rad) * lon_deg_per_m(op.lat)

        marker_count += 1

        if evt["kind"] == "report":
            direction = random.choice(SPOT_DIRECTIONS)
            distance  = random.choice(SPOT_DISTANCES)
            payload   = {
                "grid":     f"{clat:.4f},{clon:.4f}",
                "direction": direction,
                "distance":  distance,
                "description": "Contact spotted, awaiting orders",
            }
            r = await api(client, "POST", "/reports", token=op.token,
                          json={"type": "SPOT", "payload": payload})
            if r:
                log.info("📋  %s  SPOT REPORT  %s %dm  (#%d)",
                         op.callsign, direction, distance, marker_count)

        else:
            r = await api(client, "POST", "/tactical-objects", token=op.token,
                          json={"type":        evt["type"],
                                "symbol_code": evt["sidc"],
                                "latitude":    round(clat, 6),
                                "longitude":   round(clon, 6),
                                "notes":       evt["notes"],
                                "visibility":  "COMPANY"})
            if r:
                emoji = "⚠️ " if evt["kind"] == "enemy" else "📍"
                log.info("%s %s  marked %-12s at %.4f,%.4f  (#%d)",
                         emoji, op.callsign, evt["type"],
                         clat, clon, marker_count)

        # Operator broadcasts a short contact report
        if op.token:
            msg_map = {
                "INFANTRY":  f"CONTACT — infantry element, grid {clat:.4f} {clon:.4f}",
                "ARMOR":     f"CONTACT — armour, grid {clat:.4f} {clon:.4f}",
                "SNIPER":    "CONTACT — sniper fire received, taking cover",
                "UNKNOWN":   f"CONTACT WAIT OUT — unknown element, grid {clat:.4f} {clon:.4f}",
                "POI":       f"INFO — POI located, grid {clat:.4f} {clon:.4f}",
            }
            content = msg_map.get(evt["type"],
                                  f"CONTACT — {evt['type']} at {clat:.4f},{clon:.4f}")
            await api(client, "POST", "/messages", token=op.token,
                      json={"content": content, "message_type": "BROADCAST"})

# ── Reset helper ──────────────────────────────────────────────────────────────

async def reset_sim(client: httpx.AsyncClient, all_ops: list[SimOp]) -> None:
    """Delete all sim operators (requires admin login to succeed first)."""
    log.info("── Reset: deleting sim operators ─────────────────────")
    admin_op = next((o for o in all_ops if o.role == "ADMIN"), None)
    if not admin_op:
        return
    token = await login(client, admin_op.callsign)
    if not token:
        log.warning("Cannot login as admin — skipping reset")
        return
    rows = await api(client, "GET", "/operators", token=token) or []
    sim_callsigns = {o.callsign for o in all_ops}
    for row in rows:
        if row["callsign"] in sim_callsigns:
            await api(client, "DELETE", f"/operators/{row['id']}", token=token)
            log.info("  Deleted %s", row["callsign"])

# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    all_ops, sections = _build_sections()
    speed_mult = ARGS.speed

    log.info("=== Arrow Tactical Simulator — Operation Dendermonde ===")
    log.info("Backend : %s", BASE)
    log.info("Operators: %d  |  Sections: %d  |  Speed: %.1f×",
             len(all_ops), len(sections), speed_mult)
    log.info("Walk %.1f km/h  Infil %.1f km/h  Update every %gs  Enemy every %gs",
             WALK_MS * 3.6, INFIL_MS * 3.6,
             UPDATE_S / speed_mult, ENEMY_S / speed_mult)

    async with httpx.AsyncClient() as client:

        if ARGS.reset:
            await reset_sim(client, all_ops)

        await bootstrap(client, all_ops, sections)
        await login_all(client, all_ops)

        # Gather all coroutines
        coros = []

        # Section movement — section 2 of each platoon staggers by SECTION_STAGGER_S
        for sec in sections:
            stagger = 0.0 if sec.section_num == 1 else SECTION_STAGGER_S
            coros.append(run_section(client, sec, speed_mult, stagger))

        # Command element
        coros.append(run_command(client, all_ops, speed_mult))

        # Enemy / report marker
        coros.append(run_enemy_marker(client, sections, speed_mult))

        log.info("=== Simulation running — Ctrl-C to stop ===")
        try:
            await asyncio.gather(*coros)
        except asyncio.CancelledError:
            pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Simulator stopped.")
