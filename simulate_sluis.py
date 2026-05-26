#!/usr/bin/env python3
"""
Arrow Tactical Simulator — Operation Sluis
============================================
Delta Company assaults the town of Sluis (Zeeuws-Vlaanderen, NL) from staging
areas across the Belgian border. The scenario drives:

  * 3-platoon, 6-section advance to contact along three axes
  * Enemy contacts and POIs (tactical objects)
  * Fire-mission requests against suspected enemy positions
  * Close Air Support 9-line requests
  * MEDEVAC 9-line reports for casualties
  * Periodic CBRN events around the objective

Unit structure (same as Dendermonde scenario)
  Delta Company
  ├─ DELTA-6 (company commander, ADMIN)
  └─ 3 Platoons (Alpha / Bravo / Charlie)
       └─ each: platoon commander (BATTLE_CAPTAIN) + 2 Sections
            └─ each section: 2 Teams × 3 soldiers

Usage
  uv run python simulate_sluis.py
  uv run python simulate_sluis.py --backend http://localhost:6001 --speed 4
  uv run python simulate_sluis.py --reset
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

import sim_utils

# ── CLI ───────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Arrow Sluis-attack scenario simulator")
parser.add_argument("--backend", default="http://78.21.255.210:6200/api",
                    help="Backend URL (e.g. http://host:6200/api or http://localhost:6001)")
parser.add_argument("--speed", type=float, default=1.0,
                    help="Time multiplier (1 = real time, 6 = 6× faster)")
parser.add_argument("--reset", action="store_true",
                    help="Delete sim operators before starting")
parser.add_argument("--seed-admin", default="benoit",
                    help="Pre-seeded ADMIN callsign (default: benoit)")
parser.add_argument("--seed-admin-password", default="ranger14",
                    help="Password for --seed-admin (default: ranger14)")
parser.add_argument("--mission-name", default="Operation Sluis",
                    help="Mission name to create or adopt (default: Operation Sluis)")
ARGS = parser.parse_args()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("sluis")

BASE          = ARGS.backend.rstrip("/")
MISSION_ID: int | None = None
SIM_PASSWORD  = "Arrow2525!"
WALK_MS       = 5000 / 3600
INFIL_MS      = 1500 / 3600
UPDATE_S      = 10.0
ENEMY_S       = 25.0
FM_S          = 75.0
CAS_S         = 90.0
MEDEVAC_S     = 110.0
CBRN_S        = 240.0
SECTION_STAGGER_S = 90.0

LAT_DEG_PER_M = 1 / 111_000.0


def lon_deg_per_m(lat: float) -> float:
    return 1 / (111_000.0 * math.cos(math.radians(lat)))


def dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = (lat2 - lat1) * 111_000
    dlon = (lon2 - lon1) * 111_000 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)


def step_towards(lat, lon, tlat, tlon, speed_ms, dt):
    d = dist_m(lat, lon, tlat, tlon)
    if d < 0.5:
        return tlat, tlon
    move = min(speed_ms * dt, d)
    dlat = (tlat - lat) * 111_000
    dlon = (tlon - lon) * 111_000 * math.cos(math.radians(lat))
    brg = math.atan2(dlon, dlat)
    return (
        lat + move * math.cos(brg) * LAT_DEG_PER_M,
        lon + move * math.sin(brg) * lon_deg_per_m(lat),
    )


def jitter(lat, lon, north_m, east_m):
    return lat + north_m * LAT_DEG_PER_M, lon + east_m * lon_deg_per_m(lat)


# ── MGRS (compact) ────────────────────────────────────────────────────────────

def _utm_zone(lat, lon):
    if 56 <= lat < 64 and 3 <= lon < 12:
        return 32
    if 72 <= lat <= 84:
        if lon < 9:  return 31
        if lon < 21: return 33
        if lon < 33: return 35
        if lon < 42: return 37
    return int((lon + 180) / 6) + 1


def _lat_band(lat):
    return "CDEFGHJKLMNPQRSTUVWX"[min(19, int((lat + 80) / 8))]


def _to_utm(lat, lon, zone):
    a, f = 6378137, 1 / 298.257223563
    e2 = 2 * f - f * f; e4 = e2 * e2; e6 = e4 * e2; ep2 = e2 / (1 - e2); k0 = 0.9996
    lr = math.radians(lat); lo = math.radians(lon); lo0 = math.radians((zone - 1) * 6 - 180 + 3)
    N = a / math.sqrt(1 - e2 * math.sin(lr) ** 2)
    T = math.tan(lr) ** 2; C = ep2 * math.cos(lr) ** 2; av = math.cos(lr) * (lo - lo0)
    M = a * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * lr
             - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * lr)
             + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * lr)
             - (35 * e6 / 3072) * math.sin(6 * lr))
    e = k0 * N * (av + (1 - T + C) * av ** 3 / 6
                  + (5 - 18 * T + T ** 2 + 72 * C - 58 * ep2) * av ** 5 / 120) + 500_000
    n = k0 * (M + N * math.tan(lr) * (av ** 2 / 2
              + (5 - T + 9 * C + 4 * C ** 2) * av ** 4 / 24
              + (61 - 58 * T + T ** 2 + 600 * C - 330 * ep2) * av ** 6 / 720))
    if lat < 0: n += 10_000_000
    return e, n


_SET_COLS = ["ABCDEFGH", "JKLMNPQR", "STUVWXYZ"]
_ROW_ODD  = "ABCDEFGHJKLMNPQRSTUV"
_ROW_EVEN = "FGHJKLMNPQRSTUVABCDE"


def mgrs(lat, lon, acc=5):
    try:
        z = _utm_zone(lat, lon); b = _lat_band(lat)
        e, n = _to_utm(lat, lon, z)
        col = _SET_COLS[(z - 1) % 3][max(0, min(7, int(e / 100_000) - 1))]
        row = (_ROW_ODD if z % 2 else _ROW_EVEN)[int(n / 100_000) % 20]
        es = str(int(e % 100_000)).zfill(5)[:acc]
        ns = str(int(n % 100_000)).zfill(5)[:acc]
        return f"{z}{b}{col}{row} {es}{ns}"
    except Exception:
        return f"{lat:.4f},{lon:.4f}"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class SimOp:
    callsign: str
    rank: str
    role: str
    formation_idx: int
    token: str = ""
    op_id: int = 0
    lat: float = 0.0
    lon: float = 0.0
    casualties_taken: int = 0


@dataclass
class SimSection:
    name: str
    platoon_code: str
    section_num: int
    operators: list[SimOp] = field(default_factory=list)


# Section formation: 6 soldiers in wedge, ~12 m frontage
_FORMATION = [
    (  8,  0), (  0, -8), (  0,  8),
    (-12, -4), (-12,  4), (-20,  0),
]


def _build_sections() -> tuple[list[SimOp], list[SimSection]]:
    all_ops: list[SimOp] = []
    sections: list[SimSection] = []
    platoons = [("ALPHA", "1st Platoon (Alpha)"),
                ("BRAVO", "2nd Platoon (Bravo)"),
                ("CHARLIE", "3rd Platoon (Charlie)")]
    for plt_code, _ in platoons:
        for sec_num in (1, 2):
            sec = SimSection(name=f"{sec_num}st Section {plt_code.capitalize()}",
                             platoon_code=plt_code, section_num=sec_num)
            for team_num in (1, 2):
                for mbr_num in (1, 2, 3):
                    form_idx = (team_num - 1) * 3 + (mbr_num - 1)
                    is_sl = sec_num == 1 and team_num == 1 and mbr_num == 1
                    is_tl = mbr_num == 1 and not is_sl
                    callsign = f"{plt_code}-{sec_num}{team_num}{mbr_num}"
                    rank = "OR-6" if is_sl else ("OR-5" if is_tl else "OR-3")
                    op = SimOp(callsign=callsign, rank=rank, role="OPERATOR",
                               formation_idx=form_idx)
                    sec.operators.append(op); all_ops.append(op)
            sections.append(sec)

    for plt_code, _ in platoons:
        all_ops.append(SimOp(callsign=f"{plt_code}-6", rank="OF-1",
                             role="BATTLE_CAPTAIN", formation_idx=0))
    all_ops.append(SimOp(callsign="DELTA-6", rank="OF-3", role="ADMIN", formation_idx=0))
    return all_ops, sections


# ── Sluis (NL) routes ─────────────────────────────────────────────────────────
# Sluis town centre  ≈ 51.3093°N, 3.3878°E
# Three axes converge on the town from the south.

ROUTES: dict[str, dict] = {
    "ALPHA": {  # Western axis — via Retranchement / Cadzand approach
        "phase_infil_start": 3,
        "waypoints": [
            (51.2700, 3.3460),   # 0  Staging (Aardenburg fields)
            (51.2820, 3.3520),   # 1  Crossing border, N58
            (51.2940, 3.3640),   # 2  Polders, hedge cover
            (51.3030, 3.3760),   # 3  Edge of Sluis west  ← infil
            (51.3080, 3.3835),   # 4  Western perimeter / Kaai
            (51.3093, 3.3878),   # 5  Objective: Sluis Markt
            (51.3070, 3.3850),   # 6  Consolidation
            (51.2700, 3.3460),   # 7  Loop
        ],
    },
    "BRAVO": {  # Centre axis — N376 Sluis-zuid
        "phase_infil_start": 3,
        "waypoints": [
            (51.2680, 3.3870),   # 0  Staging (south of border post)
            (51.2810, 3.3880),   # 1  N376 northbound
            (51.2950, 3.3900),   # 2  Open polder approach
            (51.3050, 3.3900),   # 3  Zuiddijk / Sluis south  ← infil
            (51.3080, 3.3895),   # 4  South gate / canal
            (51.3093, 3.3878),   # 5  Objective: Sluis Markt
            (51.3075, 3.3895),   # 6  Consolidation
            (51.2680, 3.3870),   # 7  Loop
        ],
    },
    "CHARLIE": {  # Eastern axis — via St. Anna ter Muiden
        "phase_infil_start": 3,
        "waypoints": [
            (51.2700, 3.4300),   # 0  Staging east (Heille area)
            (51.2830, 3.4220),   # 1  Crossing border east
            (51.2960, 3.4080),   # 2  Approach from SE
            (51.3050, 3.3980),   # 3  St. Anna ter Muiden  ← infil
            (51.3088, 3.3925),   # 4  Eastern perimeter
            (51.3093, 3.3878),   # 5  Objective: Sluis Markt
            (51.3075, 3.3905),   # 6  Consolidation
            (51.2700, 3.4300),   # 7  Loop
        ],
    },
}

# Command element loiters south of LD then advances behind centre axis.
CMD_WAYPOINTS = [
    (51.2700, 3.3870),
    (51.2860, 3.3885),
    (51.3000, 3.3895),
    (51.3060, 3.3890),
    (51.3000, 3.3895),
    (51.2700, 3.3870),
]

# Suspected enemy positions defending Sluis (used for fire missions / CAS / contact reports).
# Each: (name, lat, lon, type).
ENEMY_LAYDOWN: list[tuple[str, float, float, str]] = [
    ("Sluis south checkpoint", 51.3055, 3.3890, "INFANTRY"),
    ("Hedgerow MG nest",        51.3045, 3.3815, "INFANTRY"),
    ("Mortar baseplate",        51.3015, 3.3955, "ARTILLERY"),
    ("Armoured technical",      51.3072, 3.3970, "ARMOR"),
    ("Sniper in church tower",  51.3097, 3.3870, "SNIPER"),
    ("Recce team woods east",   51.3030, 3.4030, "VEHICLE"),
    ("Rear depot — N376 farm",  51.2960, 3.3905, "POI"),
]


# ── HTTP helpers ──────────────────────────────────────────────────────────────

async def api(client: httpx.AsyncClient, method: str, path: str,
              token: str = "", **kwargs) -> Optional[dict]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if MISSION_ID:
        headers["X-Mission-ID"] = str(MISSION_ID)
    try:
        r = await client.request(method, f"{BASE}{path}", headers=headers,
                                 timeout=10, **kwargs)
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 409:
            return None
        log.warning("%-6s %-30s → %d  %s", method, path, r.status_code, r.text[:100])
        return None
    except Exception as exc:
        log.warning("%-6s %-30s → %s", method, path, exc)
        return None


async def login(client, callsign, password=SIM_PASSWORD) -> Optional[str]:
    try:
        r = await client.post(f"{BASE}/auth/login",
                              data={"username": callsign, "password": password},
                              timeout=10)
        if r.status_code == 200:
            return r.json().get("access_token")
    except Exception:
        pass
    return None


# ── Bootstrap (mirrors simulate.py) ──────────────────────────────────────────

async def bootstrap(client, all_ops, sections) -> str:
    log.info("── Bootstrap ─────────────────────────────────────────")
    seed_token = await login(client, ARGS.seed_admin, ARGS.seed_admin_password)
    if not seed_token:
        raise RuntimeError(
            f"Cannot login as seed admin {ARGS.seed_admin!r}. "
            "Ensure backend is running and seeded."
        )
    log.info("Logged in as seed admin %s", ARGS.seed_admin)
    admin_token = seed_token

    admin_op = next(o for o in all_ops if o.role == "ADMIN")
    sim_admin_token = await login(client, admin_op.callsign)
    if not sim_admin_token:
        r = await api(client, "POST", "/auth/register/admin", token=seed_token, json={
            "callsign": admin_op.callsign, "password": SIM_PASSWORD,
            "rank": admin_op.rank, "role": "ADMIN"})
        if r and r.get("access_token"):
            sim_admin_token = r["access_token"]
            log.info("Registered %s (ADMIN)", admin_op.callsign)
    else:
        ops = await api(client, "GET", "/operators", token=seed_token) or []
        row = next((o for o in ops if o["callsign"] == admin_op.callsign), None)
        if row and row.get("role") != "ADMIN":
            await api(client, "PATCH", f"/operators/{row['id']}",
                      token=seed_token, json={"role": "ADMIN"})
            log.info("Promoted %s to ADMIN", admin_op.callsign)
            sim_admin_token = await login(client, admin_op.callsign) or sim_admin_token
    admin_op.token = sim_admin_token or seed_token

    companies = await api(client, "GET", "/companies", token=admin_token) or []
    company = next((c for c in companies if c["name"] == "Delta Company"), None)
    if not company:
        company = await api(client, "POST", "/companies", token=admin_token,
                            json={"name": "Delta Company"})
        if not company:
            raise RuntimeError("Failed to create Delta Company")
        log.info("Created Delta Company (id=%d)", company["id"])
    company_id = company["id"]

    plt_ids: dict[str, int] = {}
    sec_ids: dict[str, int] = {}
    for code, name in [("ALPHA", "1st Platoon (Alpha)"),
                       ("BRAVO", "2nd Platoon (Bravo)"),
                       ("CHARLIE", "3rd Platoon (Charlie)")]:
        plt = await api(client, "GET", "/platoons", token=admin_token) or []
        existing = next((p for p in plt if p["name"] == name), None)
        if existing:
            plt_ids[code] = existing["id"]
        else:
            r = await api(client, "POST", "/platoons", token=admin_token,
                          json={"name": name, "company_id": company_id})
            if r:
                plt_ids[code] = r["id"]
                log.info("  Created platoon %s", name)

    sections_resp = await api(client, "GET", "/sections", token=admin_token) or []
    teams_resp    = await api(client, "GET", "/teams", token=admin_token) or []
    team_name_to_id = {t["name"]: t["id"] for t in teams_resp}
    for s in sections_resp:
        for sec in sections:
            if s["name"] == sec.name:
                sec_ids[f"{sec.platoon_code}-{sec.section_num}"] = s["id"]

    for sec in sections:
        key = f"{sec.platoon_code}-{sec.section_num}"
        if key not in sec_ids:
            r = await api(client, "POST", "/sections", token=admin_token,
                          json={"name": sec.name, "platoon_id": plt_ids[sec.platoon_code]})
            if r:
                sec_ids[key] = r["id"]
                log.info("    Created section %s", sec.name)
        sec_id = sec_ids.get(key)
        if not sec_id:
            continue
        for team_num in (1, 2):
            tname = f"Team {sec.platoon_code}-{sec.section_num}{team_num}"
            if tname not in team_name_to_id:
                r = await api(client, "POST", "/teams", token=admin_token,
                              json={"name": tname, "section_id": sec_id})
                if r:
                    team_name_to_id[tname] = r["id"]

    existing_ops = {o["callsign"]: o for o in
                    (await api(client, "GET", "/operators", token=admin_token) or [])}

    for sec in sections:
        for idx, op in enumerate(sec.operators):
            team_num = (idx // 3) + 1
            tname = f"Team {sec.platoon_code}-{sec.section_num}{team_num}"
            team_id = team_name_to_id.get(tname)
            ex = existing_ops.get(op.callsign)
            if not ex:
                r = await api(client, "POST", "/auth/register/admin",
                              token=admin_token, json={
                    "callsign": op.callsign, "password": SIM_PASSWORD,
                    "rank": op.rank, "role": op.role, "team_id": team_id})
                if r:
                    log.info("  Registered %-14s → %s", op.callsign, tname)
            else:
                op.op_id = ex.get("id", 0)
                if team_id and ex.get("team_id") != team_id:
                    await api(client, "PATCH", f"/operators/{ex['id']}",
                              token=admin_token, json={"team_id": team_id})

    for plt_code in ("ALPHA", "BRAVO", "CHARLIE"):
        cs = f"{plt_code}-6"
        if cs not in existing_ops:
            await api(client, "POST", "/auth/register/admin", token=admin_token, json={
                "callsign": cs, "password": SIM_PASSWORD,
                "rank": "OF-1", "role": "BATTLE_CAPTAIN"})
            log.info("  Registered %-14s (BATTLE_CAPTAIN)", cs)

    log.info("── Bootstrap complete ────────────────────────────────")
    return admin_token


async def login_all(client, all_ops):
    log.info("── Logging in %d operators ───────────────────────────", len(all_ops))
    tokens = await asyncio.gather(*(login(client, o.callsign) for o in all_ops))
    ok = fail = 0
    for op, tok in zip(all_ops, tokens):
        if tok: op.token = tok; ok += 1
        else:   fail += 1
    log.info("  %d OK  %d failed", ok, fail)

    admin_op = next((o for o in all_ops if o.role == "ADMIN"), None)
    if admin_op and admin_op.token:
        rows = await api(client, "GET", "/operators", token=admin_op.token) or []
        m = {r["callsign"]: r["id"] for r in rows}
        for op in all_ops:
            op.op_id = m.get(op.callsign, 0)


# ── Movement ──────────────────────────────────────────────────────────────────

async def run_section(client, sec, speed_mult, stagger_s):
    route = ROUTES[sec.platoon_code]
    waypoints = route["waypoints"]
    infil_start = route["phase_infil_start"]
    real_dt = UPDATE_S / speed_mult

    if stagger_s > 0:
        await asyncio.sleep(stagger_s / speed_mult)

    start = waypoints[0]
    for i, op in enumerate(sec.operators):
        off = _FORMATION[min(i, len(_FORMATION) - 1)]
        op.lat, op.lon = jitter(start[0], start[1], off[0], off[1])

    wp_idx = 0
    log.info("Section %-22s LD → WP0  (axis %s)", sec.name, sec.platoon_code)

    while True:
        tlat, tlon = waypoints[wp_idx]
        speed = INFIL_MS if wp_idx >= infil_start else WALK_MS
        while True:
            clat, clon = sec.operators[0].lat, sec.operators[0].lon
            nclat, nclon = step_towards(clat, clon, tlat, tlon, speed, real_dt * speed_mult)
            dlat = nclat - clat
            dlon = nclon - clon
            tasks = []
            for op in sec.operators:
                if not op.token:
                    continue
                op.lat += dlat + random.gauss(0, 0.2) * LAT_DEG_PER_M
                op.lon += dlon + random.gauss(0, 0.2) * lon_deg_per_m(op.lat)
                tasks.append(api(client, "POST", "/tracking/position", token=op.token,
                                 json={"latitude": op.lat, "longitude": op.lon,
                                       "altitude": round(random.uniform(2, 8), 1)}))
            if tasks:
                await asyncio.gather(*tasks)
            await asyncio.sleep(real_dt)
            if dist_m(nclat, nclon, tlat, tlon) < 5:
                break
        wp_idx = (wp_idx + 1) % len(waypoints)
        nlat, nlon = waypoints[wp_idx]
        log.info("Section %-22s → WP%d  %s  (%s)",
                 sec.name, wp_idx, mgrs(nlat, nlon),
                 "infil" if wp_idx >= infil_start else "walk")


async def run_command(client, all_ops, speed_mult):
    cmd_ops = [o for o in all_ops if o.role in ("ADMIN", "BATTLE_CAPTAIN")]
    real_dt = UPDATE_S / speed_mult
    wp_idx = 0
    for i, op in enumerate(cmd_ops):
        wp = CMD_WAYPOINTS[0]
        op.lat = wp[0] + i * 0.0003
        op.lon = wp[1] + i * 0.0002
    while True:
        tlat, tlon = CMD_WAYPOINTS[wp_idx]
        while True:
            tasks = []
            for op in cmd_ops:
                if not op.token: continue
                op.lat, op.lon = step_towards(op.lat, op.lon, tlat, tlon,
                                              WALK_MS, real_dt * speed_mult)
                op.lat += random.gauss(0, 0.3) * LAT_DEG_PER_M
                op.lon += random.gauss(0, 0.3) * lon_deg_per_m(op.lat)
                tasks.append(api(client, "POST", "/tracking/position", token=op.token,
                                 json={"latitude": op.lat, "longitude": op.lon}))
            if tasks: await asyncio.gather(*tasks)
            await asyncio.sleep(real_dt)
            if dist_m(op.lat, op.lon, tlat, tlon) < 10:
                break
        wp_idx = (wp_idx + 1) % len(CMD_WAYPOINTS)


# ── Helpers for picking actors / targets ─────────────────────────────────────

SPOT_DIRECTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _pick_forward_op(sections) -> Optional[SimOp]:
    candidates = [o for sec in sections for o in sec.operators
                  if o.token and o.lat != 0]
    return random.choice(candidates) if candidates else None


def _pick_enemy_target() -> tuple[str, float, float, str]:
    name, lat, lon, etype = random.choice(ENEMY_LAYDOWN)
    # Slight wiggle to avoid identical reports stacking.
    lat += random.uniform(-0.0008, 0.0008)
    lon += random.uniform(-0.0008, 0.0008)
    return name, lat, lon, etype


# ── Enemy contacts (tactical objects + broadcast chatter) ────────────────────

_ENEMY_NOTES = {
    "INFANTRY":  "Squad-strength infantry observed",
    "ARMOR":     "Armoured vehicle, direction of movement unknown",
    "ARTILLERY": "Indirect fire baseplate suspected",
    "SNIPER":    "Sniper fire received from elevated position",
    "VEHICLE":   "Unknown vehicle, possible recce",
    "POI":       "Point of interest — possible cache / ORP",
}
_SIDC = {
    "INFANTRY":  "SHGPUCI-----",
    "ARMOR":     "SHGPUCA-----",
    "ARTILLERY": "SHGPUCF-----",
    "SNIPER":    "SHGPUCIS----",
    "VEHICLE":   "SHGPEV------",
    "POI":       "SNGPI-------",
}


async def run_enemy_marker(client, sections, speed_mult):
    real_interval = ENEMY_S / speed_mult
    await asyncio.sleep(real_interval * 0.3)
    n = 0
    while True:
        await asyncio.sleep(real_interval)
        op = _pick_forward_op(sections)
        if not op:
            continue
        name, elat, elon, etype = _pick_enemy_target()
        notes = f"{_ENEMY_NOTES.get(etype, etype)}  ({name})  MGRS: {mgrs(elat, elon)}"
        n += 1
        await api(client, "POST", "/tactical-objects", token=op.token,
                  json={"type": etype, "symbol_code": _SIDC.get(etype, ""),
                        "latitude": round(elat, 6), "longitude": round(elon, 6),
                        "notes": notes, "visibility": "COMPANY"})
        log.info("⚠️  %s  CONTACT  %-12s  %-22s  %s  (#%d)",
                 op.callsign, etype, name[:22], mgrs(elat, elon), n)
        await api(client, "POST", "/messages", token=op.token,
                  json={"content": f"CONTACT — {etype} ({name}) grid {mgrs(elat, elon)}",
                        "message_type": "BROADCAST"})


# ── Fire missions ─────────────────────────────────────────────────────────────

_AMMUNITION = ["HE", "ILLUM", "SMOKE", "WP"]
_MISSIONS   = ["ADJUST_FIRE", "FIRE_FOR_EFFECT", "SUPPRESSION", "DESTRUCTION"]


async def run_fire_missions(client, sections, speed_mult):
    real_interval = FM_S / speed_mult
    await asyncio.sleep(real_interval * 0.6)
    n = 0
    while True:
        await asyncio.sleep(real_interval)
        op = _pick_forward_op(sections)
        if not op:
            continue
        name, tlat, tlon, _etype = _pick_enemy_target()
        ammo  = random.choice(_AMMUNITION)
        mtype = random.choice(_MISSIONS)
        qty   = random.choice([3, 4, 6, 8])
        bearing = random.randint(0, 359)
        n += 1
        r = await api(client, "POST", "/fire-missions", token=op.token, json={
            "latitude":     round(tlat, 6),
            "longitude":    round(tlon, 6),
            "altitude":     round(random.uniform(0, 5), 1),
            "direction":    bearing,
            "mission_type": mtype,
            "ammunition":   ammo,
            "quantity":     qty,
            "description":  f"FFE on {name}",
            "notes":        f"Requested by {op.callsign}",
        })
        if r:
            log.info("🎯 %s  FIRE MISSION  %-16s  %s ×%d  on %-22s  %s  (#%d)",
                     op.callsign, mtype, ammo, qty, name[:22],
                     mgrs(tlat, tlon), n)


# ── CAS 9-line ────────────────────────────────────────────────────────────────

_CAS_AIRCRAFT = ["F-16C", "F-35A", "A-10C", "AH-64D", "AH-1Z", "EUROFIGHTER"]
_CAS_ORDNANCE = ["GBU-12 LGB", "AGM-65 MAVERICK", "20MM CANNON", "HELLFIRE", "GBU-39 SDB"]
_CAS_MARK     = ["IR STROBE", "VS-17 PANEL", "SMOKE GREEN", "LASER 1688", "GLINT TAPE"]


async def run_cas(client, sections, speed_mult):
    real_interval = CAS_S / speed_mult
    await asyncio.sleep(real_interval * 0.8)
    n = 0
    while True:
        await asyncio.sleep(real_interval)
        op = _pick_forward_op(sections)
        if not op:
            continue
        name, tlat, tlon, etype = _pick_enemy_target()
        grid = mgrs(tlat, tlon)
        aircraft = random.choice(_CAS_AIRCRAFT)
        ord_     = random.choice(_CAS_ORDNANCE)
        mark     = random.choice(_CAS_MARK)
        friend_m = random.choice([200, 300, 400, 500])
        bearing  = random.choice(SPOT_DIRECTIONS)
        n += 1
        payload = {
            "line_1_ip":               f"IP {random.choice(['ALPHA','BRAVO','CHARLIE','DELTA'])}",
            "line_2_heading":          random.randint(0, 359),
            "line_3_distance_m":       random.randint(2000, 8000),
            "line_4_target_elevation": random.randint(2, 30),
            "line_5_target_desc":      f"{etype} — {name}",
            "line_6_target_location": {"latitude": round(tlat, 5),
                                       "longitude": round(tlon, 5),
                                       "mgrs": grid},
            "line_7_marking":          mark,
            "line_8_friendlies":       f"{friend_m}m {bearing}",
            "line_9_egress":           random.choice(["NORTH", "SOUTH", "EAST", "WEST"]),
            "aircraft_requested":      aircraft,
            "ordnance_requested":      ord_,
            "remarks":                 f"Type 2. CAS on {name}.",
            "latitude":  round(tlat, 5),
            "longitude": round(tlon, 5),
            "grid":      grid,
        }
        r = await api(client, "POST", "/reports", token=op.token,
                      json={"type": "CAS", "payload": payload})
        if r:
            log.info("✈️  %s  CAS REQ  %-22s  %s  %s/%s  (#%d)",
                     op.callsign, name[:22], grid, aircraft, ord_, n)


# ── MEDEVAC 9-line ────────────────────────────────────────────────────────────

_PRECEDENCE   = ["A — URGENT", "B — URGENT SURGICAL", "C — PRIORITY", "D — ROUTINE"]
_EQUIPMENT    = ["A — NONE", "B — HOIST", "C — EXTRACTION", "D — VENTILATOR"]
_PATIENT_TYPE = ["A — LITTER", "B — AMBULATORY"]
_SECURITY     = ["N — NO ENEMY", "P — POSSIBLE ENEMY", "E — ENEMY IN AREA",
                 "X — ENEMY IN AREA — ARMED ESCORT REQUIRED"]
_NATIONALITY  = ["A — US MILITARY", "B — US CIVILIAN",
                 "C — NON-US MILITARY", "D — NON-US CIVILIAN", "E — EPW"]
_NBC          = ["N — NUCLEAR", "B — BIOLOGICAL", "C — CHEMICAL", "0 — NONE"]
_INJURIES     = [
    "GSW chest, conscious, rapid breathing",
    "Frag wounds bilateral lower extremities",
    "Blast injury, suspected TBI",
    "GSW abdomen, hypotensive",
    "Burn 30% TBSA, airway compromise concern",
    "GSW upper extremity, controlled hemorrhage",
    "Crush injury, lower leg",
]


async def run_medevac(client, sections, speed_mult):
    real_interval = MEDEVAC_S / speed_mult
    await asyncio.sleep(real_interval * 1.0)
    n = 0
    while True:
        await asyncio.sleep(real_interval)
        op = _pick_forward_op(sections)
        if not op:
            continue
        # Pickup point near the requesting op
        plat = op.lat + random.uniform(-0.0006, 0.0006)
        plon = op.lon + random.uniform(-0.0006, 0.0006)
        grid = mgrs(plat, plon)
        urgent = random.random() < 0.5
        precedence = random.choice(_PRECEDENCE[:2] if urgent else _PRECEDENCE)
        litter = random.randint(0, 2)
        ambulatory = random.randint(0, 3)
        op.casualties_taken += litter + ambulatory
        injury = random.choice(_INJURIES)
        n += 1
        payload = {
            "line_1_location":     {"latitude": round(plat, 5),
                                    "longitude": round(plon, 5),
                                    "mgrs": grid},
            "line_2_callsign_freq": f"{op.callsign} / 32.450 MHz",
            "line_3_precedence":    precedence,
            "line_4_equipment":     random.choice(_EQUIPMENT),
            "line_5_patients":      {"litter": litter, "ambulatory": ambulatory},
            "line_6_security":      random.choice(_SECURITY),
            "line_7_marking":       random.choice(_CAS_MARK),
            "line_8_nationality":   random.choice(_NATIONALITY),
            "line_9_nbc":           random.choice(_NBC),
            "remarks":              injury,
            "latitude":  round(plat, 5),
            "longitude": round(plon, 5),
            "grid":      grid,
        }
        r = await api(client, "POST", "/reports", token=op.token,
                      json={"type": "MEDEVAC", "payload": payload})
        if r:
            log.info("🚑 %s  MEDEVAC  %s  L%d/A%d  %s  %-40s  (#%d)",
                     op.callsign, precedence.split(" — ")[0],
                     litter, ambulatory, grid, injury[:40], n)
        # Audible call on broadcast
        await api(client, "POST", "/messages", token=op.token,
                  json={"content": f"MEDEVAC {precedence.split(' — ')[0]} — "
                                   f"{litter}L/{ambulatory}A — grid {grid}",
                        "message_type": "BROADCAST"})


# ── CBRN around objective ────────────────────────────────────────────────────

_CBRN_AGENTS = [
    ("C", "CBRN_4", "CHLORINE",        "Industrial chemical release"),
    ("C", "CBRN_4", "SARIN (GB)",      "Suspected nerve-agent munition"),
    ("R", "CBRN_3", "DIRTY-BOMB",      "RDD detonation reported"),
    ("B", "CBRN_4", "ANTHRAX",         "Suspected biological dispersal"),
]


async def run_cbrn(client, admin_op, speed_mult):
    real_interval = CBRN_S / speed_mult
    await asyncio.sleep(real_interval * 1.0)
    n = 0
    while True:
        await asyncio.sleep(real_interval)
        if not admin_op.token:
            continue
        # Anchor near Sluis but offset up to ~3 km
        lat = 51.3093 + random.uniform(-0.030, 0.030)
        lon = 3.3878  + random.uniform(-0.040, 0.040)
        cat, mtype, agent, notes = random.choice(_CBRN_AGENTS)
        wind_dir   = random.randint(0, 359)
        wind_speed = random.randint(5, 35)
        zi = {"C": 800, "B": 1500, "R": 1200, "N": 4000}[cat]
        zd = zi * random.randint(3, 7)
        n += 1
        payload = {
            "msg_type": mtype,
            "agent_category": cat, "agent": agent,
            "latitude": round(lat, 5), "longitude": round(lon, 5),
            "wind_direction": wind_dir, "wind_speed": wind_speed,
            "zone_inner_m": zi, "zone_downwind_m": zd,
            "zone_downwind_angle_deg": 30,
            "dtg": "", "serial": f"SLUIS{n:03d}", "notes": notes, "lines": {},
        }
        r = await api(client, "POST", "/reports", token=admin_op.token,
                      json={"type": mtype, "payload": payload})
        if r:
            log.info("☣️  CBRN %s  %-14s  %.4f,%.4f  wind %d°@%dkm/h  (#%d)",
                     mtype, agent, lat, lon, wind_dir, wind_speed, n)


# ── Reset helper ──────────────────────────────────────────────────────────────

async def reset_sim(client, all_ops):
    log.info("── Reset: deleting sim operators ─────────────────────")
    token = await login(client, ARGS.seed_admin, ARGS.seed_admin_password)
    if not token:
        log.warning("Cannot login as seed admin — skipping reset")
        return
    rows = await api(client, "GET", "/operators", token=token) or []
    sim_callsigns = {o.callsign for o in all_ops}
    for row in rows:
        if row["callsign"] in sim_callsigns and row["callsign"] != ARGS.seed_admin:
            await api(client, "DELETE", f"/operators/{row['id']}", token=token)
            log.info("  Deleted %s", row["callsign"])


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    all_ops, sections = _build_sections()
    speed_mult = ARGS.speed

    log.info("=== Arrow Tactical Simulator — Operation Sluis ===")
    log.info("Backend : %s", BASE)
    log.info("Operators: %d  |  Sections: %d  |  Speed: %.1f×",
             len(all_ops), len(sections), speed_mult)
    log.info("Walk %.1f km/h  Infil %.1f km/h  Update every %gs",
             WALK_MS * 3.6, INFIL_MS * 3.6, UPDATE_S / speed_mult)
    log.info("Enemy %gs  FM %gs  CAS %gs  MEDEVAC %gs  CBRN %gs",
             ENEMY_S / speed_mult, FM_S / speed_mult,
             CAS_S / speed_mult, MEDEVAC_S / speed_mult, CBRN_S / speed_mult)

    async with httpx.AsyncClient() as client:
        if ARGS.reset:
            await reset_sim(client, all_ops)
        admin_token = await bootstrap(client, all_ops, sections)
        global MISSION_ID
        MISSION_ID = await sim_utils.create_mission_async(
            client, BASE, admin_token, ARGS.mission_name)
        await login_all(client, all_ops)

        coros = []
        for sec in sections:
            stagger = 0.0 if sec.section_num == 1 else SECTION_STAGGER_S
            coros.append(run_section(client, sec, speed_mult, stagger))
        coros.append(run_command(client, all_ops, speed_mult))
        coros.append(run_enemy_marker(client, sections, speed_mult))
        coros.append(run_fire_missions(client, sections, speed_mult))
        coros.append(run_cas(client, sections, speed_mult))
        coros.append(run_medevac(client, sections, speed_mult))

        admin_op = next(o for o in all_ops if o.role == "ADMIN")
        coros.append(run_cbrn(client, admin_op, speed_mult))

        log.info("=== Operation Sluis running — Ctrl-C to stop ===")
        try:
            await asyncio.gather(*coros)
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Simulator stopped.")
