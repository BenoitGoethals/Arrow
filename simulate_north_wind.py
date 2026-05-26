#!/usr/bin/env python3
"""
Arrow Brigade Simulator — OPERATION NORTH WIND
==============================================

Brigade-level invasion of the Netherlands from the Belgian border (Lommel) to
Dokkum (Friesland), 8 phase objectives along the central NL corridor.

Works like simulate.py:
  • Defaults to the production backend  ``http://78.21.255.210:6200/api``
  • Async HTTP via httpx (drives a live, observable demo)
  • Plants the full ORBAT, tactical control graphics, enemy positions, OPORD
  • Registers brigade-level operators (BDE CDR + BN COs + recce teams)
  • Animates them along the brigade axis through the 8 phases — everything is
    visible on the web map / Android map in real time, with periodic
    contact reports and tactical-object marks.

Friendly forces — 21 PANZER BRIGADE (DEU/NLD multinational)
  HHC · 1/2/3-21 PzBn (Leopard 2A7) · 4/5-21 PzGrenBn (Puma/Marder)
  21 Recce Bn (Fennek/CV90) · 21 Arty Bn (PzH 2000, MARS II) · 21 Engr Bn
  21 AD Coy (IRIS-T SLM) · 21 Log Bn · 21 Med Coy · 21 Sig Coy

Enemy forces — 36 GUARDS MOTOR RIFLE BRIGADE (defending in depth)
  2× Tank Bn (T-90M) · 2× MRB (BMP-3/BTR-82A) · Recce (BRM-1K)
  SP Arty Bn (2S19 Msta-S) · MLRS Btry (BM-21) · AD (Tor-M2 / Strela-10)
  AT (Kornet / Khrizantema-S) · Engr · EW (Borisoglebsk-2 / Pole-21)

Phase plan (south → north):
  Φ1 ANVIL   — Eindhoven                Φ2 HAMMER  — 's-Hertogenbosch
  Φ3 BRIDGE  — Nijmegen (Waal)          Φ4 ARROW   — Arnhem (Nederrijn)
  Φ5 SHIELD  — Apeldoorn                Φ6 DAGGER  — Zwolle (IJssel)
  Φ7 EAGLE   — Heerenveen               Φ8 NORTH   — Dokkum

Run:
  uv run python simulate_north_wind.py
  uv run python simulate_north_wind.py --backend http://192.168.0.240:6001
  uv run python simulate_north_wind.py --speed 30      # 30× real time
  uv run python simulate_north_wind.py --no-live       # static plant only
  uv run python simulate_north_wind.py --reset         # wipe TGs + OPORDs + sim ops first
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import random
import sys
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlsplit
import httpx

import sim_utils

# ── CLI / persistent config ─────────────────────────────────────────────────
# simulate.py-compatible default — points at the production server so just
# running the script with no args drops the brigade onto everyone's map.
DEFAULT_BACKEND = (
    os.environ.get("ARROW_BACKEND_URL")
    or sim_utils.load_saved_backend()
    or "http://78.21.255.210:6200/api"
)

parser = argparse.ArgumentParser(description="Arrow brigade simulator — OPERATION NORTH WIND")
parser.add_argument("--backend",  default=DEFAULT_BACKEND,
                    help=f"Backend base URL (default: {DEFAULT_BACKEND})")
parser.add_argument("--admin",    default="benoit",   help="Seed ADMIN callsign")
parser.add_argument("--password", default="ranger14", help="Seed ADMIN password")
parser.add_argument("--reset",    action="store_true",
                    help="Wipe TGs/enemies/POIs, prior NORTH WIND OPORD, and sim operators first")
parser.add_argument("--no-live",  action="store_true",
                    help="Plant the static OPORD + tactical objects then exit (no live operators)")
parser.add_argument("--skip-snapshots", action="store_true",
                    help="Don't request server-side OSM-tile snapshots for the OPORD")
parser.add_argument("--speed",    type=float, default=2.0,
                    help="Live-phase time multiplier; 1 = real time, 2 = 2× faster (default). "
                         "At default each phase = ~15 s; full advance Lommel → Dokkum ≈ 2 min.")
parser.add_argument("--loop",     action="store_true", default=True,
                    help="After Φ8, loop back to Φ1 so the demo keeps running (default on)")
parser.add_argument("--once",     dest="loop", action="store_false",
                    help="Stop after Φ8 instead of looping")
parser.add_argument("--mission-name", default="Operation North Wind",
                    help="Mission name to create or adopt (default: Operation North Wind)")
ARGS = parser.parse_args()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("nw")

BASE = ARGS.backend.rstrip("/")
MISSION_ID: int | None = None

ORIGIN, PATH_PREFIX = sim_utils.split_base(BASE)


# ── Tactical-graphic & object types ─────────────────────────────────────────
POINT_TG_TYPES = {"ATK_AXIS", "COUNTERATTACK", "AMBUSH", "DEF_AREA",
                  "BLOCK", "BYPASS", "WITHDRAW"}
LINE_TG_TYPES  = {"BOUNDARY", "FLET", "FLOT", "PHASE_LINE"}
POLY_TG_TYPES  = {"OBJ_AREA"}
ALL_TG_TYPES   = POINT_TG_TYPES | LINE_TG_TYPES | POLY_TG_TYPES
NON_TG_TYPES   = {"ENEMY", "POI", "MARKER", "OBJECTIVE", "ROUTE", "ZONE"}


# ── Geo helpers ──────────────────────────────────────────────────────────────
LAT_DEG_PER_M = 1 / 111_000.0

def lon_deg_per_m(lat: float) -> float:
    return 1 / (111_000.0 * math.cos(math.radians(lat)))

def dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = (lat2 - lat1) * 111_000
    dlon = (lon2 - lon1) * 111_000 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)

def step_towards(lat: float, lon: float, tlat: float, tlon: float,
                 speed_ms: float, dt: float) -> tuple[float, float]:
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


@dataclass(frozen=True)
class LatLon:
    lat: float
    lon: float

    def offset_m(self, north_m: float, east_m: float) -> "LatLon":
        return LatLon(self.lat + north_m / 111_320.0,
                      self.lon + east_m  / (111_320.0 * math.cos(math.radians(self.lat))))

    def bearing_m(self, bearing_deg: float, distance_m: float) -> "LatLon":
        rad = math.radians(bearing_deg)
        return self.offset_m(distance_m * math.cos(rad), distance_m * math.sin(rad))

    def as_pair(self) -> list[float]:
        return [self.lat, self.lon]


# ── Phase-by-phase plan ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class Phase:
    idx: int
    obj_name: str
    city: str
    centre: LatLon
    main_effort_bn: str
    waterway: str = ""

PHASES: list[Phase] = [
    Phase(1, "ANVIL",   "Eindhoven",        LatLon(51.4416, 5.4697), "4-21 PzGren Bn",        ""),
    Phase(2, "HAMMER",  "'s-Hertogenbosch", LatLon(51.6978, 5.3037), "1-21 Panzer Bn",        ""),
    Phase(3, "BRIDGE",  "Nijmegen",         LatLon(51.8126, 5.8372), "4-21 PzGren Bn",        "Waal"),
    Phase(4, "ARROW",   "Arnhem",           LatLon(51.9851, 5.8987), "1-21 Panzer Bn",        "Nederrijn"),
    Phase(5, "SHIELD",  "Apeldoorn",        LatLon(52.2112, 5.9699), "2-21 Panzer Bn",        ""),
    Phase(6, "DAGGER",  "Zwolle",           LatLon(52.5168, 6.0830), "5-21 PzGren Bn",        "IJssel"),
    Phase(7, "EAGLE",   "Heerenveen",       LatLon(52.9602, 5.9189), "2-21 Panzer Bn",        ""),
    Phase(8, "NORTH",   "Dokkum",           LatLon(53.3257, 5.9986), "4-21 PzGren Bn",        ""),
]

LD_CENTRE = LatLon(51.2333, 5.3133)      # Lommel / NL border crossing
LEFT_BOUNDARY_LON   = 5.0
RIGHT_BOUNDARY_LON  = 6.3


# ── HTTP plumbing (async, simulate.py-style) ────────────────────────────────
def _p(path: str) -> str:
    if not PATH_PREFIX or path.startswith(PATH_PREFIX + "/") or path == PATH_PREFIX:
        return path
    return PATH_PREFIX + path

_API_FAIL_COUNT = 0    # bumped on each non-2xx so we can log the first few loudly

async def api(client: httpx.AsyncClient, method: str, path: str,
              token: str = "", **kwargs) -> Optional[dict]:
    """Async request returning JSON or None. Logs non-2xx without aborting.

    First 5 failures are logged with the full response body so the operator
    can immediately tell whether it's auth, schema validation, or a missing
    endpoint. After that we throttle to avoid drowning the console.
    """
    global _API_FAIL_COUNT
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if MISSION_ID:
        headers["X-Mission-ID"] = str(MISSION_ID)
    try:
        r = await client.request(method, _p(path), headers=headers, timeout=20, **kwargs)
        if 200 <= r.status_code < 300:
            return r.json() if r.content else {}
        _API_FAIL_COUNT += 1
        body = r.text[:400] if _API_FAIL_COUNT <= 5 else r.text[:80]
        log.warning("%-6s %-30s → %d  %s", method, path, r.status_code, body)
        return None
    except Exception as exc:
        _API_FAIL_COUNT += 1
        log.warning("%-6s %-30s → %s", method, path, exc)
        return None

async def login(client: httpx.AsyncClient, callsign: str, password: str) -> Optional[str]:
    """POST /auth/login.

    On exception we log the *type* of the exception alongside its message —
    httpx raises ``ConnectTimeout`` / ``ConnectError`` / ``ReadTimeout`` with
    empty messages, so logging just ``str(exc)`` produces a silent warning
    that's nearly impossible to diagnose. The type tells the operator at a
    glance whether it's a wrong host, a closed port, a slow backend, or a
    genuine 4xx/5xx response.
    """
    try:
        r = await client.post(_p("/auth/login"),
                              data={"username": callsign, "password": password},
                              timeout=15)
        if r.status_code == 200:
            payload = r.json()
            if payload.get("mfa_required"):
                log.error("Account %s has MFA enabled — use a non-MFA admin.", callsign)
                return None
            return payload.get("access_token")
        log.warning("login %s → HTTP %d  %s",
                    callsign, r.status_code, (r.text or "<empty body>")[:200])
    except httpx.ConnectError as exc:
        log.warning("login %s → CONNECT-ERROR: %s (host unreachable / wrong --backend URL?)",
                    callsign, exc or "no detail")
    except httpx.ConnectTimeout as exc:
        log.warning("login %s → CONNECT-TIMEOUT after 15s: %s "
                    "(port firewalled or wrong --backend URL?)",
                    callsign, exc or "no detail")
    except httpx.ReadTimeout as exc:
        log.warning("login %s → READ-TIMEOUT after 15s: %s "
                    "(backend reachable but unresponsive)",
                    callsign, exc or "no detail")
    except Exception as exc:
        log.warning("login %s → %s: %s",
                    callsign, type(exc).__name__, exc or "no detail")
    return None


# ── Static-phase: plant tactical objects ────────────────────────────────────
def build_phase_objects(prev: LatLon, ph: Phase, nxt: LatLon | None) -> list[dict]:
    """Friendly OBJ + axes + reserve + boundaries + enemy ORBAT + POIs."""
    items: list[dict] = []
    centre = ph.centre
    NORTH, SOUTH, EAST, WEST = 0.0, 180.0, 90.0, 270.0

    def tg(type_, lat, lon, *, affiliation="FRIENDLY", echelon="", notes="",
           rotation=0.0, geometry="", symbol_code=""):
        return {"type": type_, "latitude": lat, "longitude": lon,
                "affiliation": affiliation, "echelon": echelon, "notes": notes,
                "rotation": rotation, "geometry": geometry,
                "symbol_code": symbol_code, "visibility": "COMPANY"}

    def line(type_, pts):
        return tg(type_, pts[0].lat, pts[0].lon,
                  geometry=json.dumps({"type": "line",
                                       "coords": [p.as_pair() for p in pts]}))

    def poly(type_, pts, **kw):
        return tg(type_, pts[0].lat, pts[0].lon,
                  geometry=json.dumps({"type": "polygon",
                                       "coords": [p.as_pair() for p in pts]}),
                  **kw)

    # 1. BDE objective polygon
    obj_poly = [centre.offset_m( 1_800, -2_200), centre.offset_m( 1_800,  2_200),
                centre.offset_m(-1_400,  2_200), centre.offset_m(-1_400, -2_200)]
    items.append(poly("OBJ_AREA", obj_poly, echelon="BDE",
                      notes=f"Φ{ph.idx} OBJ {ph.obj_name} — 21 BDE objective ({ph.city})"))

    # 2. Attack axes (main + L/R screens)
    aa = LatLon(
        prev.lat + (centre.lat - prev.lat) * 0.4,
        prev.lon + (centre.lon - prev.lon) * 0.4,
    )
    items.append(tg("ATK_AXIS", *aa.as_pair(), echelon="BN", rotation=NORTH,
                    notes=f"Φ{ph.idx} ME — {ph.main_effort_bn} axis to OBJ {ph.obj_name}"))
    items.append(tg("ATK_AXIS", *aa.bearing_m(WEST, 4_000).as_pair(),
                    echelon="BN", rotation=NORTH,
                    notes=f"Φ{ph.idx} SE (W) — 2-21 PzBn screen LEFT flank"))
    items.append(tg("ATK_AXIS", *aa.bearing_m(EAST, 4_000).as_pair(),
                    echelon="BN", rotation=NORTH,
                    notes=f"Φ{ph.idx} SE (E) — 5-21 PzGrenBn screen RIGHT flank"))

    # 3. Reserve + CT-ATK
    items.append(tg("DEF_AREA", *centre.bearing_m(SOUTH, 3_500).as_pair(),
                    echelon="BN", rotation=NORTH,
                    notes=f"Φ{ph.idx} BDE RES — 3-21 PzBn consolidation BP"))
    items.append(tg("COUNTERATTACK",
                    *centre.bearing_m(SOUTH, 4_500).bearing_m(EAST, 1_500).as_pair(),
                    echelon="BN", rotation=NORTH,
                    notes=f"Φ{ph.idx} CT-ATK — 3-21 PzBn east flank on order"))

    # 4. Phase line (LOA for this phase)
    pl = centre.bearing_m(NORTH, 2_500)
    items.append(line("PHASE_LINE", [pl.bearing_m(WEST, 12_000), pl.bearing_m(EAST, 12_000)]))
    items[-1]["echelon"] = "BDE"
    items[-1]["notes"]   = f"PL {ph.obj_name} — Φ{ph.idx} limit of advance"

    # 5. BDE boundaries — only emitted on Φ1 (they span the whole AO)
    if ph.idx == 1:
        items.append(line("BOUNDARY", [
            LatLon(LD_CENTRE.lat - 0.1, LEFT_BOUNDARY_LON),
            LatLon(PHASES[-1].centre.lat + 0.2, LEFT_BOUNDARY_LON),
        ]))
        items[-1]["echelon"] = "BDE"
        items[-1]["notes"]   = "21 BDE / 22 BDE boundary — WEST"
        items.append(line("BOUNDARY", [
            LatLon(LD_CENTRE.lat - 0.1, RIGHT_BOUNDARY_LON),
            LatLon(PHASES[-1].centre.lat + 0.2, RIGHT_BOUNDARY_LON),
        ]))
        items[-1]["echelon"] = "BDE"
        items[-1]["notes"]   = "21 BDE / 23 BDE boundary — EAST"

    # 6. Enemy FLET line
    flet_e = centre.bearing_m(SOUTH, 800).bearing_m(EAST, 4_500)
    flet_w = centre.bearing_m(SOUTH, 800).bearing_m(WEST, 4_500)
    items.append(line("FLET", [flet_w, flet_e]))
    items[-1]["affiliation"] = "ENEMY"
    items[-1]["echelon"]     = "BDE"
    items[-1]["notes"]       = f"FLET — 36 GuMRB forward defence S of {ph.city}"

    # 7. Enemy ORBAT
    enemy = [
        ("Enemy tank coy (T-90M)",            "SHGPUCAA----", centre.offset_m(  200,  -300)),
        ("Enemy motor rifle coy (BMP-3)",     "SHGPUCIM----", centre.offset_m( -150,   400)),
        ("Enemy motor rifle coy (BTR-82A)",   "SHGPUCIZ----", centre.offset_m(  350,   600)),
        ("Enemy SP arty btry (2S19 Msta)",    "SHGPUCFHE---", centre.offset_m(-1_200,  -700)),
        ("Enemy MLRS section (BM-21)",        "SHGPUCFHM---", centre.offset_m(-1_400,   500)),
        ("Enemy AT plt (Kornet/Khrizantema)", "SHGPUCAA---F", centre.offset_m(  500,  -150)),
        ("Enemy AD plt (Strela-10 / Tor)",    "SHGPUCDS----", centre.offset_m( -200, -1_000)),
        ("Enemy recce plt (BRM-1K)",          "SHGPUCRR----", centre.offset_m( 1_200,   800)),
        ("Enemy engr coy",                    "SHGPUCEN----", centre.offset_m( -800,   200)),
        ("Enemy EW det (Borisoglebsk-2)",     "SHGPUUS-----", centre.offset_m(-1_000,   900)),
    ]
    for desc, sidc, ll in enemy:
        items.append({"type": "ENEMY", "symbol_code": sidc,
                      "latitude": ll.lat, "longitude": ll.lon,
                      "affiliation": "ENEMY",
                      "notes": f"36 GuMRB · {desc} · {ph.city}",
                      "echelon": "", "rotation": 0.0, "geometry": "",
                      "visibility": "COMPANY"})
    # Enemy prepared MRB DEF_AREA
    enemy_pos = [centre.offset_m( 600, -1_400), centre.offset_m( 600,  1_400),
                 centre.offset_m(-600,  1_400), centre.offset_m(-600, -1_400)]
    items.append(poly("DEF_AREA", enemy_pos,
                      affiliation="ENEMY", echelon="BN", rotation=NORTH,
                      notes=f"36 GuMRB · prepared MRB BP IVO {ph.city}"))
    items.append(tg("AMBUSH", *centre.bearing_m(SOUTH, 6_000).as_pair(),
                    affiliation="ENEMY", echelon="COY", rotation=NORTH,
                    notes=f"Suspected EN ambush on BDE axis S of {ph.city}"))

    # 8. Friendly POIs — BSA, TOC, Role 2, fuel, ammo, MEDEVAC, arty, AD
    bsa = centre.bearing_m(SOUTH, 6_000)
    pois = [
        ("21 BDE TOC",                "SFGPUH------", aa.bearing_m(SOUTH, 1_500)),
        ("21 Sig Coy CIS node",       "SFGPUUS-----", aa.bearing_m(SOUTH, 1_400).bearing_m(WEST, 300)),
        ("21 Med Coy Role 2 LM",      "SFGPIMS-----", bsa.bearing_m(WEST, 600)),
        ("21 Log Bn — fuel point",    "SFGPIRP-----", bsa.bearing_m(EAST, 600)),
        ("21 Log Bn — ammo point",    "SFGPIRP-----", bsa.bearing_m(EAST, 900)),
        ("MEDEVAC LZ ALPHA",          "SFGPIBA-----", bsa.bearing_m(WEST, 900)),
        ("21 Arty Bn PA1 (PzH 2000)", "SFGPUCFHE---", bsa.bearing_m(EAST, 1_400)),
        ("21 Arty Bn PA2 (MARS II)",  "SFGPUCFHM---", bsa.bearing_m(WEST, 1_400)),
        ("21 AD Coy (IRIS-T SLM)",    "SFGPUCDS----", bsa.bearing_m(NORTH, 600)),
    ]
    for desc, sidc, ll in pois:
        items.append({"type": "POI", "symbol_code": sidc,
                      "latitude": ll.lat, "longitude": ll.lon,
                      "affiliation": "FRIENDLY",
                      "notes": f"21 BDE · {desc} · Φ{ph.idx} {ph.obj_name}",
                      "echelon": "", "rotation": 0.0, "geometry": "",
                      "visibility": "COMPANY"})

    if ph.waterway:
        items.append(tg("POI", *centre.bearing_m(SOUTH, 400).as_pair(),
                        symbol_code="SFGPUCEN----", affiliation="FRIENDLY",
                        echelon="COY",
                        notes=f"21 Engr Bn · bridging set ({ph.waterway}) · Φ{ph.idx}"))

    return items


# ── Brigade OPORD ──────────────────────────────────────────────────────────
def build_opord() -> dict:
    return dict(
        title="OPORD 26-NW-01 — OPERATION NORTH WIND",
        opord_number="OPORD 26-NW-01",
        dtg="010500ZJUN26",
        classification="UNCLASSIFIED//FOUO  ·  EXERCISE",
        references=(
            "a. Map: NL TOP50 1:50.000 sheets 51/52/57/16/15/11/06 (WGS-84)\n"
            "b. NATO LANDOPS doctrine — ATP-3.2.1, AJP-3.2 ed C v1\n"
            "c. Div OPORD 26-04 (Op NORTHERN GUARD)\n"
            "d. BDE STANDING SOP 21-1 (Movement & Manoeuvre)\n"
            "e. Annex Q — Engineer plan (Waal/Nederrijn/IJssel bridging)"
        ),
        task_organization=(
            "21 PANZER BRIGADE (DEU/NLD multinational) — ENABLING TASK 1 NORTH WIND\n"
            "  HHC, 21 BDE\n"
            "  1-21 Panzer Bn (Leo 2A7)     — ME on selected phases\n"
            "  2-21 Panzer Bn (Leo 2A7)     — Flank security (W) / SE Φ5, Φ7\n"
            "  3-21 Panzer Bn (Leo 2A7)     — RES; CT-ATK on order\n"
            "  4-21 PzGren Bn (Puma)        — ME urban (Φ1, Φ3, Φ8)\n"
            "  5-21 PzGren Bn (Marder)      — Flank security (E); ME Φ6\n"
            "  21 Recce Bn (Fennek/CV90)    — 30 km forward screen\n"
            "  21 Arty Bn (PzH 2000×16, MARS II×4) — DS to BDE\n"
            "  21 Engr Bn (bridging) — Waal/Nederrijn/IJssel\n"
            "  21 AD Coy (IRIS-T SLM) — GS BDE\n"
            "  21 Log Bn · 21 Med Coy (Role 2 LM) · 21 Sig Coy\n"
            "ATTACHMENTS: UAS section (Heron-TP) · CIMIC TM · SOTG LO (KCT)\n"
            "DETACHMENTS: nil"
        ),
        situation={
            "terrain": (
                "360 km central NL corridor, Lommel (BE/NL) → Dokkum (Friesland). "
                "OAKOC: open polders + farmland; long sight lines outside cities. "
                "Avenues of approach: A2/A50/A28 motorways. Key terrain: Waal "
                "(Nijmegen), Nederrijn (Arnhem), IJssel (Zwolle) — three obligate "
                "crossings; Veluwe forest restricts off-road armour."
            ),
            "weather": (
                "BMNT 0345 / Sunrise 0521 / Sunset 2202 / EENT 2338 (June, NLD). "
                "Illum 65%, set 0148. Temp 12–24°C. Wind W 8–15 kt. "
                "Visibility >10 km. Soil trafficability AMBER polders, GREEN motorways."
            ),
            "enemy_cds": (
                "36 GUARDS MOTOR RIFLE BRIGADE defends in depth. "
                "ORBAT: 2× Tank Bn (T-90M), 2× MRB (BMP-3/BTR-82A), Recce (BRM-1K), "
                "SP Arty (2S19×18), MLRS (BM-21×6), AD (Strela-10/Tor-M2), "
                "AT (Kornet/Khrizantema), EW (Borisoglebsk-2/Pole-21). "
                "Strength ~80%, morale MEDIUM."
            ),
            "enemy_mlcoa": (
                "Forward MRB IVO Eindhoven/Den Bosch slows BDE; main defensive belt "
                "along Nederrijn (Arnhem); ATGM ambushes A50; reserve tank Bn CT-ATKs "
                "across IJssel into Φ5/Φ6. EW degrades BDE comms 0–80 km from FLET."
            ),
            "enemy_mdcoa": (
                "Spoiling attack from Apeldoorn into Φ3/Φ4 at H+24 with 1× Tank Bn "
                "(+ MR Coy) to disrupt Waal/Nederrijn crossings; massed BM-21 fires "
                "on BDE BSA south of Den Bosch."
            ),
            "civil": (
                "Dense populace: Eindhoven 240k, Arnhem 160k, Zwolle 130k. NEO routes "
                "pre-cleared by KMar. NO-STRIKE: Φ4 grid interconnect, Φ5 hospital ZGT, "
                "all bridges + heritage."
            ),
            "friendly_higher": (
                "21 BDE is DIV main effort. 22 BDE (W coastal) and 23 BDE (E Twente) "
                "advance abreast. CAS by DEU/NLD F-35A + AH-64E; SEAD by USAFE."
            ),
            "friendly_adjacent": (
                "22 BDE WEST boundary 5.0°E; 23 BDE EAST boundary 6.3°E. "
                "LO exchange H-12; DIV TAC coord at H+0."
            ),
        },
        mission=(
            "21 BDE attacks 010500ZJUN26 along Axis NORTH to seize OBJs ANVIL, HAMMER, "
            "BRIDGE, ARROW, SHIELD, DAGGER, EAGLE and NORTH in succession in order to "
            "destroy 36 GuMRB, secure Waal/Nederrijn/IJssel crossings, and link up with "
            "host-nation reserves IVO Dokkum NLT 050000ZJUN26."
        ),
        execution={
            "intent_purpose": (
                "Eject 36 GuMRB from the central NLD corridor and re-establish host-nation "
                "control from BE/NL border to the Wadden coast within 4 days."
            ),
            "intent_key_tasks": (
                "1) Seize 3× river crossings intact or repaired.\n"
                "2) Destroy enemy tank Bn(s) on the brigade axis.\n"
                "3) Protect Φ4 grid interconnect & Φ5 hospital (NO-STRIKE).\n"
                "4) BSA established within 4 hr of each LOA.\n"
                "5) Hand over OBJ NORTH to host-nation 13 LMB NLT H+96."
            ),
            "intent_end_state": (
                "36 GuMRB defeated or withdrawn N of Wadden. 21 BDE ≥70% combat power. "
                "All bridges secured. Civilian populace re-enabled in liberated cities."
            ),
            "conops_maneuver": (
                "8-phase brigade attack along Axis NORTH.\n"
                "Φ1 ANVIL  — cross LD Lommel; seize Eindhoven, secure A2 IVC.\n"
                "Φ2 HAMMER — bound to 's-Hertogenbosch; UAS recce N.\n"
                "Φ3 BRIDGE — seize Waal at Nijmegen; SOTG DA on bridge H-1.\n"
                "Φ4 ARROW  — cross Nederrijn at Arnhem; protect grid.\n"
                "Φ5 SHIELD — clear Veluwe; destroy EN reserve vic Apeldoorn.\n"
                "Φ6 DAGGER — cross IJssel at Zwolle (RABM ribbon bridge).\n"
                "Φ7 EAGLE  — exploit N to Heerenveen; passage of lines 13 LMB.\n"
                "Φ8 NORTH  — seize Dokkum; HOTO."
            ),
            "conops_fires": (
                "Priority: ME each phase. SEAD by air component Φ3–Φ6. "
                "FSCMs: FSCL = current PL. NO-STRIKE = Φ4 grid, Φ5 hospital, heritage."
            ),
            "conops_main_effort": (
                "ME shifts by phase: PzGrenBn for urban (Φ1, Φ3, Φ4, Φ8); "
                "PzBn for open exploitation (Φ2, Φ5, Φ7); PzGren Φ6 IJssel."
            ),
            "conops_phasing": "PREP → LD → Φ1 → Φ2 → … → Φ8 → CONSOLIDATE / HOTO",
            "tasks": (
                "1-21 PzBn: ME Φ2, Φ4. SE Φ1, Φ8.\n"
                "2-21 PzBn: ME Φ5, Φ7. Flank screen W all phases.\n"
                "3-21 PzBn: BDE RES; CT-ATK on order.\n"
                "4-21 PzGren Bn: ME Φ1, Φ3, Φ8.\n"
                "5-21 PzGren Bn: ME Φ6. Flank screen E all phases.\n"
                "21 Recce Bn: 30 km screen forward.\n"
                "21 Arty Bn: GS to ME each phase.\n"
                "21 Engr Bn: Φ3/Φ4/Φ6 bridging.\n"
                "21 AD Coy: protect BSA + bridging sites."
            ),
            "coord_timings": (
                "H-72 OPORD issue. H-48 ROC drill. H-24 LO exchange. H-12 Recce fwd. "
                "H-1 SOTG DA Φ3. H+0 (010500ZJUN26) BDE crosses LD. "
                "H+24 Φ3 BRIDGE seized. H+48 Φ5 consolidated. H+96 NLT HOTO Dokkum."
            ),
            "coord_ccir": (
                "PIR: 1) EN tank Bn reserve location. 2) Bridge demo prep. 3) EW emissions.\n"
                "FFIR: 1) BN combat power <60%. 2) Loss of crossing site. 3) Comms >20 min."
            ),
            "coord_roe": "AJP-3.4. Hostile act/intent. PID before engagement. NO-STRIKE briefed.",
            "coord_risk": (
                "HIGH (urban + crossings + EW). Controls: redundant comms (VHF/HF/SATCOM/"
                "Starlink mil); primary+alt bridging; pre-positioned Role 2 every BSA."
            ),
            "coord_fscm": (
                "FSCL bounded by current LOA. CFL = prior PL until 5-21 PzGrenBn confirms "
                "passage. NFA = cleared host-nation built-up. RFA = bridging + BSAs. "
                "NO-STRIKE = Φ4 grid, Φ5 hospital, heritage."
            ),
        },
        sustainment={
            "supply": "I/III/V topped at H-12 in BDE BSA south of Lommel. Class IIIB ~180 m³/day.",
            "transport": "21 Log Bn: 60× HX2, 12× MULTI, 24× M1014. Host-nation rail past Φ4.",
            "maintenance": "UMCP per BSA. Critical parts Leo 2A7 / Puma airlifted via Welschap.",
            "personnel": "Daily SITREP; AAR per phase. Replacement pool 60 PAX at DIV BSA.",
            "epw": "Detainee CCP each BSA; HOTO to KMar within 12 hr. Biometric enrolment (HIIDE).",
            "casevac": "CCP each BSA. Air MEDEVAC NLD NH90×4 from BDE TOC. Ground M1133 MEV.",
            "medevac": "Role 2 LM per BSA. Role 2E Eindhoven Welschap. Role 3 Radboudumc, UMCG.",
        },
        command_signal={
            "command": "CDR at TAC w/ ME each phase. DCO at Main south of current BSA.",
            "succession": "BDE CDR → DCO → S3 → 1-21 CO → 4-21 CO → 2-21 CO.",
            "control": "SITREP/60 min; immediate on contact > coy; bridge status/15 min during crossings.",
            "pace_primary":     "VHF SINCGARS (BOWMAN/SOTAS) — BDE CMD 38.250 / FH-D",
            "pace_alternate":   "HF ALE — 4.825 MHz / 7.225 MHz day",
            "pace_contingency": "SATCOM TACSAT CH 104 (BDE) / CH 108 (ME)",
            "pace_emergency":   "Starlink Mil dish at TOC + dispatch riders + IR strobes",
            "callsigns": (
                "BLACK 6 (BDE CDR), STEEL (1-21), IRON (2-21), BRONZE (3-21/RES), "
                "WOLF (4-21), LYNX (5-21), HAWK (Recce), THOR (Arty), "
                "PIONEER (Engr), SHIELD (AD), MULE (Log), DUSTOFF (Med)."
            ),
            "password": "Challenge: NORTHWIND / Reply: DOKKUM / Running: WADDEN",
        },
    )


def opord_snapshots() -> list[tuple[str, list[float], int, str]]:
    out: list[tuple[str, list[float], int, str]] = []
    out.append(("Brigade overview — Lommel → Dokkum",
                [51.10, 4.80, 53.45, 6.40], 8,
                "Brigade axis runs S→N along central corridor; 22 BDE west, 23 BDE east."))
    for ph in PHASES:
        bbox = [ph.centre.lat - 0.10, ph.centre.lon - 0.18,
                ph.centre.lat + 0.10, ph.centre.lon + 0.18]
        ann = (f"Φ{ph.idx} OBJ {ph.obj_name} — {ph.city}. ME: {ph.main_effort_bn}. "
               + (f"Waterway: {ph.waterway}." if ph.waterway else "No waterway."))
        out.append((f"Φ{ph.idx} OBJ {ph.obj_name} — {ph.city}", bbox, 12, ann))
    return out


# ── Live-phase: brigade operators that walk the axis ────────────────────────
SIM_PASSWORD = "Arrow2525!"

@dataclass
class SimOp:
    callsign: str
    rank: str
    role: str               # ADMIN / BATTLE_CAPTAIN / OPERATOR
    # Where this operator sits relative to the active phase centre, in metres.
    # E.g. (-1500, 0) = 1.5 km south of OBJ centre; (+500, +800) = right-fwd.
    offset_n: float
    offset_e: float
    # Optional fixed home location for static elements (Arty Bn, etc.)
    home: Optional[LatLon] = None
    token: str = ""
    op_id: int = 0
    lat: float = 0.0
    lon: float = 0.0

def _brigade_orbat() -> list[SimOp]:
    """Brigade-level operators visible on the map."""
    return [
        # BDE CDR
        SimOp("BLACK-6",  "OF-6", "ADMIN",          offset_n= -1_400, offset_e=    0),
        # Brigade staff
        SimOp("BLACK-3",  "OF-4", "BATTLE_CAPTAIN", offset_n= -1_500, offset_e=  150),  # S3
        SimOp("BLACK-2",  "OF-4", "BATTLE_CAPTAIN", offset_n= -1_500, offset_e= -150),  # S2
        # Battalion COs
        SimOp("STEEL-6",   "OF-4", "BATTLE_CAPTAIN", offset_n=  -200, offset_e=    0),  # 1-21 PzBn
        SimOp("IRON-6",    "OF-4", "BATTLE_CAPTAIN", offset_n=  -300, offset_e= -3_500), # 2-21 PzBn W
        SimOp("BRONZE-6",  "OF-4", "BATTLE_CAPTAIN", offset_n= -3_500, offset_e=    0),  # 3-21 PzBn RES
        SimOp("WOLF-6",    "OF-4", "BATTLE_CAPTAIN", offset_n=  -150, offset_e=  200),   # 4-21 PzGrenBn
        SimOp("LYNX-6",    "OF-4", "BATTLE_CAPTAIN", offset_n=  -300, offset_e= 3_500),  # 5-21 PzGrenBn E
        SimOp("THOR-6",    "OF-4", "BATTLE_CAPTAIN", offset_n= -5_500, offset_e= 1_400), # Arty Bn @ BSA
        SimOp("PIONEER-6", "OF-3", "BATTLE_CAPTAIN", offset_n=  -800, offset_e=    0),   # Engr Bn
        SimOp("SHIELD-6",  "OF-3", "BATTLE_CAPTAIN", offset_n= -5_400, offset_e=    0),  # AD Coy @ BSA
        SimOp("DUSTOFF-6", "OF-3", "BATTLE_CAPTAIN", offset_n= -6_000, offset_e=  -600), # Med Coy
        SimOp("MULE-6",    "OF-3", "BATTLE_CAPTAIN", offset_n= -6_000, offset_e=   600), # Log Bn
        # Recce teams — push ~10 km forward of OBJ
        SimOp("HAWK-21",   "OR-7", "OPERATOR",       offset_n= 9_000, offset_e=  -800),
        SimOp("HAWK-22",   "OR-7", "OPERATOR",       offset_n= 9_500, offset_e=    0),
        SimOp("HAWK-23",   "OR-7", "OPERATOR",       offset_n= 9_000, offset_e=   800),
    ]


async def register_or_login(client: httpx.AsyncClient, admin_token: str, op: SimOp) -> None:
    tok = await login(client, op.callsign, SIM_PASSWORD)
    if tok:
        op.token = tok
        return
    r = await api(client, "POST", "/auth/register/admin", token=admin_token, json={
        "callsign": op.callsign, "password": SIM_PASSWORD,
        "rank": op.rank, "role": op.role,
    })
    if r and r.get("access_token"):
        op.token = r["access_token"]
        log.info("  registered %-12s (%s)", op.callsign, op.role)
    else:
        # Last resort — try plain login again in case the account existed
        # but seed admin couldn't list it (race / cache).
        tok = await login(client, op.callsign, SIM_PASSWORD)
        if tok:
            op.token = tok


async def position_for_phase(op: SimOp, ph: Phase) -> tuple[float, float]:
    """Where this operator sits at the given phase (centre + offset, jittered)."""
    base = ph.centre.offset_m(op.offset_n, op.offset_e)
    jit_n = random.gauss(0, 35)
    jit_e = random.gauss(0, 35)
    spot = base.offset_m(jit_n, jit_e)
    return spot.lat, spot.lon


# A reasonable mech-infantry advance pace, accelerated by --speed.
PHASE_SECONDS = 30.0      # real seconds per phase at speed=1 (becomes 1.5 s at speed=20)
TICK_SECONDS  = 2.0       # real seconds between position pushes at speed=1
WALK_MS       = 9_000 / 3_600   # ~9 km/h advance pace (averaged over road + cross-country)


async def drive_operator(client: httpx.AsyncClient, op: SimOp,
                         phase_idx_state: dict, speed: float) -> None:
    """One operator coroutine — keeps stepping toward the current phase centre.

    Never returns: when phase_idx wraps (looping) the operator just keeps
    chasing the new target. If the position POST fails we log and retry on
    the next tick rather than dying silently.
    """
    if not op.token:
        return
    # Seed at the LD area (phase 0 = south of Φ1)
    spot = LD_CENTRE.offset_m(op.offset_n, op.offset_e)
    op.lat, op.lon = spot.lat, spot.lon
    real_tick = max(0.05, TICK_SECONDS / speed)
    while True:
        idx = max(0, min(len(PHASES) - 1, phase_idx_state["idx"]))
        ph = PHASES[idx]
        tlat, tlon = await position_for_phase(op, ph)
        sim_dt = real_tick * speed
        op.lat, op.lon = step_towards(op.lat, op.lon, tlat, tlon, WALK_MS, sim_dt)
        await api(client, "POST", "/tracking/position", token=op.token, json={
            "latitude": op.lat, "longitude": op.lon, "altitude": 12.0,
        })
        await asyncio.sleep(real_tick)


async def advance_phase_clock(phase_idx_state: dict, speed: float,
                              loop: bool) -> None:
    """Bump the active phase every PHASE_SECONDS / speed real seconds.

    When ``loop`` is True (default), wraps Φ8 → Φ1 and keeps running so the
    map keeps animating until Ctrl-C. When False, stops after Φ8.
    """
    interval = max(0.5, PHASE_SECONDS / speed)
    while True:
        await asyncio.sleep(interval)
        nxt = phase_idx_state["idx"] + 1
        if nxt >= len(PHASES):
            if not loop:
                phase_idx_state["idx"] = len(PHASES)   # signals "done"
                log.info("🏁 Brigade reached OBJ NORTH (Dokkum). Operators idle at LOA.")
                return
            log.info("🔁 LOOPING — brigade re-seeds at Lommel (Φ1 ANVIL).")
            phase_idx_state["idx"] = 0
        else:
            phase_idx_state["idx"] = nxt
        ph = PHASES[phase_idx_state["idx"]]
        log.info("📍 PHASE ADVANCE — Φ%d %s (%s)", ph.idx, ph.obj_name, ph.city)


# Simple MGRS converter — duplicated from simulate.py so this script stays standalone.
def mgrs(lat: float, lon: float, acc: int = 5) -> str:
    return f"{lat:.4f},{lon:.4f}"   # plain decimal as a tactical placeholder


CONTACT_TEMPLATES = [
    ("Enemy mech infantry section spotted",  "ENEMY", "SHGPUCIM----"),
    ("Enemy tank section (T-90)",            "ENEMY", "SHGPUCAA----"),
    ("Enemy ATGM team",                      "ENEMY", "SHGPUCAA---F"),
    ("Suspected enemy artillery",            "ENEMY", "SHGPUCFHE---"),
    ("UAV overhead",                         "ENEMY", "SHAPMFA-----"),
    ("Civilian convoy crossing axis",        "POI",   "SNGPI-------"),
    ("Demolished bridge / obstacle",         "POI",   "SFGPGPRD----"),
    ("Linkup with host-nation patrol",       "POI",   "SFGPUH------"),
]


def _live_recce_or_any(ops: list[SimOp]) -> Optional[SimOp]:
    recce = [o for o in ops if o.callsign.startswith("HAWK-2") and o.token and o.lat]
    live  = [o for o in ops if o.token and o.lat]
    return random.choice(recce) if recce else (random.choice(live) if live else None)


async def inject_contacts(client: httpx.AsyncClient, ops: list[SimOp],
                          speed: float) -> None:
    """Drop a fresh enemy/POI tactical object every ~10s + a chat broadcast."""
    interval = max(2.0, 10.0 / speed)
    await asyncio.sleep(interval * 0.4)
    n = 0
    while True:
        await asyncio.sleep(interval)
        op = _live_recce_or_any(ops)
        if not op:
            continue
        desc, type_, sidc = random.choice(CONTACT_TEMPLATES)
        spread = random.uniform(200, 500)
        clat = op.lat + spread * LAT_DEG_PER_M
        clon = op.lon + random.uniform(-150, 150) * lon_deg_per_m(op.lat)
        grid = mgrs(clat, clon)
        n += 1
        r = await api(client, "POST", "/tactical-objects", token=op.token, json={
            "type": type_, "symbol_code": sidc,
            "latitude": round(clat, 6), "longitude": round(clon, 6),
            "affiliation": "ENEMY" if type_ == "ENEMY" else "FRIENDLY",
            "notes": f"{desc} · {grid}",
            "echelon": "", "rotation": 0.0, "geometry": "",
            "visibility": "COMPANY",
        })
        if r:
            log.info("⚠️  %s marks: %s @ %s (#%d)", op.callsign, desc, grid, n)
        await api(client, "POST", "/messages", token=op.token, json={
            "content": f"CONTACT — {desc}, grid {grid}",
            "message_type": "BROADCAST",
        })


async def inject_spot_reports(client: httpx.AsyncClient, ops: list[SimOp],
                              speed: float) -> None:
    """Periodic SPOT report — appears in /reports + the report layer on map."""
    interval = max(3.0, 18.0 / speed)
    await asyncio.sleep(interval * 0.7)
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    n = 0
    while True:
        await asyncio.sleep(interval)
        op = _live_recce_or_any(ops)
        if not op:
            continue
        grid = mgrs(op.lat, op.lon)
        payload = {
            "size":     random.choice(["squad", "section", "platoon", "company"]),
            "activity": random.choice([
                "DEFENDING from prepared positions",
                "MOVING NORTH on motorway",
                "DUG IN with armoured support",
                "HASTY DEFENCE at road junction",
                "WITHDRAWING under fire",
            ]),
            "location":     grid,
            "unit":         random.choice(["motor rifle", "tank", "recce", "arty"]),
            "time":         "current",
            "equipment":    random.choice(["T-90M", "BMP-3", "BTR-82A", "2S19", "BM-21"]),
            "direction":    random.choice(directions),
            "distance":     random.choice([200, 400, 800, 1200, 1600]),
            "description":  "Spot report from forward element",
        }
        r = await api(client, "POST", "/reports", token=op.token, json={
            "type": "SPOT", "payload": payload,
        })
        if r:
            n += 1
            log.info("📋 %s SPOT %s/%s — %s",
                     op.callsign, payload["size"], payload["unit"], grid)


async def inject_fire_missions(client: httpx.AsyncClient, ops: list[SimOp],
                               speed: float) -> None:
    """Periodic call-for-fire from a recce observer — appears as a fire-mission."""
    interval = max(4.0, 25.0 / speed)
    await asyncio.sleep(interval * 0.5)
    n = 0
    while True:
        await asyncio.sleep(interval)
        op = _live_recce_or_any(ops)
        if not op:
            continue
        # Target 600–1500 m ahead of the observer, in the direction of advance.
        dist = random.uniform(600, 1500)
        brg  = random.uniform(330, 30)        # roughly N ±30°
        tlat = op.lat + dist * math.cos(math.radians(brg)) * LAT_DEG_PER_M
        tlon = op.lon + dist * math.sin(math.radians(brg)) * lon_deg_per_m(op.lat)
        payload = {
            "latitude":  round(tlat, 6),
            "longitude": round(tlon, 6),
            "altitude":  0.0,
            "direction": round(brg, 1),
            "mission_type": random.choice(["ADJUST_FIRE", "FIRE_FOR_EFFECT",
                                           "SUPPRESSION", "ILLUMINATION"]),
            "ammunition":   random.choice(["HE", "ICM", "SMOKE", "ILLUM"]),
            "quantity":     random.choice([1, 3, 6, 12]),
            "description":  f"{op.callsign} — observed enemy element, request fire",
        }
        r = await api(client, "POST", "/fire-missions", token=op.token, json=payload)
        if r:
            n += 1
            log.info("🎯 %s CFF %s × %d %s @ %.4f,%.4f (#%d)",
                     op.callsign, payload["ammunition"], payload["quantity"],
                     payload["mission_type"], tlat, tlon, n)


async def inject_tic_alerts(client: httpx.AsyncClient, ops: list[SimOp],
                            speed: float) -> None:
    """Rare TIC alert — every ~45s real. Triggers the alert pulse on every client."""
    interval = max(8.0, 45.0 / speed)
    await asyncio.sleep(interval * 0.8)
    n = 0
    while True:
        await asyncio.sleep(interval)
        op = _live_recce_or_any(ops)
        if not op:
            continue
        type_ = random.choices(
            ["TIC", "MEDICAL", "EVAC", "LOST_COMMS"],
            weights=[6, 2, 1, 1])[0]
        r = await api(client, "POST", "/alerts", token=op.token, json={
            "type": type_,
            "latitude":  round(op.lat, 6),
            "longitude": round(op.lon, 6),
        })
        if r:
            n += 1
            log.info("🚨 %s ALERT %s @ %.4f,%.4f (#%d)",
                     op.callsign, type_, op.lat, op.lon, n)


async def reset_world(client: httpx.AsyncClient,
                      admin_token: str) -> tuple[int, int, int, int]:
    """Delete tactical objects, NORTH WIND OPORDs, saved overlays, sim operators.

    Saved overlays MUST be wiped too: any operator with one still active in
    their localStorage filter will see an empty map (the filter set becomes
    the union of now-deleted ids → matches nothing → nothing renders). Same
    for KML layers — a layer with stale member objects can mask the plant.
    """
    n_obj = 0
    for o in (await api(client, "GET", "/tactical-objects", token=admin_token) or []):
        if o.get("type") in (ALL_TG_TYPES | NON_TG_TYPES):
            r = await api(client, "DELETE", f"/tactical-objects/{o['id']}", token=admin_token)
            if r is not None:
                n_obj += 1
    n_op = 0
    for o in (await api(client, "GET", "/opords", token=admin_token) or []):
        title = o.get("title") if isinstance(o, dict) else None
        opnum = o.get("opord_number") if isinstance(o, dict) else None
        if (title and "NORTH WIND" in title) or (opnum and opnum.startswith("OPORD 26-NW")):
            r = await api(client, "DELETE", f"/opords/{o['id']}", token=admin_token)
            if r is not None:
                n_op += 1
    n_ov = 0
    for ov in (await api(client, "GET", "/overlays", token=admin_token) or []):
        if isinstance(ov, dict) and "id" in ov:
            r = await api(client, "DELETE", f"/overlays/{ov['id']}", token=admin_token)
            if r is not None:
                n_ov += 1
    sim_callsigns = {o.callsign for o in _brigade_orbat()}
    n_users = 0
    for op in (await api(client, "GET", "/operators", token=admin_token) or []):
        if (isinstance(op, dict) and op.get("callsign") in sim_callsigns
                and op.get("callsign") != ARGS.admin):
            r = await api(client, "DELETE", f"/operators/{op['id']}", token=admin_token)
            if r is not None:
                n_users += 1
    return n_obj, n_op, n_ov, n_users


# ── Main async driver ──────────────────────────────────────────────────────
async def amain() -> None:
    log.info("Backend: %s   (path prefix: %r)", BASE, PATH_PREFIX or "<none>")
    async with httpx.AsyncClient(base_url=ORIGIN, timeout=20.0) as client:
        # Pre-flight reachability check — a quick GET /health (or the prefixed
        # equivalent) tells us in under 5 seconds whether the host / port is
        # wrong, before we waste 15s on the auth-form timeout.
        try:
            health = await client.get(_p("/health"), timeout=5)
            log.info("Health check → HTTP %d", health.status_code)
        except httpx.ConnectError as exc:
            sys.exit(f"❌  Cannot reach {BASE}\n"
                     f"   ConnectError: {exc or '(no detail)'}\n"
                     f"   Check the IP / port — common typo: 78.21.255.21 vs "
                     f"78.21.255.210. Also confirm the backend is running and "
                     f"the path prefix is correct (currently '{PATH_PREFIX or '<none>'}').")
        except httpx.ConnectTimeout:
            sys.exit(f"❌  Cannot reach {BASE} — connect timed out after 5s.\n"
                     f"   Port {urlsplit(BASE).netloc.rsplit(':', 1)[-1]} firewalled "
                     f"or the host is offline.")
        except httpx.HTTPError as exc:
            log.warning("Health check failed: %s: %s — continuing anyway.",
                        type(exc).__name__, exc or "(no detail)")

        log.info("Logging in as seed admin %s …", ARGS.admin)
        admin_token = await login(client, ARGS.admin, ARGS.password)
        if not admin_token:
            sys.exit(f"❌  login failed for {ARGS.admin}.\n"
                     f"   Backend URL : {BASE}\n"
                     f"   Most common causes:\n"
                     f"     • Wrong --backend URL (typo in IP/port/path prefix)\n"
                     f"     • Admin password not 'ranger14' (use --password)\n"
                     f"     • Admin account has MFA enabled — disable it or use "
                     f"another ADMIN with --admin <callsign>")
        sim_utils.save_backend(ARGS.backend)
        log.info("Authenticated.")
        global MISSION_ID
        MISSION_ID = await sim_utils.create_mission_async(
            client, BASE, admin_token, ARGS.mission_name,
            map_center_lat=52.2, map_center_lng=5.6, map_zoom=8)

        if ARGS.reset:
            n_obj, n_op, n_ov, n_users = await reset_world(client, admin_token)
            log.info("Reset: removed %d tactical objects · %d OPORDs · "
                     "%d overlays · %d sim operators.",
                     n_obj, n_op, n_ov, n_users)

        # ── Static plant ───────────────────────────────────────────────────
        total_ok, total_all = 0, 0
        prev = LD_CENTRE
        for ph in PHASES:
            items = build_phase_objects(prev, ph,
                                        PHASES[ph.idx].centre if ph.idx < len(PHASES) else None)
            total_all += len(items)
            log.info("── Φ%d · OBJ %s · %s (%.4f, %.4f) — planting %d objects",
                     ph.idx, ph.obj_name, ph.city, ph.centre.lat, ph.centre.lon, len(items))
            # Plant concurrently per-phase but cap parallelism so we don't
            # drown the backend's rate-limiter on a fresh boot.
            sem = asyncio.Semaphore(8)
            async def _post(item):
                async with sem:
                    return await api(client, "POST", "/tactical-objects",
                                     token=admin_token, json=item)
            results = await asyncio.gather(*[_post(it) for it in items])
            ok = sum(1 for r in results if r)
            total_ok += ok
            log.info("   %d / %d planted", ok, len(items))
            prev = ph.centre

        # OPORD + snapshots
        op_payload = build_opord()
        op_resp = await api(client, "POST", "/opords", token=admin_token, json=op_payload)
        op_id = op_resp.get("id", -1) if op_resp else -1
        if op_id < 0:
            log.warning("OPORD creation failed — check the warning above for the HTTP body.")
        else:
            log.info("✓ OPORD created: id=%d  %s", op_id, op_payload["title"])
            if not ARGS.skip_snapshots:
                for label, bbox, zoom, ann in opord_snapshots():
                    r = await api(client, "POST",
                                  f"/opords/{op_id}/snapshots/render",
                                  token=admin_token, json={
                                      "label": label, "bbox": bbox,
                                      "zoom": zoom, "annotations": ann,
                                  })
                    log.info("   %s snapshot: %s", "✓" if r else "·", label)

        # Verification — round-trip what the server actually shows so the user
        # can confirm enemies + edges + OBJs really landed before live ops start.
        check_objs = await api(client, "GET", "/tactical-objects", token=admin_token) or []
        check_ops  = await api(client, "GET", "/opords",            token=admin_token) or []
        check_ovs  = await api(client, "GET", "/overlays",          token=admin_token) or []
        nw_opords  = [o for o in check_ops if isinstance(o, dict) and (
                      "NORTH WIND" in (o.get("title") or "")
                      or (o.get("opord_number") or "").startswith("OPORD 26-NW"))]

        from collections import Counter as _C
        by_type = _C(o.get("type") for o in check_objs if isinstance(o, dict))
        by_aff  = _C(o.get("affiliation") for o in check_objs if isinstance(o, dict))
        log.info("── Verify ─────────────────────────────────────────────────")
        log.info("   tactical objects on server : %d", len(check_objs))
        log.info("   by affiliation             : %s", dict(by_aff))
        log.info("   types present              : %s",
                 ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
        log.info("   NORTH WIND OPORDs          : %d  (id list: %s)",
                 len(nw_opords), [o.get("id") for o in nw_opords])
        log.info("   saved overlays on server   : %d", len(check_ovs))

        # If the user can't see enemies / edges / OBJ on their map but the
        # server shows them here, the problem is browser-side. Spell it out.
        if (by_type.get("ENEMY", 0) > 0 and by_type.get("OBJ_AREA", 0) > 0
                and by_type.get("BOUNDARY", 0) > 0):
            log.info("✓ Server confirms ENEMY (%d), OBJ_AREA (%d), BOUNDARY (%d) all "
                     "landed. If they're invisible on your map:",
                     by_type["ENEMY"], by_type["OBJ_AREA"], by_type["BOUNDARY"])
            log.info("   1) hard-refresh the web map (Cmd-Shift-R / Ctrl-Shift-R)")
            log.info("   2) untick any active filter in the 📚 Overlays panel")
            log.info("   3) chip strip → click \"🌐 All\" and \"📐 Tac Gfx\" (must be ON)")
            log.info("   4) pan to the central NL corridor: bbox ~[51.2, 5.0]–[53.4, 6.4]")
        else:
            log.warning("⚠ Plant is incomplete. Re-read the warnings above. "
                        "Common causes: --backend URL wrong (currently %s), seed admin "
                        "lacks ADMIN role, MFA enabled on seed admin, or backend rate "
                        "limit. Try: --backend http://YOUR-SERVER:6001 --reset", BASE)

        log.info("Static plant: %d / %d POSTs accepted across %d phases.",
                 total_ok, total_all, len(PHASES))

        if ARGS.no_live:
            log.info("--no-live: exiting without driving operators.")
            return

        # ── Live ops — register brigade operators and march them N ─────────
        log.info("── Registering brigade operators (%.0fx speed) ─────", ARGS.speed)
        sim_ops = _brigade_orbat()
        await asyncio.gather(*[register_or_login(client, admin_token, op) for op in sim_ops])
        active = [o for o in sim_ops if o.token]
        log.info("%d / %d brigade operators ready.", len(active), len(sim_ops))

        # Shared phase clock — drive_operator and generate_contacts both read it.
        phase_idx_state = {"idx": 0}
        log.info("📍 START — Φ1 ANVIL (%s)", PHASES[0].city)

        # All tasks run concurrently. Cancel-friendly on Ctrl-C.
        try:
            await asyncio.gather(
                advance_phase_clock(phase_idx_state, ARGS.speed, ARGS.loop),
                inject_contacts(client, active, ARGS.speed),
                inject_spot_reports(client, active, ARGS.speed),
                inject_fire_missions(client, active, ARGS.speed),
                inject_tic_alerts(client, active, ARGS.speed),
                *[drive_operator(client, op, phase_idx_state, ARGS.speed)
                  for op in active],
            )
        except (KeyboardInterrupt, asyncio.CancelledError):
            log.info("Interrupted — brigade operators frozen at last position.")


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
