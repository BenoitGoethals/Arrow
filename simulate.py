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
import json
import logging
import math
import random
from dataclasses import dataclass, field
from typing import Optional

import httpx

import sim_utils
from sim_utils import LAT_DEG_PER_M, lon_deg_per_m, dist_m, step_towards, jitter, mgrs

# ── CLI ───────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Arrow tactical simulator")
parser.add_argument("--backend", default="https://78.21.255.210:6200/api")
parser.add_argument("--speed", type=float, default=1.0,
                    help="Time multiplier: 6 = 6× faster, 1 = real time")
parser.add_argument("--reset", action="store_true",
                    help="Delete all sim operators before starting")
parser.add_argument("--seed-admin", default="benoit",
                    help="Callsign of the pre-seeded ADMIN used to bootstrap (default: benoit)")
parser.add_argument("--seed-admin-password", default="ranger14",
                    help="Password for --seed-admin (default: ranger14)")
parser.add_argument("--mission-name", default="Operation Dendermonde",
                    help="Mission name to create or adopt (default: Operation Dendermonde)")
ARGS = parser.parse_args()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("sim")

# ── Simulation constants ──────────────────────────────────────────────────────

SIM_PASSWORD   = "Arrow2525!"
_CTX           = sim_utils.AsyncSimContext(ARGS.backend.rstrip("/"), SIM_PASSWORD)
api            = _CTX.api
login          = _CTX.login
WALK_MS        = 5000 / 3600          # 5 km/h in m/s
INFIL_MS       = 1500 / 3600          # 1.5 km/h in m/s
UPDATE_S       = 10.0                 # real seconds between position pushes
ENEMY_S        = 10.0                 # real seconds between enemy marks
SECTION_STAGGER_S = 120.0            # section 2 starts this many (real) seconds later
CBRN_S         = 90.0                 # real seconds between worldwide CBRN incidents
CAS_S          = 60.0                 # real seconds between CAS requests

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

## Operation IRON ARDENNES — three platoons attack three of the four villages
## (the 4th, Vielsalm, gets static graphics + OPFOR only).
## Each waypoint pair = (lat, lon); element transits from AA to OBJ centre.

ROUTES: dict[str, dict] = {
    # ALPHA platoon → A CO axis on OBJ HAWK at Bastogne (attack E → W)
    "ALPHA": {
        "phase_infil_start": 2,
        "waypoints": [
            (50.0028, 5.7450),   # 0  AA east of Bastogne
            (50.0030, 5.7350),   # 1  LD, on the N4
            (50.0029, 5.7275),   # 2  PL ATTACK  ← infil pace
            (50.0028, 5.7220),   # 3  PL OBJ
            (50.0028, 5.7178),   # 4  OBJ HAWK centre (Bastogne square)
            (50.0033, 5.7165),   # 5  Consolidation N
            (50.0028, 5.7450),   # 6  Loop back to AA
        ],
    },
    # BRAVO platoon → B CO axis on OBJ EAGLE at Houffalize (NE → SW)
    "BRAVO": {
        "phase_infil_start": 2,
        "waypoints": [
            (50.1450, 5.8050),   # 0  AA NE of Houffalize
            (50.1390, 5.7990),   # 1  LD
            (50.1340, 5.7945),   # 2  PL ATTACK  ← infil
            (50.1315, 5.7925),   # 3  PL OBJ
            (50.1300, 5.7910),   # 4  OBJ EAGLE centre (Houffalize bridge)
            (50.1310, 5.7895),   # 5  Consolidation
            (50.1450, 5.8050),   # 6  Loop
        ],
    },
    # CHARLIE platoon → C CO axis on OBJ FALCON at La Roche-en-Ardenne (W → E)
    "CHARLIE": {
        "phase_infil_start": 2,
        "waypoints": [
            (50.1817, 5.5500),   # 0  AA west of La Roche
            (50.1817, 5.5620),   # 1  LD
            (50.1817, 5.5710),   # 2  PL ATTACK  ← infil
            (50.1817, 5.5760),   # 3  PL OBJ
            (50.1817, 5.5783),   # 4  OBJ FALCON centre (La Roche castle)
            (50.1822, 5.5798),   # 5  Consolidation
            (50.1817, 5.5500),   # 6  Loop
        ],
    },
}

# Route for command element — circulates between the three active objectives.
CMD_WAYPOINTS: list[tuple[float, float]] = [
    (50.0028, 5.7300),   # near Bastogne axis
    (50.1300, 5.7910),   # Houffalize OBJ
    (50.1817, 5.5783),   # La Roche OBJ
    (50.2811, 5.9128),   # Vielsalm (overwatch, no friendly platoon)
    (50.1300, 5.7910),
    (50.0028, 5.7300),
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

    # 1. Seed admin — already created by backend/storage/seed.py (benoit/ranger14
    #    by default). All authenticated bootstrap calls go through this token.
    seed_token = await login(client, ARGS.seed_admin, ARGS.seed_admin_password)
    if not seed_token:
        raise RuntimeError(
            f"Cannot login as seed admin {ARGS.seed_admin!r}. "
            "Ensure the backend has been seeded (it auto-seeds on first boot) "
            "and pass --seed-admin / --seed-admin-password if you've changed them."
        )
    log.info("Logged in as seed admin %s", ARGS.seed_admin)

    # 2. Sim company commander (DELTA-6) — register if missing, ensure ADMIN role.
    #    All bootstrap reads/writes go through the seed admin token (guaranteed ADMIN);
    #    DELTA-6's own token is only used for DELTA-6's own actions later.
    admin_token = seed_token
    admin_op = next(o for o in all_ops if o.role == "ADMIN")
    sim_admin_token = await login(client, admin_op.callsign)
    if not sim_admin_token:
        r = await api(client, "POST", "/auth/register/admin", token=seed_token, json={
            "callsign": admin_op.callsign, "password": SIM_PASSWORD,
            "rank": admin_op.rank, "role": "ADMIN",
        })
        if r and r.get("access_token"):
            sim_admin_token = r["access_token"]
            log.info("Registered %s (ADMIN)", admin_op.callsign)
    else:
        # DELTA-6 already exists; make sure it's actually ADMIN (an earlier run
        # may have created it as OPERATOR via the un-elevated /auth/register).
        ops = await api(client, "GET", "/operators", token=seed_token) or []
        row = next((o for o in ops if o["callsign"] == admin_op.callsign), None)
        if row and row.get("role") != "ADMIN":
            patched = await api(client, "PATCH", f"/operators/{row['id']}",
                                token=seed_token, json={"role": "ADMIN"})
            if patched:
                log.info("Promoted %s to ADMIN (was %s)", admin_op.callsign, row.get("role"))
                # Re-login to obtain a token with the elevated role claim.
                sim_admin_token = await login(client, admin_op.callsign) or sim_admin_token

    admin_op.token = sim_admin_token or seed_token

    # 3. Company
    companies = await api(client, "GET", "/companies", token=admin_token) or []
    company = next((c for c in companies if c["name"] == "Delta Company"), None)
    if not company:
        company = await api(client, "POST", "/companies", token=admin_token,
                            json={"name": "Delta Company"})
        if not company:
            raise RuntimeError("Failed to create Delta Company (insufficient role?)")
        log.info("Created Delta Company (id=%d)", company["id"])
    company_id = company["id"]

    # 4. Platoons → sections → teams
    #    We walk through sections and build the tree lazily.
    plt_ids:  dict[str, int] = {}   # code → id
    sec_ids:  dict[str, int] = {}   # "{code}-{num}" → id

    platoons_resp = await api(client, "GET", "/platoons", token=admin_token) or []
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

    sections_resp = await api(client, "GET", "/sections", token=admin_token) or []
    for s in sections_resp:
        for sec in sections:
            if s["name"] == sec.name:
                sec_ids[f"{sec.platoon_code}-{sec.section_num}"] = s["id"]

    teams_resp = await api(client, "GET", "/teams", token=admin_token) or []
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

    # 5. Register / fix all operators — team_id included at creation (atomic)
    log.info("── Registering / assigning operators ────────────────")
    existing_ops = {o["callsign"]: o
                    for o in (await api(client, "GET", "/operators",
                                        token=admin_token) or [])}

    for sec in sections:
        for team_idx, op in enumerate(sec.operators):
            team_num  = (team_idx // 3) + 1
            team_name = f"Team {sec.platoon_code}-{sec.section_num}{team_num}"
            team_id   = team_name_to_id.get(team_name)
            ex        = existing_ops.get(op.callsign)

            if not ex:
                # New operator — register with team_id already set.
                # Use the admin-elevated endpoint so the requested role sticks.
                r = await api(client, "POST", "/auth/register/admin",
                              token=admin_token, json={
                    "callsign": op.callsign, "password": SIM_PASSWORD,
                    "rank": op.rank, "role": op.role,
                    "team_id": team_id,
                })
                if r:
                    log.info("  Registered %-14s (%s) → team %s",
                             op.callsign, op.rank, team_name)
            else:
                op.op_id = ex.get("id", 0)
                # Fix unassigned or wrong-team operators
                if team_id and ex.get("team_id") != team_id:
                    await api(client, "PATCH", f"/operators/{ex['id']}",
                              token=admin_token, json={"team_id": team_id})
                    log.info("  Assigned  %-14s → team %s", op.callsign, team_name)

    # Resolve op_ids for newly registered operators
    ops_all = {o["callsign"]: o
               for o in (await api(client, "GET", "/operators",
                                   token=admin_token) or [])}
    for sec in sections:
        for op in sec.operators:
            row = ops_all.get(op.callsign)
            if row:
                op.op_id = row["id"]

    # 6. Register platoon commanders (unassigned — command element)
    for plt_code, _ in [("ALPHA",""), ("BRAVO",""), ("CHARLIE","")]:
        callsign = f"{plt_code}-6"
        if callsign not in ops_all:
            r = await api(client, "POST", "/auth/register/admin",
                          token=admin_token, json={
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
        wlat, wlon = waypoints[wp_idx]
        log.info("Section %-20s → WP%d  %-24s  %s",
                 sec.name, wp_idx, mgrs(wlat, wlon),
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

        grid = mgrs(clat, clon)

        if evt["kind"] == "report":
            direction = random.choice(SPOT_DIRECTIONS)
            distance  = random.choice(SPOT_DISTANCES)
            payload   = {
                "grid":        grid,
                "direction":   direction,
                "distance":    distance,
                "description": "Contact spotted, awaiting orders",
            }
            r = await api(client, "POST", "/reports", token=op.token,
                          json={"type": "SPOT", "payload": payload})
            if r:
                log.info("📋  %s  SPOT REPORT  %s %dm  grid %s  (#%d)",
                         op.callsign, direction, distance, grid, marker_count)

        else:
            notes = f"{evt['notes']}  MGRS: {grid}"
            r = await api(client, "POST", "/tactical-objects", token=op.token,
                          json={"type":        evt["type"],
                                "symbol_code": evt["sidc"],
                                "latitude":    round(clat, 6),
                                "longitude":   round(clon, 6),
                                "notes":       notes,
                                "visibility":  "COMPANY"})
            if r:
                emoji = "⚠️ " if evt["kind"] == "enemy" else "📍"
                log.info("%s %s  marked %-12s  %s  (#%d)",
                         emoji, op.callsign, evt["type"], grid, marker_count)

        # Operator broadcasts contact report with MGRS grid
        if op.token:
            msg_map = {
                "INFANTRY":  f"CONTACT — infantry element, grid {grid}",
                "ARMOR":     f"CONTACT — armour, grid {grid}",
                "ARTILLERY": f"CONTACT — arty position, grid {grid}",
                "SNIPER":    f"CONTACT — sniper fire received, grid {grid}",
                "VEHICLE":   f"CONTACT — vehicle sighted, grid {grid}",
                "UNKNOWN":   f"CONTACT WAIT OUT — unknown element, grid {grid}",
                "POI":       f"INFO — POI located, grid {grid}",
            }
            content = msg_map.get(evt["type"],
                                  f"CONTACT — {evt['type']} grid {grid}")
            await api(client, "POST", "/messages", token=op.token,
                      json={"content": content, "message_type": "BROADCAST"})

# ── CBRN worldwide incident generator ────────────────────────────────────────

# Notable cities used as "near" anchors so the marker isn't always in open ocean.
# Each entry: (name, lat, lon).
_WORLD_ANCHORS: list[tuple[str, float, float]] = [
    ("Brussels",      50.85,   4.35),
    ("London",        51.51,  -0.13),
    ("Paris",         48.86,   2.35),
    ("Berlin",        52.52,  13.40),
    ("Madrid",        40.42,  -3.70),
    ("Rome",          41.90,  12.50),
    ("Warsaw",        52.23,  21.01),
    ("Kyiv",          50.45,  30.52),
    ("Istanbul",      41.01,  28.98),
    ("Cairo",         30.04,  31.24),
    ("Lagos",          6.52,   3.38),
    ("Nairobi",       -1.29,  36.82),
    ("Johannesburg", -26.20,  28.05),
    ("Dubai",         25.20,  55.27),
    ("Tehran",        35.69,  51.39),
    ("Karachi",       24.86,  67.01),
    ("Mumbai",        19.08,  72.88),
    ("New Delhi",     28.61,  77.21),
    ("Bangkok",       13.76, 100.50),
    ("Singapore",      1.35, 103.82),
    ("Jakarta",       -6.21, 106.85),
    ("Manila",        14.60, 120.98),
    ("Tokyo",         35.68, 139.69),
    ("Seoul",         37.57, 126.98),
    ("Beijing",       39.90, 116.41),
    ("Shanghai",      31.23, 121.47),
    ("Sydney",       -33.87, 151.21),
    ("Auckland",     -36.85, 174.76),
    ("Buenos Aires", -34.60, -58.38),
    ("São Paulo",    -23.55, -46.63),
    ("Bogotá",         4.71, -74.07),
    ("Mexico City",   19.43, -99.13),
    ("Los Angeles",   34.05,-118.24),
    ("New York",      40.71, -74.01),
    ("Toronto",       43.65, -79.38),
    ("Reykjavík",     64.13, -21.94),
    ("Anchorage",     61.22,-149.90),
    ("Cape Town",    -33.92,  18.42),
]

_AGENT_CATALOGUE: list[tuple[str, str, str, str]] = [
    # (agent_category, msg_type, agent label, descriptive notes)
    ("C", "CBRN_4", "SARIN (GB)",      "Nerve agent release detected"),
    ("C", "CBRN_4", "VX",              "Persistent nerve agent contamination"),
    ("C", "CBRN_4", "MUSTARD (HD)",    "Vesicant gas — blistering hazard"),
    ("C", "CBRN_4", "CHLORINE",        "Industrial toxic chemical release"),
    ("B", "CBRN_4", "ANTHRAX",         "Suspected biological release — anthrax"),
    ("B", "CBRN_4", "PLAGUE",          "Suspected biological release — plague"),
    ("B", "CBRN_4", "BOTULINUM",       "Suspected biological toxin release"),
    ("R", "CBRN_3", "DIRTY BOMB",      "Radiological dispersal device — gamma rate elevated"),
    ("R", "CBRN_3", "REACTOR LEAK",    "Civilian reactor leak suspected"),
    ("N", "CBRN_2", "TACTICAL NUCLEAR","Suspected sub-kilotonne nuclear detonation"),
    ("N", "CBRN_2", "STRATEGIC YIELD", "Multi-kilotonne nuclear event — confirm yield"),
]


def _random_world_location() -> tuple[float, float, str]:
    """Pick a random anchor city and offset by up to ~50 km in any direction."""
    name, lat, lon = random.choice(_WORLD_ANCHORS)
    dlat = random.uniform(-0.45, 0.45)   # ≈ 50 km N/S
    dlon = random.uniform(-0.45, 0.45) / max(0.2, math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon, name


async def run_cbrn_worldwide(client: httpx.AsyncClient,
                             admin_op: SimOp,
                             speed_mult: float) -> None:
    """Every CBRN_S real seconds emit a CBRN incident at a random worldwide location."""
    real_interval = CBRN_S / speed_mult
    await asyncio.sleep(real_interval * 0.5)
    count = 0

    while True:
        await asyncio.sleep(real_interval)
        if not admin_op.token:
            continue

        lat, lon, near = _random_world_location()
        agent_cat, msg_type, agent_label, notes = random.choice(_AGENT_CATALOGUE)
        wind_dir   = random.randint(0, 359)
        wind_speed = random.randint(5, 45)

        zone_inner = {
            "C": random.randint(500, 1500),
            "B": random.randint(1000, 3000),
            "R": random.randint(800, 2500),
            "N": random.randint(2000, 6000),
        }[agent_cat]
        zone_downwind = zone_inner * random.randint(3, 8)

        payload = {
            "msg_type": msg_type,
            "agent_category": agent_cat,
            "agent": agent_label,
            "latitude":  round(lat, 5),
            "longitude": round(lon, 5),
            "wind_direction":  wind_dir,
            "wind_speed":      wind_speed,
            "zone_inner_m":    zone_inner,
            "zone_downwind_m": zone_downwind,
            "zone_downwind_angle_deg": 30,
            "dtg":     "",
            "serial":  f"WW{count:04d}",
            "near":    near,
            "notes":   notes,
            "lines":   {},
        }
        count += 1

        r = await api(client, "POST", "/reports", token=admin_op.token,
                      json={"type": msg_type, "payload": payload})
        if r:
            log.info("☣️  CBRN %s  %-18s  near %-12s  %.4f,%.4f  wind %d°@%dkm/h  (#%d)",
                     msg_type, agent_label, near, lat, lon, wind_dir, wind_speed, count)


# ── CAS request generator ────────────────────────────────────────────────────

_CAS_AIRCRAFT  = ["F-16C", "F-35A", "A-10C", "AH-64D", "AH-1Z", "EUROFIGHTER", "RAFALE"]
_CAS_ORDNANCE  = ["GBU-12 LGB", "AGM-65 MAVERICK", "20MM CANNON", "HELLFIRE", "ROCKETS", "GBU-39 SDB"]
_CAS_MARK      = ["IR STROBE", "VS-17 PANEL", "SMOKE GREEN", "LASER 1688", "GLINT TAPE"]
_CAS_TARGETS   = [
    "Dug-in infantry platoon",
    "Armoured column halted",
    "Mortar firing position",
    "Technical with HMG",
    "Sniper team in building",
    "Anti-air position",
    "Massed dismounts in tree-line",
]


async def run_cas_requests(client: httpx.AsyncClient,
                           sections: list[SimSection],
                           admin_op: SimOp,
                           speed_mult: float) -> None:
    """Every CAS_S real seconds a forward operator (or admin) requests CAS."""
    real_interval = CAS_S / speed_mult
    await asyncio.sleep(real_interval * 0.7)
    count = 0

    while True:
        await asyncio.sleep(real_interval)

        # Prefer a forward operator with a position; fall back to admin.
        live_ops = [
            o for sec in sections for o in sec.operators
            if o.token and o.lat != 0
        ]
        op = random.choice(live_ops) if live_ops else admin_op
        if not op.token:
            continue

        # Target is 300–1500 m from requester
        spread_m = random.uniform(300, 1500)
        brg_rad  = random.uniform(0, 2 * math.pi)
        if op.lat == 0 and op.lon == 0:
            tlat, tlon, near = _random_world_location()
        else:
            tlat = op.lat + spread_m * math.cos(brg_rad) * LAT_DEG_PER_M
            tlon = op.lon + spread_m * math.sin(brg_rad) * lon_deg_per_m(op.lat)
            near = op.callsign

        grid = mgrs(tlat, tlon)
        target_desc = random.choice(_CAS_TARGETS)
        aircraft    = random.choice(_CAS_AIRCRAFT)
        ordnance    = random.choice(_CAS_ORDNANCE)
        marking     = random.choice(_CAS_MARK)
        friendly_m  = random.choice([200, 300, 400, 500, 600])
        bearing_friendly = random.choice(SPOT_DIRECTIONS)

        # CAS 9-line payload
        payload = {
            "line_1_ip":               f"IP {random.choice(['ALPHA','BRAVO','CHARLIE','DELTA'])}",
            "line_2_heading":          random.randint(0, 359),
            "line_3_distance_m":       random.randint(2000, 8000),
            "line_4_target_elevation": random.randint(5, 500),
            "line_5_target_desc":      target_desc,
            "line_6_target_location": {"latitude": round(tlat, 5),
                                       "longitude": round(tlon, 5),
                                       "mgrs": grid},
            "line_7_marking":          marking,
            "line_8_friendlies":       f"{friendly_m}m {bearing_friendly}",
            "line_9_egress":           random.choice(["NORTH", "SOUTH", "EAST", "WEST"]),
            "aircraft_requested":      aircraft,
            "ordnance_requested":      ordnance,
            "remarks":                 f"Type 2 control. Requesting CAS on {target_desc.lower()}",
            "latitude":  round(tlat, 5),
            "longitude": round(tlon, 5),
            "grid":      grid,
        }

        count += 1
        r = await api(client, "POST", "/reports", token=op.token,
                      json={"type": "CAS", "payload": payload})
        if r:
            log.info("✈️  %s  CAS REQ  %-26s  %s  %s/%s  (#%d)",
                     op.callsign, target_desc[:26], grid, aircraft, ordnance, count)


# ── Operation Dendermonde — tactical control graphics ───────────────────────
#
# One-shot setup that overlays the moving simulation with the doctrinal
# graphics for a Coy attack: company OBJ, FLOT/FLET, phase lines, boundaries,
# a hierarchy of attack axes (PL → SEC → TM), reserve in defence with a
# pre-planned counter-attack, and the usual obstacle / withdraw graphics.
#
# Coordinates align with the ROUTES dictionary above so the graphics tell
# the same story as the moving operators.

# Centre of OBJ EAGLE — the company objective enveloping the three platoon
# objectives (Bogaerdpark / Scheldebrug / NE industrial).
_OP_CENTER = (51.0355, 4.1015)

# Spans of the play area, derived from ROUTES above.
_LD_LAT     = 51.0188   # line of departure (staging line, south)
_AP_LAT     = 51.0335   # assault position (just south of objectives)
_FLET_LAT   = 51.0382   # estimated forward line of enemy troops
_WEST_LON   = 4.0870
_CENTRE_LON = 4.1015
_EAST_LON   = 4.1140
_BOUND_W    = 4.0945    # boundary west:  between BRAVO and ALPHA
_BOUND_E    = 4.1080    # boundary east:  between ALPHA and CHARLIE


def _pl_axis(plt: str) -> tuple[float, float, float]:
    """Return (lat, lon, heading-deg) for the given platoon's attack-axis
    centred between LD and Assault Position. Heading is roughly toward the
    platoon objective from that point."""
    if plt == "BRAVO":
        return (51.0265, 4.0930, 10)         # north-north-east
    if plt == "CHARLIE":
        return (51.0265, 4.1140, 350)        # almost due north
    return (51.0265, 4.1010, 0)              # ALPHA — due north


def _operation_graphics() -> list[dict]:
    """Return the full list of TacticalObjectIn payloads for OPERATION DENDERMONDE."""
    out: list[dict] = []

    # ── COY objective area (envelops all three platoon objectives) ──────
    poly_obj = [
        (51.0345, 4.0980), (51.0395, 4.0985),
        (51.0395, 4.1115), (51.0345, 4.1115),
    ]
    out.append({
        "type": "OBJ_AREA",
        "latitude":  poly_obj[0][0], "longitude": poly_obj[0][1],
        "echelon": "COY",
        "notes":   "OBJ EAGLE — Delta Coy company objective",
        "geometry": json.dumps({"type": "polygon",
                                "coords": [list(p) for p in poly_obj]}),
    })

    # ── FLOT — own forward line, aligned with the LD ──
    flot = [(_LD_LAT, _WEST_LON - 0.005), (_LD_LAT, _CENTRE_LON),
            (_LD_LAT, _EAST_LON + 0.005)]
    out.append({
        "type": "FLOT", "echelon": "COY",
        "latitude": flot[0][0], "longitude": flot[0][1],
        "notes":  "FLOT — DELTA Coy",
        "geometry": json.dumps({"type": "line",
                                "coords": [list(p) for p in flot]}),
    })

    # ── FLET — estimated enemy forward line ──
    flet = [(_FLET_LAT, _WEST_LON - 0.005),
            (_FLET_LAT - 0.001, _CENTRE_LON),
            (_FLET_LAT, _EAST_LON + 0.005)]
    out.append({
        "type": "FLET",
        "latitude": flet[0][0], "longitude": flet[0][1],
        "notes":  "Estimated FLET — coy(+) defending OBJ",
        "geometry": json.dumps({"type": "line",
                                "coords": [list(p) for p in flet]}),
    })

    # ── Phase lines: ALPHA (LD) and BRAVO (Assault Position) ──
    pl_alpha = [(_LD_LAT, _WEST_LON - 0.005), (_LD_LAT, _EAST_LON + 0.005)]
    pl_bravo = [(_AP_LAT, _WEST_LON - 0.005), (_AP_LAT, _EAST_LON + 0.005)]
    out.append({
        "type": "PHASE_LINE",
        "latitude": pl_alpha[0][0], "longitude": pl_alpha[0][1],
        "notes":  "PL ALPHA — Line of Departure (H-hour)",
        "geometry": json.dumps({"type": "line",
                                "coords": [list(p) for p in pl_alpha]}),
    })
    out.append({
        "type": "PHASE_LINE",
        "latitude": pl_bravo[0][0], "longitude": pl_bravo[0][1],
        "notes":  "PL BRAVO — Assault Position",
        "geometry": json.dumps({"type": "line",
                                "coords": [list(p) for p in pl_bravo]}),
    })

    # ── Boundaries between platoons ──
    for lon, label in ((_BOUND_W, "BRAVO // ALPHA"),
                       (_BOUND_E, "ALPHA // CHARLIE")):
        out.append({
            "type": "BOUNDARY", "echelon": "PL",
            "latitude": _LD_LAT, "longitude": lon,
            "notes":  f"Inter-platoon boundary  {label}",
            "geometry": json.dumps({"type": "line",
                                    "coords": [[_LD_LAT, lon], [_FLET_LAT, lon]]}),
        })

    # ── Attack axes — PL → SEC → TM ──
    for plt in ("ALPHA", "BRAVO", "CHARLIE"):
        plat, plon, head = _pl_axis(plt)
        out.append({
            "type": "ATK_AXIS", "echelon": "PL", "rotation": head,
            "latitude": plat, "longitude": plon,
            "notes": f"{plt} PL — attack axis",
        })
        # Two sections — small lateral spread, slightly forward
        for sec_num, dlon in ((1, -0.0015), (2, +0.0015)):
            out.append({
                "type": "ATK_AXIS", "echelon": "SEC",
                "rotation": head,
                "latitude":  plat + 0.0015,
                "longitude": plon + dlon,
                "notes": f"{plt}-{sec_num} SEC",
            })
        # Lead TM of the lead section
        out.append({
            "type": "ATK_AXIS", "echelon": "TM",
            "rotation": head,
            "latitude":  plat + 0.0030,
            "longitude": plon - 0.0010,
            "notes": f"{plt}-1-1 TM lead",
        })

    # ── Reserve PL in defence at LD, CATK on order ──
    out.append({
        "type": "DEF_AREA", "echelon": "PL", "rotation": 0,
        "latitude": _LD_LAT - 0.001, "longitude": _CENTRE_LON,
        "notes":  "Reserve PL — hasty defence at LD",
    })
    out.append({
        "type": "COUNTERATTACK", "echelon": "PL", "rotation": 45,
        "latitude": _LD_LAT + 0.0010, "longitude": _CENTRE_LON - 0.0030,
        "notes":  "ON-ORDER CATK — reserve into west flank",
    })

    # ── Suspected enemy ambush + bypass + block + withdraw ──
    out.append({
        "type": "AMBUSH", "echelon": "SEC", "rotation": 200,
        "latitude": 51.0310, "longitude": 4.1010,
        "notes":  "EN AMBUSH — suspected RPG team at chokepoint",
    })
    out.append({
        "type": "BYPASS", "echelon": "PL", "rotation": 90,
        "latitude": 51.0315, "longitude": 4.1040,
        "notes":  "Bypass east of suspected ambush — ALPHA alt route",
    })
    out.append({
        "type": "BLOCK", "echelon": "COY", "rotation": 90,
        "latitude": _OP_CENTER[0], "longitude": _EAST_LON + 0.0030,
        "notes":  "Block east — interdict EN reinforcement axis",
    })
    out.append({
        "type": "WITHDRAW", "echelon": "COY", "rotation": 180,
        "latitude": _OP_CENTER[0], "longitude": _CENTRE_LON,
        "notes":  "Withdraw route — south through PL ALPHA, RV at FLOT centre",
    })

    return out


# Enemy contacts pre-planted on/around OBJ — gives the moving sim something
# to advance against from the very first frame.
_OP_ENEMY_PLANT: list[dict] = [
    dict(type="INFANTRY",  sidc="SHGPUCI-----",
         lat=51.0370, lon=4.0995, notes="EN platoon — defending Scheldebrug"),
    dict(type="INFANTRY",  sidc="SHGPUCI-----",
         lat=51.0372, lon=4.1015, notes="EN platoon — Bogaerdpark north edge"),
    dict(type="INFANTRY",  sidc="SHGPUCI-----",
         lat=51.0375, lon=4.1075, notes="EN section — NE industrial"),
    dict(type="ARMOR",     sidc="SHGPUCA-----",
         lat=51.0388, lon=4.1015, notes="EN T-72 in hull-down position"),
    dict(type="ARTILLERY", sidc="SHGPUCF-----",
         lat=51.0410, lon=4.1010, notes="EN 120 mm mortar baseplate, est."),
    dict(type="AIR_DEFENSE", sidc="SHGPUCD-----",
         lat=51.0395, lon=4.1100, notes="EN MANPADS / ZU-23 covering NE"),
    dict(type="SNIPER",    sidc="SHGPUCIS----",
         lat=51.0365, lon=4.1035, notes="EN sniper team — church tower"),
    dict(type="VEHICLE",   sidc="SHGPEV------",
         lat=51.0380, lon=4.0985, notes="Technical w/ HMG — west bank"),
    dict(type="UNKNOWN",   sidc="SUGPU-------",
         lat=51.0405, lon=4.0980, notes="Unknown contact — recce reports"),
    dict(type="POI",       sidc="SNGPI-------",
         lat=51.0260, lon=4.1015, notes="POI — fuel station, RV for resupply"),
]


# ── Friendly battalion laydown ─────────────────────────────────────────────
#
# Plants a full battalion's worth of friendly unit markers (SEC / PL / COY /
# BN echelons across the usual combat and combat-support branches) as plain
# tactical objects on the map. These are NOT operators and NOT part of the
# command hierarchy — they are doctrinal force-laydown symbols only, so the
# map shows where the BN's sub-units sit on the ground.
#
# Each entry carries a MIL-STD-2525C friendly SIDC with the echelon modifier
# at position 11 (A=team, C=section, D=platoon, E=company, F=battalion). The
# map clients (web milsymbol.js and android MilsymRenderer) render the cyan
# affiliation rectangle, function-modifier glyph and echelon bars from the
# SIDC alone.

# Battalion rear area — Brugge (Bruges), Belgium. Garrison / depot location
# from which the BN deploys forward; markers fan out around the city centre.
_FBN_BASE_LAT = 51.2093
_FBN_BASE_LON = 3.2247

# (label,                   SIDC,            d-lat,   d-lon,  notes)
# Latitude offsets are negative south, longitude offsets east-west around base.
_FRIENDLY_BN_LAYDOWN: list[tuple[str, str, float, float, str]] = [
    # ── 1× BN HQ (centre, rear area) ─────────────────────────────────────
    ("1-12 IN BN HQ",        "SFGPUCI----F",  0.0000,   0.0000,
     "Battalion Tactical Operations Centre (TOC)"),
    ("1-12 IN BN MAIN CP",   "SFGPUCI--H-F", -0.0050,   0.0030,
     "Battalion Main Command Post (HQ modifier)"),

    # ── 4× rifle companies (A/B/C/D) — fan north toward the line ─────────
    ("A CO HQ",              "SFGPUCI--H-E",  0.0250,  -0.0450,
     "A Company command post — supports OBJ HAWK (Bastogne)"),
    ("B CO HQ",              "SFGPUCI--H-E",  0.0250,  -0.0150,
     "B Company command post — supports OBJ EAGLE (Houffalize)"),
    ("C CO HQ",              "SFGPUCI--H-E",  0.0250,   0.0150,
     "C Company command post — supports OBJ FALCON (La Roche)"),
    ("D CO HQ",              "SFGPUCI--H-E",  0.0250,   0.0450,
     "D Company command post — supports OBJ KITE (Vielsalm)"),

    # ── Combat-support companies (HHC + Weapons CO) ──────────────────────
    ("HHC",                  "SFGPUCI--H-E", -0.0080,  -0.0250,
     "Headquarters & Headquarters Company"),
    ("WPNS CO",              "SFGPUCFH--HE", -0.0080,   0.0250,
     "Weapons / Heavy Mortar Company"),

    # ── 12× rifle platoons (3 per CO) ────────────────────────────────────
    # A CO platoons
    ("A/1 PL",               "SFGPUCI----D",  0.0420,  -0.0520,
     "A Coy / 1 Pl rifle platoon"),
    ("A/2 PL",               "SFGPUCI----D",  0.0420,  -0.0450,
     "A Coy / 2 Pl rifle platoon"),
    ("A/3 PL",               "SFGPUCIZ---D",  0.0420,  -0.0380,
     "A Coy / 3 Pl mech-infantry platoon"),
    # B CO platoons
    ("B/1 PL",               "SFGPUCI----D",  0.0420,  -0.0220,
     "B Coy / 1 Pl rifle platoon"),
    ("B/2 PL",               "SFGPUCI----D",  0.0420,  -0.0150,
     "B Coy / 2 Pl rifle platoon"),
    ("B/3 PL",               "SFGPUCIZ---D",  0.0420,  -0.0080,
     "B Coy / 3 Pl mech-infantry platoon"),
    # C CO platoons
    ("C/1 PL",               "SFGPUCI----D",  0.0420,   0.0080,
     "C Coy / 1 Pl rifle platoon"),
    ("C/2 PL",               "SFGPUCI----D",  0.0420,   0.0150,
     "C Coy / 2 Pl rifle platoon"),
    ("C/3 PL",               "SFGPUCIZ---D",  0.0420,   0.0220,
     "C Coy / 3 Pl mech-infantry platoon"),
    # D CO platoons
    ("D/1 PL",               "SFGPUCI----D",  0.0420,   0.0380,
     "D Coy / 1 Pl rifle platoon"),
    ("D/2 PL",               "SFGPUCI----D",  0.0420,   0.0450,
     "D Coy / 2 Pl rifle platoon"),
    ("D/3 PL",               "SFGPUCIZ---D",  0.0420,   0.0520,
     "D Coy / 3 Pl mech-infantry platoon"),

    # ── Selected SEC markers under lead platoons (A/1 and D/1) ───────────
    ("A/1/1 SEC",            "SFGPUCI----C",  0.0480,  -0.0540,
     "A Coy / 1 Pl / 1 Sec rifle section"),
    ("A/1/2 SEC",            "SFGPUCI----C",  0.0480,  -0.0500,
     "A Coy / 1 Pl / 2 Sec rifle section"),
    ("D/1/1 SEC",            "SFGPUCI----C",  0.0480,   0.0360,
     "D Coy / 1 Pl / 1 Sec rifle section"),
    ("D/1/2 SEC",            "SFGPUCI----C",  0.0480,   0.0400,
     "D Coy / 1 Pl / 2 Sec rifle section"),

    # ── Battalion combat-support platoons ────────────────────────────────
    ("RECCE PL",             "SFGPUCRR---D",  0.0150,   0.0000,
     "Battalion reconnaissance platoon — screen forward of FLOT"),
    ("AT PL (TOW)",          "SFGPUCAA---D",  0.0080,  -0.0080,
     "Battalion anti-armour platoon (TOW)"),
    ("MOR PL",               "SFGPUCF----D",  0.0070,   0.0080,
     "Battalion mortar platoon (81 mm)"),
    ("AD PL (STINGER)",      "SFGPUCD----D",  0.0050,   0.0150,
     "Battalion air-defence platoon (Stinger)"),
    ("ENG PL",               "SFGPUCEN---D",  0.0030,  -0.0150,
     "Combat engineer platoon — breach / mobility"),
    ("SIG SEC",              "SFGPUCS----C", -0.0030,  -0.0080,
     "Signal section — BN HQ communications"),

    # ── Battalion combat-service-support ─────────────────────────────────
    ("MED PL",               "SFGPUSM----D", -0.0080,   0.0080,
     "Medical platoon — BAS (Battalion Aid Station)"),
    ("SUP CO",               "SFGPUSS----E", -0.0150,   0.0150,
     "Supply company — combat trains"),
    ("MAINT SEC",            "SFGPUSM----C", -0.0150,  -0.0150,   # noqa: dup-key
     "Maintenance section — recovery & repair"),
]


def _friendly_battalion_objects() -> list[dict]:
    """Build TacticalObjectIn payloads for the friendly BN laydown."""
    out: list[dict] = []
    for label, sidc, dlat, dlon, notes in _FRIENDLY_BN_LAYDOWN:
        out.append({
            "type":        "FRIENDLY",
            "symbol_code": sidc,
            "affiliation": "FRIENDLY",
            "latitude":    _FBN_BASE_LAT + dlat,
            "longitude":   _FBN_BASE_LON + dlon,
            "notes":       f"{label} — {notes}",
        })
    return out


async def plant_friendly_battalion(client: httpx.AsyncClient, admin_op: SimOp) -> None:
    """Plant a full friendly battalion as map markers — not operators."""
    if not admin_op.token:
        log.warning("Cannot plant friendly battalion — admin not logged in")
        return
    items = _friendly_battalion_objects()
    log.info("── Planting friendly BN laydown — %d unit markers "
             "(SEC/PL/COY/BN) ─────", len(items))
    n_ok = 0
    for item in items:
        r = await api(client, "POST", "/tactical-objects",
                      token=admin_op.token, json=item)
        if r:
            n_ok += 1
    log.info("── Friendly BN laydown planted: %d / %d ─────", n_ok, len(items))


async def plant_operation(client: httpx.AsyncClient, admin_op: SimOp) -> None:
    """One-shot: plant Operation IRON ARDENNES — four company plans, all
    tactical graphics, OPFOR defenders at each village, friendly POIs."""
    if not admin_op.token:
        log.warning("Cannot plant operation graphics — admin not logged in")
        return

    # Import the canonical builder used by simulate_battlefield.py so the
    # graphics and enemy laydown stay in sync between the two simulators.
    from simulate_battlefield import PLANS as ARDENNES_PLANS, build_company_plan

    all_items: list[dict] = []
    for coy, obj_name, village, centre, bearing in ARDENNES_PLANS:
        all_items.extend(build_company_plan(coy, obj_name, village, centre, bearing))

    log.info("── Planting Operation IRON ARDENNES — %d objects across %d "
             "company plans ─────", len(all_items), len(ARDENNES_PLANS))

    n_ok = 0
    for item in all_items:
        r = await api(client, "POST", "/tactical-objects",
                      token=admin_op.token, json=item)
        if r:
            n_ok += 1
            aff = item.get("affiliation", "FRIENDLY")
            tag = item.get("echelon") or "—"
            icon = "⚠️ " if aff == "ENEMY" else "📐"
            label = (item.get("notes") or item["type"]).split("\n", 1)[0][:60]
            log.info("  %s %-13s %-8s %-4s  %s",
                     icon, item["type"], aff, tag, label)

    log.info("── Operation laydown: %d / %d objects planted ─────────",
             n_ok, len(all_items))


# ── OPFOR — moving enemy units defending each Ardennes village ──────────────
#
# Spawns N enemy tactical-object markers per village at startup and jitters
# their position every OPFOR_S real seconds so the friendly map shows live
# threat movement around each OBJ.

OPFOR_S = 25.0                          # real seconds between OPFOR moves
OPFOR_RADIUS_M = 350.0                  # jitter radius around village centre
OPFOR_PER_VILLAGE = 6                   # number of OPFOR units per OBJ

_OPFOR_TYPES = [
    ("INFANTRY",    "SHGPUCIZ----", "Mech inf section"),
    ("ARMOR",       "SHGPUCAA----", "T-72 element"),
    ("AT/ATGM",     "SHGPUCAA---F", "ATGM team"),
    ("ARTILLERY",   "SHGPUCFHE---", "120 mm mortar"),
    ("AIR_DEFENSE", "SHGPUCDS----", "MANPADS team"),
    ("VEHICLE",     "SHGPEVAT----", "Technical w/ HMG"),
]


async def plant_opords(client: httpx.AsyncClient, admin_op: SimOp) -> None:
    """One OPORD per company plan, fully filled doctrinally and PUBLISHED.

    Idempotent: existing OPORDs with the same OPORD number are skipped.
    """
    if not admin_op.token:
        return
    from simulate_battlefield import PLANS as ARDENNES_PLANS

    # Fetch any pre-existing OPORDs so we don't double-plant on rerun.
    existing = await api(client, "GET", "/opord", token=admin_op.token) or []
    seen = {o.get("opord_number") for o in existing if isinstance(o, dict)}

    n_created = 0
    for idx, (coy, obj_name, village, centre, bearing) in enumerate(ARDENNES_PLANS, start=1):
        opord_no = f"OPORD 26-{100 + idx:03d}"
        if opord_no in seen:
            log.info("OPORD %s — already present, skipping.", opord_no)
            continue
        bearing_from = int(bearing) % 360
        atk_heading  = (bearing_from + 180) % 360
        body = {
            "title": f"{coy} Attack to Seize OBJ {obj_name}",
            "opord_number":   opord_no,
            "dtg":            f"11{500 + idx * 30:04d}ZMAY26",
            "time_zone":      "ZULU",
            "classification": "UNCLASSIFIED//FOUO",
            "references": (
                f"a. Map Series M745, Sheet covering {village}, 1:50,000\n"
                "b. BDE OPORD 26-04 (Operation IRON ARDENNES)\n"
                "c. Co/Tm Offensive SOP"
            ),
            "task_organization": (
                f"1 PL (ME) — 3 rifle squads, 1 WPN sqd (2x M240B)\n"
                "2 PL (SE) — 3 rifle squads\n"
                "3 PL (RES) — 3 rifle squads\n"
                "ATT: ENG TM, FO TM, MED TM, AT SEC (2x Javelin)"
            ),
            "situation": {
                "terrain": (
                    f"OAKOC. Ardennes — wooded ridges, restricted MSRs through {village}. "
                    "Key terrain: village centre and approaches from N4/N89."
                ),
                "weather": (
                    "BMNT 0518 / Sunrise 0552 / Sunset 1928 / EENT 1954. Temp 6–14°C, "
                    "scattered showers, vis >5 km. Fog risk in low ground before BMNT."
                ),
                "enemy_cds":  f"Reinforced mech inf coy IVO {village}; T-72 plt, ATGM, mortar baseplate, MANPADS.",
                "enemy_mlcoa": (
                    f"Defend {village} from prepared positions; mortar fires onto AAs; "
                    f"CT effort from {atk_heading}° at H+30."
                ),
                "enemy_mdcoa": "Pre-emptive spoiling attack with armour pair; FASCAM on Route GREEN.",
                "higher": (
                    f"{coy} attacks to seize OBJ {obj_name} NLT H+45 IOT enable BN passage of lines."
                ),
                "adjacent": "Left/right: adjacent companies on neighbouring axes; BN reserve at AA OSCAR.",
                "civil": f"ASCOPE — {village} ~1000 civilians; coordinate via CIMIC. NFA on church/mosque.",
                "attachments": "ENG TM, FO TM, MED TM, AT SEC — effective H-12.",
                "assumptions": "EN composition unchanged at H-Hour; CAS pair on 30-min strip alert.",
            },
            "mission": (
                f"{coy} attacks at H-Hour to seize OBJ {obj_name} (vic {village}) IOT enable "
                "BN continuation of attack along the Ardennes axis."
            ),
            "execution": {
                "intent_purpose":    f"Defeat EN at {village} so BN can pass N.",
                "intent_key_tasks":  "Isolate OBJ · Suppress EN AT · Seize OBJ · BPT defend.",
                "intent_end_state":  f"OBJ {obj_name} secured; EN destroyed/captured; civilians unharmed.",
                "conops_maneuver":   (
                    f"Envelopment from bearing {atk_heading}°. PHASE I PREP, II ASSAULT, III "
                    "CONSOLIDATION. 1 PL ME, 2 PL SE, 3 PL RES."
                ),
                "conops_fires":      "Priority: ME. FPF on TRP-1. CAS on call (THUNDER 21). Smoke at H-2 min.",
                "conops_main_effort": "1 PL assault.",
                "conops_phasing":    "PREP → ASSAULT → CONSOLIDATION (LACE).",
                "tasks": (
                    "1 PL (ME): O/O assault OBJ — destroy EN, gain foothold.\n"
                    "2 PL (SE): SBF on dominant terrain; suppress EN AT.\n"
                    "3 PL (RES): BPT reinforce ME / block N approach / counter-CT.\n"
                    "ENG TM: breach obstacle belt fwd of OBJ.\n"
                    "FO TM: with 1 PL HQ — execute fires plan."
                ),
                "coord_timings":  "H-12 rehearsals; H-3 SP; H-2 SBF set; H-Hour assault; H+45 consolidation.",
                "coord_ccir":     "PIR: EN reinforce axis & timing. FFIR: ME <70%, CIV cas event.",
                "coord_roe":      "ROE Annex E. PID required. NFA on church/mosque/school.",
                "coord_risk":     "HIGH (fratricide on flanks). Controls: PL BLUE LOA; VS-17 orange-up; rehearse recognition.",
                "coord_fscm":     "FSCL PL BLUE; RFL 100m N of OBJ; CFL on order.",
            },
            "sustainment": {
                "supply":      "I 2xMRE/24h; III topped at AA; V basic+50%; VIII medic resupplied H-6.",
                "transport":   "Organic veh; 1x M113 dedicated CASEVAC.",
                "maintenance": "UMCP at AA; recovery TARGET-1 in trail.",
                "personnel":   "Strength reports H-1 and H+1.",
                "epw":         "5 S's & T; tag EPW-1; hold at CCP until BN MP.",
                "casevac":     "CCP at AA; 9-Line on CMD net; PRI ground via M113.",
                "medevac":     "ROLE 1 BAS at AA; ROLE 2 BN MED CO; DUSTOFF 36 30-min alert.",
            },
            "command_signal": {
                "command":      f"CDR with ME during PHASE II. XO at TAC CP at AA.",
                "succession":   "CDR → XO → 1 PL LDR → 2 PL LDR → 3 PL LDR.",
                "control":      "SITREP every 30 min; immediate report on contact.",
                "pace_primary":    "VHF SINCGARS — CMD 38.250 / FH-M",
                "pace_alternate":  "HF 4.825",
                "pace_contingency":"SATCOM TACSAT CH 102",
                "pace_emergency":  "Pyro: green star = consolidate; red = withdraw.",
                "callsigns":   f"BLACK 6 (CDR), RED (1 PL ME), WHITE (2 PL SE), BLUE (3 PL RES), GUNNER 6 (FO).",
                "password":    "Challenge: THUNDER / Reply: STORM / Running: HAMMER",
            },
        }
        r = await api(client, "POST", "/opord", token=admin_op.token, json=body)
        if not (r and isinstance(r, dict) and "id" in r):
            log.warning("OPORD plant failed for %s", opord_no)
            continue
        opord_id = r["id"]
        # Attach a server-rendered map snapshot covering the AO.
        bbox = [centre.lat - 0.025, centre.lon - 0.035,
                centre.lat + 0.025, centre.lon + 0.035]
        await api(client, "POST", f"/opord/{opord_id}/snapshots/render",
                  token=admin_op.token,
                  json={"label": f"OBJ {obj_name} AO",
                        "bbox": bbox, "zoom": 13,
                        "annotations": f"{coy} attack axis on {village}."})
        # Publish so it appears on the OPORDs page as PUBLISHED.
        await api(client, "POST", f"/opord/{opord_id}/publish", token=admin_op.token)
        log.info("📋 OPORD #%-3d %s — %s · OBJ %s · %s",
                 opord_id, opord_no, coy, obj_name, village)
        n_created += 1

    log.info("── OPORDs planted: %d new (%d total).", n_created, n_created + len(seen))


async def spawn_opfor(client: httpx.AsyncClient, admin_op: SimOp) -> list[dict]:
    """Create OPFOR units at each village; return their server records."""
    from simulate_battlefield import PLANS as ARDENNES_PLANS
    if not admin_op.token:
        return []

    spawned: list[dict] = []
    for _coy, _obj, village, centre, _bearing in ARDENNES_PLANS:
        for i in range(OPFOR_PER_VILLAGE):
            kind, sidc, name = _OPFOR_TYPES[i % len(_OPFOR_TYPES)]
            ang = random.uniform(0, 2 * math.pi)
            r   = random.uniform(50, OPFOR_RADIUS_M)
            d_n = r * math.cos(ang); d_e = r * math.sin(ang)
            lat, lon = jitter(centre.lat, centre.lon, d_n, d_e)
            payload = {
                "type": "ENEMY", "symbol_code": sidc,
                "latitude": round(lat, 6), "longitude": round(lon, 6),
                "affiliation": "ENEMY", "echelon": "SEC",
                "notes": f"OPFOR {name} defending {village}",
                "visibility": "COMPANY", "rotation": 0.0, "geometry": "",
            }
            r2 = await api(client, "POST", "/tactical-objects",
                           token=admin_op.token, json=payload)
            if r2 and isinstance(r2, dict) and "id" in r2:
                spawned.append({"id": r2["id"], "centre": centre,
                                "lat": lat, "lon": lon, "village": village,
                                "kind": kind, "name": name, "sidc": sidc})
    log.info("OPFOR: spawned %d units across %d villages.",
             len(spawned), len(ARDENNES_PLANS))
    return spawned


async def run_opfor_movement(client: httpx.AsyncClient, admin_op: SimOp,
                             units: list[dict], speed_mult: float) -> None:
    """Re-post each OPFOR unit with a jittered position every OPFOR_S seconds.

    We delete + re-create the object (the API has no PATCH endpoint for
    tactical objects); the new id replaces the old one in our state list.
    """
    real_interval = OPFOR_S / speed_mult
    await asyncio.sleep(real_interval * 0.4)
    while True:
        for u in units:
            ang = random.uniform(0, 2 * math.pi)
            step_m = random.uniform(20, 80)
            d_n = step_m * math.cos(ang); d_e = step_m * math.sin(ang)
            new_lat, new_lon = jitter(u["lat"], u["lon"], d_n, d_e)
            # Constrain to within OPFOR_RADIUS_M of the village centre.
            if dist_m(u["centre"].lat, u["centre"].lon, new_lat, new_lon) > OPFOR_RADIUS_M:
                continue
            # Delete the old marker; re-create at the new spot.
            await api(client, "DELETE", f"/tactical-objects/{u['id']}",
                      token=admin_op.token)
            payload = {
                "type": "ENEMY", "symbol_code": u["sidc"],
                "latitude": round(new_lat, 6), "longitude": round(new_lon, 6),
                "affiliation": "ENEMY", "echelon": "SEC",
                "notes": f"OPFOR {u['name']} defending {u['village']}",
                "visibility": "COMPANY", "rotation": 0.0, "geometry": "",
            }
            r = await api(client, "POST", "/tactical-objects",
                          token=admin_op.token, json=payload)
            if r and isinstance(r, dict) and "id" in r:
                u["id"]  = r["id"]
                u["lat"] = new_lat
                u["lon"] = new_lon
        await asyncio.sleep(real_interval)


# ── Netherlands CBRN attacks ─────────────────────────────────────────────────
#
# Wider-conflict backdrop: a separate CBRN feed centred on Dutch population
# centres, distinct from the worldwide jitter generator. Tighter cadence and
# heavier agent mix — these are the events the Coy will actually plan around.

_NL_ANCHORS: list[tuple[str, float, float]] = [
    ("Amsterdam",   52.370, 4.895),
    ("Rotterdam",   51.924, 4.477),
    ("Den Haag",    52.080, 4.310),
    ("Utrecht",     52.090, 5.121),
    ("Eindhoven",   51.441, 5.469),
    ("Tilburg",     51.560, 5.090),
    ("Groningen",   53.219, 6.567),
    ("Maastricht",  50.851, 5.687),
    ("Breda",       51.586, 4.776),
    ("Arnhem",      51.985, 5.910),
    ("Nijmegen",    51.812, 5.837),
    ("Den Helder",  52.960, 4.760),
    ("Vlissingen",  51.444, 3.573),
    ("Schiphol",    52.309, 4.764),
    ("Borssele",    51.432, 3.717),   # nuclear plant
]

_NL_AGENT_CATALOGUE = [
    ("C", "CBRN_4", "SARIN (GB)",       "Nerve agent release in city centre — mass casualty event"),
    ("C", "CBRN_4", "VX",               "Persistent nerve agent — port area contamination"),
    ("C", "CBRN_4", "CHLORINE",         "Industrial chlorine release — petrochemical complex"),
    ("C", "CBRN_4", "MUSTARD (HD)",     "Mustard gas — vesicant casualties reported"),
    ("B", "CBRN_4", "ANTHRAX",          "Suspected anthrax aerosol — public transport hub"),
    ("B", "CBRN_4", "BOTULINUM",        "Botulinum toxin — water supply suspected"),
    ("R", "CBRN_3", "DIRTY BOMB",       "Radiological dispersal device detonated"),
    ("R", "CBRN_3", "REACTOR LEAK",     "Nuclear reactor coolant leak — civilian site"),
    ("N", "CBRN_2", "TACTICAL NUCLEAR", "Sub-kilotonne nuclear detonation"),
]


async def run_cbrn_netherlands(client: httpx.AsyncClient,
                               admin_op: SimOp,
                               speed_mult: float) -> None:
    """Higher-cadence CBRN incidents in NL cities — wider conflict backdrop."""
    real_interval = (CBRN_S * 0.6) / speed_mult     # ~60 % of worldwide rate
    await asyncio.sleep(real_interval * 0.2)
    count = 0

    while True:
        await asyncio.sleep(real_interval)
        if not admin_op.token:
            continue

        name, lat, lon = random.choice(_NL_ANCHORS)
        # Tighter offset than worldwide (city-scale, not regional)
        dlat = random.uniform(-0.045, 0.045)        # ≈ 5 km N/S
        dlon = random.uniform(-0.045, 0.045) / max(0.2, math.cos(math.radians(lat)))
        elat, elon = lat + dlat, lon + dlon

        agent_cat, msg_type, agent_label, notes = random.choice(_NL_AGENT_CATALOGUE)
        wind_dir   = random.randint(0, 359)
        wind_speed = random.randint(8, 35)

        zone_inner = {
            "C": random.randint(800, 2000),
            "B": random.randint(1500, 3500),
            "R": random.randint(1200, 3000),
            "N": random.randint(3000, 7000),
        }[agent_cat]
        zone_downwind = zone_inner * random.randint(4, 9)

        payload = {
            "msg_type": msg_type,
            "agent_category": agent_cat,
            "agent": agent_label,
            "latitude":  round(elat, 5),
            "longitude": round(elon, 5),
            "wind_direction":  wind_dir,
            "wind_speed":      wind_speed,
            "zone_inner_m":    zone_inner,
            "zone_downwind_m": zone_downwind,
            "zone_downwind_angle_deg": 30,
            "dtg":     "",
            "serial":  f"NL{count:04d}",
            "near":    name,
            "notes":   notes,
            "lines":   {},
        }
        count += 1

        r = await api(client, "POST", "/reports", token=admin_op.token,
                      json={"type": msg_type, "payload": payload})
        if r:
            log.info("🇳🇱☣️  CBRN %s  %-18s  near %-12s  %.4f,%.4f  wind %d°@%dkm/h  (#%d)",
                     msg_type, agent_label, name, elat, elon,
                     wind_dir, wind_speed, count)


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
    log.info("Backend : %s", _CTX.base)
    log.info("Operators: %d  |  Sections: %d  |  Speed: %.1f×",
             len(all_ops), len(sections), speed_mult)
    log.info("Walk %.1f km/h  Infil %.1f km/h  Update every %gs  Enemy every %gs  "
             "CBRN every %gs  CAS every %gs",
             WALK_MS * 3.6, INFIL_MS * 3.6,
             UPDATE_S / speed_mult, ENEMY_S / speed_mult,
             CBRN_S / speed_mult, CAS_S / speed_mult)

    async with httpx.AsyncClient(verify=False) as client:

        if ARGS.reset:
            await reset_sim(client, all_ops)

        admin_token = await bootstrap(client, all_ops, sections)
        _CTX.mission_id = await sim_utils.create_mission_async(
            client, _CTX.base, admin_token, ARGS.mission_name,
            map_center_lat=50.08, map_center_lng=5.73, map_zoom=12)
        await login_all(client, all_ops)

        # Plant the doctrinal operation graphics + enemy laydown — once.
        admin_op = next(o for o in all_ops if o.role == "ADMIN")
        await plant_operation(client, admin_op)

        # Plant a friendly battalion-strength laydown (SEC/PL/COY/BN markers
        # as plain tactical objects — NOT operators, NOT hierarchy).
        await plant_friendly_battalion(client, admin_op)

        # Plant one full OPORD per company plan (idempotent).
        await plant_opords(client, admin_op)

        # Spawn OPFOR defenders at each Ardennes village and let them shuffle.
        opfor_units = await spawn_opfor(client, admin_op)

        # Gather all coroutines
        coros = []
        if opfor_units:
            coros.append(run_opfor_movement(client, admin_op, opfor_units, speed_mult))

        # Section movement — section 2 of each platoon staggers by SECTION_STAGGER_S
        for sec in sections:
            stagger = 0.0 if sec.section_num == 1 else SECTION_STAGGER_S
            coros.append(run_section(client, sec, speed_mult, stagger))

        # Command element
        coros.append(run_command(client, all_ops, speed_mult))

        # Enemy / report marker
        coros.append(run_enemy_marker(client, sections, speed_mult))

        # Worldwide CBRN incidents + random CAS requests + NL-focused CBRN
        coros.append(run_cbrn_worldwide(client, admin_op, speed_mult))
        coros.append(run_cbrn_netherlands(client, admin_op, speed_mult))
        coros.append(run_cas_requests(client, sections, admin_op, speed_mult))

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
