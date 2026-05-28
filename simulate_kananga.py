#!/usr/bin/env python3
"""
Arrow Regiment Simulator — OPERATION IRON SKY
==============================================

Airborne seizure of Kananga (DRC) — regiment-level, 5 phases in real time.

Order of battle — 5ème Régiment Para-Commandos (5 RPC)
  REG HQ · 1 Para Bn (A/B/C Coy) · 2 Para Bn (reserve) · Weapons Coy (81 mm)
  Recce Tp · Sigs · Med Pl · Log Pl

Mission
  Seize KANANGA AIRFIELD (OBJ EAGLE) by airborne assault, then advance
  1 Coy to capture KANANGA TRAIN STATION (OBJ STATION), and consolidate
  in all-round defence at both objectives.

Phases
  Φ1 AMBER    — Airborne insertion; secure DZ NORTH of airfield
  Φ2 BRONZE   — Clear DZ, form up, advance to airfield perimeter
  Φ3 CRIMSON  — Assault OBJ EAGLE (airfield); 81 mm suppresses enemy positions
  Φ4 IRON     — C Coy advances and seizes OBJ STATION (train station)
  Φ5 GRANITE  — Consolidate; establish defence at EAGLE + STATION

Coordinates (real)
  Kananga Airport (FZUK):  -5.900 N,  22.368 E
  Kananga Train Station:   -5.895 N,  22.419 E
  DZ NORTH:                -5.870 N,  22.368 E
  81 mm Gun Line:          -5.875 N,  22.375 E

Run:
  uv run python simulate_kananga.py
  uv run python simulate_kananga.py --backend http://78.21.255.210:6001
  uv run python simulate_kananga.py --speed 30      # 30× real time
  uv run python simulate_kananga.py --no-move        # static plant only
  uv run python simulate_kananga.py --reset          # wipe all existing TGs / OPORDs
  uv run python simulate_kananga.py --steps 60 --dt 1.5
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

import httpx

import sim_utils

# ── CLI / persistent config ─────────────────────────────────────────────────
DEFAULT_BACKEND = (
    os.environ.get("ARROW_BACKEND_URL")
    or sim_utils.load_saved_backend()
    or "http://78.21.255.210:6200/api"
)

parser = argparse.ArgumentParser(description="Arrow regiment simulator — OPERATION IRON SKY (Kananga)")
parser.add_argument("--backend",  default=DEFAULT_BACKEND,
                    help=f"Backend base URL (default: {DEFAULT_BACKEND})")
parser.add_argument("--admin",    default="benoit",   help="Seed ADMIN callsign")
parser.add_argument("--password", default="ranger14", help="Seed ADMIN password")
parser.add_argument("--reset",    action="store_true",
                    help="Wipe all TGs / enemies / POIs / OPORDs / sim operators first")
parser.add_argument("--no-live",  action="store_true",
                    help="Plant the static OPORD + tactical objects then exit (no live operators)")
parser.add_argument("--no-move",  action="store_true", dest="no_live",
                    help="Alias for --no-live: plant plan only, skip movement simulation")
parser.add_argument("--speed",    type=float, default=None,
                    help="Phase time multiplier (default 2 — each phase ≈ 20 s). "
                         "Use 30 for a quick demo (≈ 3 s/phase).")
parser.add_argument("--steps",    type=int, default=None,
                    help="Movement steps. If given with --dt, derives speed (speed = TICK_SECONDS / dt) "
                         "and limits run to steps × dt real seconds.")
parser.add_argument("--dt",       type=float, default=None,
                    help="Seconds between steps. If given with --steps, derives speed and total duration.")
parser.add_argument("--once",     action="store_true",
                    help="Stop after Φ5 (no loop)")
parser.add_argument("--mission-name", default="Operation Iron Sky",
                    help="Mission name to create or adopt (default: Operation Iron Sky)")
ARGS = parser.parse_args()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("ks")

BASE = ARGS.backend.rstrip("/")
MISSION_ID: int | None = None

ORIGIN, PATH_PREFIX = sim_utils.split_base(BASE)


def _p(path: str) -> str:
    if not PATH_PREFIX or path.startswith(PATH_PREFIX + "/") or path == PATH_PREFIX:
        return path
    return PATH_PREFIX + path


# ── Tactical-graphic type sets ───────────────────────────────────────────────
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
        return LatLon(
            self.lat + north_m / 111_320.0,
            self.lon + east_m  / (111_320.0 * math.cos(math.radians(self.lat))),
        )

    def bearing_m(self, bearing_deg: float, distance_m: float) -> "LatLon":
        rad = math.radians(bearing_deg)
        return self.offset_m(distance_m * math.cos(rad), distance_m * math.sin(rad))

    def as_pair(self) -> list[float]:
        return [self.lat, self.lon]


# ── Key ground positions (real Kananga coordinates) ──────────────────────────
#
#   Kananga Airport (FZUK / KGA) — northern end of 1670 m runway 09/27
#   Train Station (Gare de Kananga) — south-east urban core
#   DZ NORTH — flat savannah 3 km north of runway threshold
#   81 mm GUN LINE — 2.5 km NNW, mask-angle clear to airfield + station
#
AIRFIELD      = LatLon(-5.900,  22.368)   # runway centre
AIRFIELD_N    = LatLon(-5.887,  22.368)   # north end of runway
AIRFIELD_S    = LatLon(-5.913,  22.368)   # south end
AIRFIELD_CTRL = LatLon(-5.898,  22.360)   # control tower / terminal
STATION       = LatLon(-5.895,  22.419)   # train station
DZ_NORTH      = LatLon(-5.870,  22.368)   # DZ NORTH — main DZ
DZ_EAST       = LatLon(-5.874,  22.384)   # DZ EAST  — feint / reserve
GUN_LINE      = LatLon(-5.875,  22.375)   # 81 mm mortar line
CITY_CENTRE   = LatLon(-5.900,  22.420)   # Kananga city centre
FUP           = LatLon(-5.882,  22.368)   # Form-Up Point — between DZ and airfield


# ── Phase definitions ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Phase:
    idx:         int
    code:        str     # AMBER / BRONZE / CRIMSON / IRON / GRANITE
    obj_name:    str
    description: str
    centre:      LatLon  # phase-clock target (where operators converge)
    axis_bearing: float  # attack axis bearing (clockwise from N)

PHASES: list[Phase] = [
    Phase(0, "AMBER",   "DZ NORTH",    "Airborne insertion — secure DZ",
          DZ_NORTH,   180.0),   # paras descend N→S toward airfield
    Phase(1, "BRONZE",  "FUP BLADE",   "DZ secure — form up and advance to airfield perimeter",
          FUP,        180.0),
    Phase(2, "CRIMSON", "OBJ EAGLE",   "Assault Kananga Airfield",
          AIRFIELD,   180.0),
    Phase(3, "IRON",    "OBJ STATION", "C Coy advances to seize train station",
          STATION,     95.0),   # eastward advance through city
    Phase(4, "GRANITE", "DEF POSTURE", "Consolidate — establish all-round defence",
          AIRFIELD,     0.0),
]


# ── HTTP plumbing ────────────────────────────────────────────────────────────
async def login(client: httpx.AsyncClient, callsign: str, password: str) -> str:
    try:
        r = await client.post(_p("/auth/login"),
                              data={"username": callsign, "password": password},
                              timeout=10)
        if r.status_code == 200:
            p = r.json()
            if p.get("mfa_required"):
                return ""
            return p.get("access_token", "")
    except Exception:
        pass
    return ""


async def api(client: httpx.AsyncClient, method: str, path: str, *,
              token: str = "", json: dict | list | None = None,
              timeout: float = 12.0) -> dict | list | None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if MISSION_ID:
        headers["X-Mission-ID"] = str(MISSION_ID)
    try:
        r = await client.request(method, _p(path),
                                 headers=headers, json=json, timeout=timeout)
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code not in (404, 409):
            log.debug("API %s %s → %d", method, path, r.status_code)
    except Exception as exc:
        log.debug("API error %s %s: %s", method, path, exc)
    return None


# ── Geometry helpers ─────────────────────────────────────────────────────────
def _tg(type_: str, lat: float, lon: float, *,
        affiliation: str = "FRIENDLY", echelon: str = "",
        notes: str = "", rotation: float = 0.0, geometry: str = "") -> dict:
    return {
        "type": type_, "latitude": lat, "longitude": lon,
        "affiliation": affiliation, "echelon": echelon,
        "notes": notes, "rotation": rotation, "geometry": geometry,
        "symbol_code": "", "visibility": "COMPANY",
    }

def _line(type_: str, pts: list[LatLon], **kw) -> dict:
    geo = json.dumps({"type": "line", "coords": [p.as_pair() for p in pts]})
    return _tg(type_, pts[0].lat, pts[0].lon, geometry=geo, **kw)

def _poly(type_: str, pts: list[LatLon], **kw) -> dict:
    geo = json.dumps({"type": "polygon", "coords": [p.as_pair() for p in pts]})
    return _tg(type_, pts[0].lat, pts[0].lon, geometry=geo, **kw)

def _unit(desc: str, sidc: str, ll: LatLon, affiliation: str = "ENEMY",
          echelon: str = "", notes_extra: str = "") -> dict:
    n = desc if not notes_extra else f"{desc} — {notes_extra}"
    return {
        "type": "ENEMY" if affiliation == "ENEMY" else "POI",
        "symbol_code": sidc,
        "latitude": ll.lat, "longitude": ll.lon,
        "affiliation": affiliation,
        "notes": n, "echelon": echelon,
        "rotation": 0.0, "geometry": "", "visibility": "COMPANY",
    }


# ── Static tactical objects (full OPORD graphics) ────────────────────────────
def build_static_objects() -> list[dict]:
    items: list[dict] = []

    # ── Phase lines ─────────────────────────────────────────────────────────
    # PL JUMP     — DZ threshold / release line
    # PL BLADE    — form-up line (FUP)
    # PL EAGLE    — airfield perimeter (LD for OBJ EAGLE)
    # PL FALCON   — limit of advance / airfield secured
    # PL STATION  — LOA after OBJ STATION
    w = 2_500   # half-width of phase lines in metres
    def _pl(name: str, centre: LatLon, bearing: float, **kw) -> dict:
        perp_l = (bearing - 90) % 360
        perp_r = (bearing + 90) % 360
        left   = centre.bearing_m(perp_l, w)
        right  = centre.bearing_m(perp_r, w)
        d = _line("PHASE_LINE", [left, right])
        d["notes"]   = name
        d.update(kw)
        return d

    items.append(_pl("PL JUMP",    DZ_NORTH.bearing_m(0, 200),  90.0))
    items.append(_pl("PL BLADE",   FUP,                          90.0))
    items.append(_pl("PL EAGLE",   AIRFIELD.bearing_m(0, 800),  90.0))
    items.append(_pl("PL FALCON",  AIRFIELD.bearing_m(180, 600), 90.0,
                     notes="PL FALCON — airfield LOA / hand-over to log echelon"))
    items.append(_pl("PL STATION", STATION.bearing_m(90, 400),   0.0,
                     notes="PL STATION — LOA C Coy after train-station seizure"))

    # ── FLOT / FLET ──────────────────────────────────────────────────────────
    flet_l = AIRFIELD.bearing_m(0, 700).bearing_m(270, 1_600)
    flet_r = AIRFIELD.bearing_m(0, 700).bearing_m( 90, 1_600)
    items.append(_line("FLET", [flet_l, flet_r],
                       affiliation="ENEMY", echelon="BN",
                       notes="FLET — enemy forward line, airfield northern perimeter"))
    flot_l = FUP.bearing_m(270, 2_000)
    flot_r = FUP.bearing_m( 90, 2_000)
    items.append(_line("FLOT", [flot_l, flot_r],
                       affiliation="FRIENDLY", echelon="BN",
                       notes="FLOT — 1 Para Bn line at FUP BLADE"))

    # ── Boundaries ───────────────────────────────────────────────────────────
    # Left/right boundaries of the regiment axis (N–S through airfield)
    reg_bdy_s = DZ_NORTH.bearing_m(270, 3_000)
    reg_bdy_n = CITY_CENTRE.bearing_m(270, 3_000)
    items.append(_line("BOUNDARY", [reg_bdy_s, reg_bdy_n],
                       echelon="REG", notes="Left boundary — REG axis"))
    reg_bdy_s2 = DZ_NORTH.bearing_m(90, 4_500)
    reg_bdy_n2 = CITY_CENTRE.bearing_m(90, 4_500)
    items.append(_line("BOUNDARY", [reg_bdy_s2, reg_bdy_n2],
                       echelon="REG", notes="Right boundary — REG axis"))
    # Inter-company boundary A/B Coy on airfield
    bdy_ab_n = AIRFIELD_N.bearing_m(270, 200)
    bdy_ab_s = AIRFIELD_S.bearing_m(270, 200)
    items.append(_line("BOUNDARY", [bdy_ab_n, bdy_ab_s],
                       echelon="COY", notes="A/B Coy boundary — runway centreline"))

    # ── DZ NORTH (friendly drop zone) ───────────────────────────────────────
    dz_poly = [
        DZ_NORTH.offset_m( 600, -1_200),
        DZ_NORTH.offset_m( 600,  1_200),
        DZ_NORTH.offset_m(-600,  1_200),
        DZ_NORTH.offset_m(-600, -1_200),
    ]
    items.append(_poly("OBJ_AREA", dz_poly, echelon="BN",
                       notes="DZ NORTH — primary drop zone, 5 RPC"))

    # ── DZ EAST (reserve / feint) ────────────────────────────────────────────
    dz_e_poly = [
        DZ_EAST.offset_m( 400, -700),
        DZ_EAST.offset_m( 400,  700),
        DZ_EAST.offset_m(-400,  700),
        DZ_EAST.offset_m(-400, -700),
    ]
    items.append(_poly("OBJ_AREA", dz_e_poly, echelon="COY",
                       notes="DZ EAST — reserve / deception DZ"))

    # ── OBJ EAGLE (airfield) ─────────────────────────────────────────────────
    af_poly = [
        AIRFIELD.offset_m( 900, -700),
        AIRFIELD.offset_m( 900,  700),
        AIRFIELD.offset_m(-900,  700),
        AIRFIELD.offset_m(-900, -700),
    ]
    items.append(_poly("OBJ_AREA", af_poly, echelon="BN",
                       notes="OBJ EAGLE — Kananga International Airport (FZUK)\n"
                             "A Coy: runway + apron; B Coy: terminal + tower; C Coy: reserve"))

    # ── OBJ STATION (train station) ──────────────────────────────────────────
    st_poly = [
        STATION.offset_m( 250, -500),
        STATION.offset_m( 250,  500),
        STATION.offset_m(-250,  500),
        STATION.offset_m(-250, -500),
    ]
    items.append(_poly("OBJ_AREA", st_poly, echelon="COY",
                       notes="OBJ STATION — Gare de Kananga\n"
                             "C Coy mission: seize, clear, hold. Exploitation to city core BPT."))

    # ── Attack axes ──────────────────────────────────────────────────────────
    # Main effort — A Coy, runway N→S
    items.append(_tg("ATK_AXIS",
                     *FUP.bearing_m(270, 300).as_pair(),
                     echelon="COY", rotation=180.0,
                     notes="A Coy — ME, axis SWORD: runway N threshold → apron"))
    # Supporting — B Coy, terminal from NW
    items.append(_tg("ATK_AXIS",
                     *FUP.bearing_m(240, 500).as_pair(),
                     echelon="COY", rotation=165.0,
                     notes="B Coy — SE, axis SHIELD: terminal + control tower"))
    # C Coy exploitation to station
    items.append(_tg("ATK_AXIS",
                     *AIRFIELD.bearing_m(90, 800).as_pair(),
                     echelon="COY", rotation=95.0,
                     notes="C Coy — axis LANCE: airfield east → train station (Φ4 IRON)"))

    # ── Blocking positions ────────────────────────────────────────────────────
    # Block south — prevent enemy reinforcement from Kananga city core
    items.append(_tg("BLOCK",
                     *AIRFIELD.bearing_m(180, 1_400).bearing_m(90, 600).as_pair(),
                     echelon="PL", rotation=0.0,
                     notes="Block SOUTH — 1 PL blocks road junction N of city, axis RONDPOINT"))
    # Block east — prevent flanking from eastern suburbs
    items.append(_tg("BLOCK",
                     *AIRFIELD.bearing_m(90, 2_200).bearing_m(0, 400).as_pair(),
                     echelon="PL", rotation=270.0,
                     notes="Block EAST — 1 Sec blocks eastern approach road to station"))

    # ── Reserve / counter-attack ──────────────────────────────────────────────
    items.append(_tg("COUNTERATTACK",
                     *AIRFIELD.bearing_m(0, 800).bearing_m(90, 300).as_pair(),
                     echelon="COY", rotation=180.0,
                     notes="C Coy CT-ATK BPT — on order counterattack from north-east"))
    items.append(_tg("DEF_AREA",
                     *DZ_NORTH.bearing_m(180, 200).bearing_m(270, 400).as_pair(),
                     echelon="BN", rotation=0.0,
                     notes="2 Para Bn reserve position — DZ NORTH perimeter, BPT reinforce EAGLE"))

    # ── Withdrawal route ──────────────────────────────────────────────────────
    items.append(_tg("WITHDRAW",
                     *DZ_NORTH.bearing_m(0, 600).as_pair(),
                     echelon="REG", rotation=0.0,
                     notes="Emergency withdrawal — DZ NORTH → recovery LZ if mission abort"))

    # ── Bypass route (eastern avenue past enemy positions) ────────────────────
    items.append(_tg("BYPASS",
                     *AIRFIELD.bearing_m(90, 1_400).as_pair(),
                     echelon="PL", rotation=95.0,
                     notes="C Coy bypass route — eastern urban track avoiding IED belt"))

    # ── 81 mm gun line + fire support coordination ────────────────────────────
    items.append(_unit("81 mm Mortar Section · 2× L16A2",
                       "SFGPUCFH----", GUN_LINE,
                       affiliation="FRIENDLY", echelon="SEC",
                       notes_extra="Weapons Coy gun line — ILLUM + HE + SMOKE ready"))
    items.append(_unit("Alternate gun position (AGP)", "SFGPUCFH----",
                       GUN_LINE.bearing_m(90, 300),
                       affiliation="FRIENDLY", echelon="SEC",
                       notes_extra="AGP MORTAR — shift on CDR order"))
    # Fire Support Coordination Line
    fsco_l = AIRFIELD.bearing_m(270, 2_500).bearing_m(0, 500)
    fsco_r = AIRFIELD.bearing_m( 90, 2_500).bearing_m(0, 500)
    items.append(_line("PHASE_LINE", [fsco_l, fsco_r],
                       notes="FSCL — no fires south of this line without FDC clearance",
                       affiliation="FRIENDLY", echelon="REG"))

    # ── Friendly support elements & POIs ────────────────────────────────────
    support_pois = [
        ("REG TAC HQ",          "SFGPUHU-----", DZ_NORTH.bearing_m(180, 300)),
        ("REG MAIN HQ",         "SFGPUH------", DZ_NORTH.bearing_m(0,  400)),
        ("CCP (Casualties)",    "SFGPIME-----", DZ_NORTH.bearing_m(90,  500)),
        ("BAS · Role 1 Med",    "SFGPIMS-----", DZ_NORTH.bearing_m(90,  700)),
        ("LZ ALPHA (MEDEVAC)",  "SFGPIBA-----", DZ_NORTH.bearing_m(270, 600)),
        ("LZ BRAVO (Log)",      "SFGPIBA-----", DZ_EAST.bearing_m(270, 400)),
        ("AMMO point",          "SFGPIRP-----", GUN_LINE.bearing_m(270, 200)),
        ("POL point",           "SFGPIRP-----", DZ_NORTH.bearing_m(180, 600).bearing_m(270, 300)),
        ("Sigs relay node",     "SFGPUSM-----", DZ_NORTH.bearing_m(90, 1_000)),
        ("FUP BLADE assembly",  "SFGPUH------", FUP),
        ("Airfield HQ (post-seizure)", "SFGPUHU-----", AIRFIELD_CTRL),
    ]
    for desc, sidc, ll in support_pois:
        items.append(_unit(desc, sidc, ll, affiliation="FRIENDLY"))

    # ── Enemy forces — militia defending airfield & city ─────────────────────
    #
    # N-sector: poorly-manned militia OPs on fence line, light weapons
    # Terminal: armed fighters using building as strongpoint
    # S-city: reinforced militia platoon, RPG + PKM, can reach airfield in 20 min
    # Station: militia section + PKM, controls rail approaches
    # Indirect: 60 mm mortar IVO market
    # Technicals: 3× pickups w/ DShK + mounted ZPU-2 in city
    # IEDs: two belts, eastern approach road
    #
    enemy_units = [
        # Airfield perimeter — north
        ("Militia OP (2–4 PAX, AK/PKM)",  "SHGPUCIR----",
         AIRFIELD_N.bearing_m(0, 400).bearing_m(270, 200)),
        ("Militia OP (2–4 PAX)",           "SHGPUCIR----",
         AIRFIELD_N.bearing_m(0, 400).bearing_m( 90, 200)),
        ("Fence-line fighting position",   "SHGPUCI-----",
         AIRFIELD_N.bearing_m(270, 150)),
        ("Fence-line fighting position",   "SHGPUCI-----",
         AIRFIELD_N.bearing_m( 90, 150)),

        # Terminal / tower — main airfield enemy
        ("Militia section in terminal building (strongpoint)",
         "SHGPUCIM----", AIRFIELD_CTRL),
        ("PKM team, control-tower roof",   "SHGPUCIS----",
         AIRFIELD_CTRL.bearing_m(0, 80)),
        ("RPG team, apron hangar",         "SHGPUCAA---F",
         AIRFIELD.bearing_m(270, 300)),

        # Airfield south — road-block + reaction force
        ("Militia platoon, road junction (reaction force)",
         "SHGPUCI-----",
         AIRFIELD.bearing_m(180, 1_200)),
        ("Technical w/ DShK (N approach)",  "SHGPEVAT----",
         AIRFIELD.bearing_m(0, 700).bearing_m(270, 100)),
        ("Technical w/ DShK (apron W)",     "SHGPEVAT----",
         AIRFIELD.bearing_m(270, 500).bearing_m(180, 200)),

        # City & station
        ("Militia section, train-station strongpoint (PKM, RPG)",
         "SHGPUCI-----", STATION),
        ("Militia PKM team, station roof",  "SHGPUCIS----",
         STATION.bearing_m(0, 100)),
        ("Technical w/ ZPU-2, market square",
         "SHGPEVAD----",
         CITY_CENTRE.bearing_m(270, 300)),
        ("Militia section, urban blocks NW of station",
         "SHGPUCI-----",
         STATION.bearing_m(270, 600)),
        ("Militia section, urban blocks S of station",
         "SHGPUCI-----",
         STATION.bearing_m(180, 500)),

        # Indirect fire — enemy mortars
        ("Enemy 60 mm mortar (1 tube), market/compound",
         "SHGPUCFHE---",
         CITY_CENTRE.bearing_m(90, 400)),
        ("Suspected 82 mm mortar (1–2 tubes), south-city compound",
         "SHGPUCFHE---",
         CITY_CENTRE.bearing_m(180, 1_000)),

        # IED belts
        ("Confirmed IED belt, eastern approach road (x4)",
         "SHGPUCWM----",
         AIRFIELD.bearing_m(90, 1_600)),
        ("Suspected IED, N access track to runway",
         "SHGPUCWM----",
         AIRFIELD_N.bearing_m(0, 250)),

        # Enemy OP south
        ("Militia OP, city northern edge",  "SHGPUCIR----",
         CITY_CENTRE.bearing_m(0, 1_200)),
    ]

    for desc, sidc, ll in enemy_units:
        items.append(_unit(desc, sidc, ll, affiliation="ENEMY"))

    # Enemy defensive areas
    items.append(_tg("DEF_AREA",
                     *AIRFIELD.bearing_m(180, 500).as_pair(),
                     affiliation="ENEMY", echelon="COY",
                     notes="Enemy hasty defence — terminal + southern runway; RPG + PKM"))
    items.append(_tg("DEF_AREA",
                     *STATION.as_pair(),
                     affiliation="ENEMY", echelon="SEC",
                     notes="Enemy militia section strongpoint — train station"))
    items.append(_tg("AMBUSH",
                     *AIRFIELD.bearing_m(90, 1_000).bearing_m(0, 100).as_pair(),
                     affiliation="ENEMY", echelon="SEC", rotation=270.0,
                     notes="Suspected ambush position, eastern approach road to station"))

    return items


# ── OPORD ────────────────────────────────────────────────────────────────────
def build_opord() -> dict:
    return {
        "title":          "OPORD 5RPC-01/26 — OPERATION IRON SKY",
        "opord_number":   "OPORD 5RPC-01/26",
        "dtg":            "251800ZMAY26",
        "time_zone":      "ZULU",
        "classification": "CONFIDENTIAL",
        "references":     (
            "A. IGN 1:50 000 sheet KANANGA (6-E), Zone 35L\n"
            "B. Air tasking order COMKFOR Ref AIRTASK/26/0445\n"
            "C. OPLAN 5 RPC PARASOL (IHL briefing attached)\n"
            "D. ROE card 5RPC/26-05, authorised lethal engagement NSAG bearing arms\n"
            "E. MED EVAC SOP 5RPC/CASEVAC/22\n"
            "F. CSAR plan Ref COMJOC/CSAR/26/011\n"
            "G. COT/TAK interoperability annex — Arrow Gateway config"
        ),
        "task_organization": (
            "5 RÉGIMENT PARA-COMMANDOS (5 RPC)\n"
            "────────────────────────────────────────────────────\n"
            "HQ 5 RPC                                LTC MOREAU\n"
            "  S2 int cell (2 pers)\n"
            "  Sigs Pl (SATCOM + HF/VHF)\n"
            "  FAC team (Air-Ground integration)\n\n"
            "1 PARA BN (MAIN EFFORT)\n"
            "  A Coy — OBJ EAGLE runway seizure (MAIN EFFORT)\n"
            "    1 Pl, 2 Pl, 3 Pl (rifles) + Wpns det 2× GPMG\n"
            "  B Coy — OBJ EAGLE terminal + tower\n"
            "    4 Pl, 5 Pl + Wpns det 2× GPMG + 1× ATGL\n"
            "  C Coy — OBJ STATION (Φ4 IRON, on order)\n"
            "    6 Pl, 7 Pl, 8 Pl (2 rifle + 1 support) + Wpns det\n"
            "  HQ Coy 1 BN — FUP BLADE control + BAS\n\n"
            "2 PARA BN (RESERVE)\n"
            "  D Coy, E Coy (rifles) — secure DZ NORTH / DZ EAST\n"
            "  F Coy (Wpns) — 81 mm section assigned to Weapons Coy\n"
            "  BPT reinforce 1 BN at OBJ EAGLE on REG CDR order\n\n"
            "WEAPONS COY 5 RPC\n"
            "  81 mm Mortar Section: 2× L16A2 on GUN LINE\n"
            "    Ammo: HE ×120 / ILLUM ×40 / SMOKE ×30 per tube\n"
            "    Max range 5650 m (C1 charge) — covers EAGLE + STATION\n"
            "  ATGL Section: 3× Carl Gustav M4 (HEAT + HE + SMOKE)\n\n"
            "RECCE TP\n"
            "  GHOST-21/22/23 — 3 teams, 2 pers each, IR + NV\n"
            "  Mission: screen DZ N/E, mark enemy OPs, route recce to EAGLE\n\n"
            "MED PL: BAS at LZ ALPHA · CCP at DZ NORTH\n"
            "LOG PL: resupply via LZ BRAVO · 24 h combat load"
        ),
        "situation": {
            "enemy_forces": (
                "NSAG MBORORO COALITION — estimated 300–600 fighters, fragmented C2.\n"
                "AIRFIELD GARRISON:\n"
                "  ~60–80 fighters; AK-47 / PKM / RPG-7 / 60mm mortar.\n"
                "  Hasty defences at terminal, control tower, fence perimeter.\n"
                "  1–2 technicals (DShK), patrolling runway road.\n"
                "  NO air defence assessed (single ZPU-2 at market, range 1.4 km slant).\n\n"
                "CITY / STATION:\n"
                "  ~40–60 fighters in urban blocks N–W of station.\n"
                "  PKM/RPG strongpoint in station building + adjacent warehouses.\n"
                "  60 mm mortar @ market compound, 82 mm suspected S-city.\n"
                "  Confirmed IED belt on eastern approach road to station.\n\n"
                "COA 1 (likely): defend in place, melt into urban terrain on contact.\n"
                "COA 2 (dangerous): vehicle-borne VBIED on DZ during assault phase.\n\n"
                "TERRAIN: flat savannah DZ; cleared perimeter 300 m around runway;\n"
                "urban grid south and east; seasonal soil — passable to wheeled vehicle."
            ),
            "friendly_forces": (
                "Higher: COMJOC authorises operation. Air support on call (ISR UAV 24 h).\n"
                "Adjacent: UN MONUSCO sector has no forces within 15 km during H-Hour.\n"
                "Supporting: 2× C-130J scheduled for H-Hour serial (drop 1 BN + Weapons Coy);\n"
                "3rd serial carries 2 BN reserve. LZ ALPHA cleared for UH-60 medevac H+45."
            ),
            "attachments": (
                "FAC team ARROW-AIR attached HQ 5 RPC (GPS + laser designator).\n"
                "JTAC cleared for AIRSTRIKE on command if OBJ EAGLE not secure by H+2."
            ),
            "weather": (
                "Night DZ: winds 080/12 kt, no moonlight — NVG conditions GREEN.\n"
                "Day assault: 28°C, humidity 85%, scattered cloud 1500 ft."
            ),
        },
        "mission": (
            "5 RPC conducts an airborne assault NLT H+00 to seize KANANGA AIRFIELD "
            "(OBJ EAGLE) and KANANGA TRAIN STATION (OBJ STATION), in order to establish "
            "a lodgement securing the strategic road and rail junction, enabling follow-on "
            "forces to enter Kasaï-Central Province by air and rail."
        ),
        "execution": {
            "commanders_intent": (
                "PURPOSE: Deny the MBORORO coalition use of the only sealed runway and rail "
                "junction in Kasaï-Central, disrupting their resupply and reinforcement.\n"
                "METHOD: Simultaneous airborne insertion on DZ NORTH / DZ EAST, rapid "
                "advance to OBJ EAGLE, A/B Coy assault with 81 mm suppression, C Coy "
                "exploitation to OBJ STATION. 2 BN secures DZ and acts as reserve.\n"
                "END STATE: OBJ EAGLE airfield OPEN for fixed-wing by H+3; OBJ STATION "
                "under REG control; all-round defence established; enemy unable to counter-attack."
            ),
            "scheme_of_manoeuvre": (
                "Φ1 AMBER — H-Hour: 1 BN drops DZ NORTH; 2 BN drops DZ EAST. "
                "Secure DZ, mark LZ ALPHA, neutralise enemy OPs on fence line.\n\n"
                "Φ2 BRONZE — H+20 min: 1 BN advances to FUP BLADE in two columns "
                "(A Coy left / B Coy right). RECCE TP screens 500 m ahead. "
                "2 BN holds DZ perimeter; Wpns Coy deploys gun line, registers targets.\n\n"
                "Φ3 CRIMSON — H+40 min: A Coy assaults north runway threshold → apron. "
                "B Coy assaults terminal + control tower (axis SHIELD). "
                "81 mm fires: ILLUM over OBJ EAGLE H-2min; HE on fence-line OPs H-1min; "
                "SMOKE on terminal approach on call. RPG: 60 mm mortar SUPPRESSED by gun-line. "
                "C Coy in reserve at FUP, BPT exploit east.\n\n"
                "Φ4 IRON — H+2 hr (on order, after OBJ EAGLE secured): C Coy advances axis "
                "LANCE eastward, bypasses IED belt via bypass route, assaults OBJ STATION. "
                "1× 81 mm tube relocates to AGP for fire support on station approach. "
                "B Coy consolidates airfield; A Coy sends 1 Pl to clear eastern perimeter.\n\n"
                "Φ5 GRANITE — OBJ EAGLE + STATION secured: Establish all-round defence. "
                "A Coy: airfield perimeter (runway N + E). B Coy: terminal + control tower. "
                "C Coy: train station strongpoint + eastern approaches. "
                "2 BN: reserve at DZ NORTH, BPT counterattack from north."
            ),
            "tasks_by_subunit": {
                "A_COY":    "Seize north runway threshold, advance S to apron. Clear runway. "
                            "Post-seizure: defend runway N + eastern fence (Φ5).",
                "B_COY":    "Seize terminal + control tower. Post-seizure: hold terminal building. "
                            "Detach 1 Pl to eastern perimeter on C Coy relief.",
                "C_COY":    "Reserve at FUP BLADE until OBJ EAGLE secure. Exploit to OBJ STATION "
                            "via axis LANCE. Seize, clear, hold train station. Φ5: defend station.",
                "2_PARA_BN":"Secure DZ NORTH and DZ EAST. Protect LZ ALPHA. Regiment reserve. "
                            "BPT counterattack at OBJ EAGLE on CDR order.",
                "WEAPONS":  "Deploy gun line at GUN LINE NLT H-10. Register targets T1–T6. "
                            "Priority: T1 terminal approach, T2 fence OPs, T3 60mm mortar enemy, "
                            "T4 station approach, T5 city block W of station, T6 road junction S. "
                            "Shift to AGP before Φ4. Cease fire line: PL FALCON (airfield), "
                            "FSCL applies throughout.",
                "RECCE_TP": "Screen 500 m ahead of 1 BN axis. Mark enemy OPs. "
                            "Route recce axis LANCE for C Coy. Confirm IED belt location.",
            },
            "coordinating_instructions": (
                "H-Hour: 25 May 2026 / 010000 local (2300 Zulu 24 May).\n"
                "Actions on: enemy air-defence — immediate suppression by gun-line + JTAC.\n"
                "ROE: positive ID required. Civilian structure not to be engaged without CDR auth.\n"
                "Casualty: CASEVAC to LZ ALPHA, MEDEVAC H+45 on call.\n"
                "CCIR: (1) OBJ EAGLE secured; (2) IED belt marked; (3) Reinforcing enemy column; "
                "(4) civilian mass movement onto DZ.\n"
                "EMCON: NV/IR from H-2 hr; no radio until DZ secured."
            ),
        },
        "sustainment": {
            "logistics": (
                "Class I: 24 h combat ration issued pre-jump. Resupply LZ BRAVO H+6.\n"
                "Class III: 2× fuel blivets LZ BRAVO. No vehicles until H+4 airland serial.\n"
                "Class V: 81 mm HE ×240 / ILLUM ×80 / SMOKE ×60 loaded at DZ. "
                "Carl Gustav rounds: 24 HEAT / 12 HE / 6 SMOKE per section.\n"
                "Barrier/obstacle: 2× Claymore per section; engineer breach kit at A Coy HQ."
            ),
            "medical": (
                "Role 1 BAS: LZ ALPHA; CCP: DZ NORTH.\n"
                "MEDEVAC: UH-60 on 30-min alert from H+45. Grid passed at H-Hour brief.\n"
                "Priority: immediate CASEVAC by stretcher to CCP; P1 to BAS within 60 min."
            ),
            "personnel": (
                "Replacement policy: none during initial phase — casualty is LOA.\n"
                "EPW: collect, tag, evacuate to REG HQ holding area at DZ NORTH."
            ),
        },
        "command_signal": {
            "command": (
                "REG CDR: LTC MOREAU at REG TAC HQ (DZ NORTH / AIRFIELD post-seizure).\n"
                "1 BN CDR: MAJ LAMBERT at FUP BLADE / OBJ EAGLE.\n"
                "2 BN CDR: MAJ OKONKWO at DZ NORTH perimeter.\n"
                "Succession: CDR → S3 → 1 BN CDR."
            ),
            "signal": (
                "C2: Arrow tactical network (this system). All encrypted.\n"
                "Freq plan:\n"
                "  REG CMD net: 40.50 MHz AM\n"
                "  1 BN tac:    52.00 MHz FM\n"
                "  2 BN tac:    53.00 MHz FM\n"
                "  Fire net:    37.50 MHz FM (FDC — Weapons Coy)\n"
                "  CASEVAC:     40.40 MHz AM\n"
                "  JTAC/Air:    UHF 363.0 MHz\n"
                "Brevity: EAGLE = airfield secure; STATION = train station secure; "
                "IRON SKY = all objectives secure; BIRDCAGE = abort/withdrawal.\n"
                "PACE: primary Arrow/radio; alt HF; contingency SATCOM; emergency runner."
            ),
        },
    }


# ── Sim operators (ORBAT on map) ─────────────────────────────────────────────
SIM_PASSWORD = "IronSky2526!"

@dataclass
class SimOp:
    callsign: str
    rank:     str
    role:     str   # ADMIN / BATTLE_CAPTAIN / OPERATOR
    # Offset from phase centre (metres, N/E positive)
    offset_n: float
    offset_e: float
    home:     Optional[LatLon] = None   # static elements
    token:    str = field(default="", compare=False)
    op_id:    int = field(default=0,   compare=False)
    lat:      float = field(default=0.0, compare=False)
    lon:      float = field(default=0.0, compare=False)

def _regiment_orbat() -> list[SimOp]:
    return [
        # ── REG HQ ─────────────────────────────────────────────────────────
        SimOp("MOREAU-6",   "OF-5", "ADMIN",          offset_n= -200,  offset_e=    0),  # REG CDR
        SimOp("ARROW-S3",   "OF-4", "BATTLE_CAPTAIN", offset_n= -300,  offset_e=  120),  # S3 ops
        SimOp("ARROW-S2",   "OF-3", "BATTLE_CAPTAIN", offset_n= -300,  offset_e= -120),  # S2 int
        SimOp("ARROW-FAC",  "OF-3", "BATTLE_CAPTAIN", offset_n= -150,  offset_e=   80),  # JTAC/FAC
        # ── 1 Para Bn ──────────────────────────────────────────────────────
        SimOp("LAMBERT-6",  "OF-4", "BATTLE_CAPTAIN", offset_n= -100,  offset_e=    0),  # 1 BN CDR
        SimOp("ACOY-6",     "OF-3", "BATTLE_CAPTAIN", offset_n=  200,  offset_e= -200),  # A Coy OC
        SimOp("BCOY-6",     "OF-3", "BATTLE_CAPTAIN", offset_n=  200,  offset_e=  200),  # B Coy OC
        SimOp("CCOY-6",     "OF-3", "BATTLE_CAPTAIN", offset_n= -400,  offset_e=    0),  # C Coy OC (reserve)
        SimOp("ALPHA-11",   "OR-6", "OPERATOR",       offset_n=  450,  offset_e= -350),  # A Coy 1 Pl
        SimOp("ALPHA-21",   "OR-6", "OPERATOR",       offset_n=  400,  offset_e= -150),  # A Coy 2 Pl
        SimOp("BRAVO-41",   "OR-6", "OPERATOR",       offset_n=  350,  offset_e=  250),  # B Coy 4 Pl
        SimOp("BRAVO-51",   "OR-6", "OPERATOR",       offset_n=  300,  offset_e=  450),  # B Coy 5 Pl
        SimOp("CHARLIE-61", "OR-6", "OPERATOR",       offset_n= -600,  offset_e= -100),  # C Coy 6 Pl
        SimOp("CHARLIE-71", "OR-6", "OPERATOR",       offset_n= -700,  offset_e=  100),  # C Coy 7 Pl
        # ── 2 Para Bn (reserve — stays near DZ) ───────────────────────────
        SimOp("OKONKWO-6",  "OF-4", "BATTLE_CAPTAIN",
              offset_n=0, offset_e=0, home=DZ_NORTH.offset_m(-100, 0)),
        SimOp("DELTA-81",   "OR-6", "OPERATOR",
              offset_n=0, offset_e=0, home=DZ_NORTH.offset_m(200, -300)),
        SimOp("ECHO-91",    "OR-6", "OPERATOR",
              offset_n=0, offset_e=0, home=DZ_NORTH.offset_m(200,  300)),
        # ── Weapons Coy (81 mm — fixed at gun line) ────────────────────────
        SimOp("THUNDER-6",  "OF-3", "BATTLE_CAPTAIN",
              offset_n=0, offset_e=0, home=GUN_LINE),
        SimOp("THUNDER-FDC","OR-5", "OPERATOR",
              offset_n=0, offset_e=0, home=GUN_LINE.offset_m(0, 50)),
        # ── Recce (push ahead) ────────────────────────────────────────────
        SimOp("GHOST-21",   "OR-7", "OPERATOR",       offset_n=  800,  offset_e= -300),
        SimOp("GHOST-22",   "OR-7", "OPERATOR",       offset_n= 1_000, offset_e=    0),
        SimOp("GHOST-23",   "OR-7", "OPERATOR",       offset_n=  800,  offset_e=  300),
        # ── Med / Log ─────────────────────────────────────────────────────
        SimOp("MEDIC-6",    "OF-2", "OPERATOR",
              offset_n=0, offset_e=0, home=DZ_NORTH.offset_m(0, 500)),
        SimOp("SUPPLY-6",   "OR-7", "OPERATOR",
              offset_n=0, offset_e=0, home=DZ_EAST),
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
        log.info("  registered %-14s (%s)", op.callsign, op.role)
    else:
        tok = await login(client, op.callsign, SIM_PASSWORD)
        if tok:
            op.token = tok


async def position_for_phase(op: SimOp, ph: Phase) -> tuple[float, float]:
    if op.home:
        jit = op.home.offset_m(random.gauss(0, 20), random.gauss(0, 20))
        return jit.lat, jit.lon
    base = ph.centre.offset_m(op.offset_n, op.offset_e)
    spot = base.offset_m(random.gauss(0, 30), random.gauss(0, 30))
    return spot.lat, spot.lon


PHASE_SECONDS = 40.0      # real seconds per phase at speed=1
TICK_SECONDS  = 2.5
PARA_WALK_MS  = 6_000 / 3_600    # 6 km/h — para advance pace on foot


async def drive_operator(client: httpx.AsyncClient, op: SimOp,
                         phase_idx_state: dict, speed: float) -> None:
    if not op.token:
        return
    # Seed near DZ NORTH
    seed = DZ_NORTH.offset_m(op.offset_n * 0.3, op.offset_e * 0.3)
    op.lat, op.lon = seed.lat, seed.lon
    real_tick = max(0.05, TICK_SECONDS / speed)
    while True:
        idx   = max(0, min(len(PHASES) - 1, phase_idx_state["idx"]))
        ph    = PHASES[idx]
        tlat, tlon = await position_for_phase(op, ph)
        sim_dt = real_tick * speed
        op.lat, op.lon = step_towards(op.lat, op.lon, tlat, tlon, PARA_WALK_MS, sim_dt)
        await api(client, "POST", "/tracking/position", token=op.token, json={
            "latitude":  op.lat,
            "longitude": op.lon,
            "altitude":  430.0,   # Kananga ~1430 m ASL
        })
        await asyncio.sleep(real_tick)


async def advance_phase_clock(phase_idx_state: dict, speed: float, loop: bool) -> None:
    interval = max(0.5, PHASE_SECONDS / speed)
    while True:
        await asyncio.sleep(interval)
        nxt = phase_idx_state["idx"] + 1
        if nxt >= len(PHASES):
            if not loop:
                phase_idx_state["idx"] = len(PHASES)
                log.info("🏁 OBJ EAGLE + OBJ STATION secured. IRON SKY complete.")
                return
            log.info("🔁 LOOPING — operation re-starts at Φ1 AMBER.")
            phase_idx_state["idx"] = 0
        else:
            phase_idx_state["idx"] = nxt
        ph = PHASES[phase_idx_state["idx"]]
        log.info("📍 PHASE — Φ%d %s · %s", ph.idx + 1, ph.code, ph.obj_name)


def _recce_or_any(ops: list[SimOp]) -> Optional[SimOp]:
    recce = [o for o in ops if o.callsign.startswith("GHOST-") and o.token and o.lat]
    live  = [o for o in ops if o.token and o.lat]
    return random.choice(recce) if recce else (random.choice(live) if live else None)

def _coy_leader(ops: list[SimOp]) -> Optional[SimOp]:
    leaders = [o for o in ops if o.callsign.endswith("-6") and o.token and o.lat]
    return random.choice(leaders) if leaders else _recce_or_any(ops)


CONTACT_TEMPLATES = [
    ("Militia section — AK/PKM, fence line",   "ENEMY", "SHGPUCI-----"),
    ("Armed pickup (technical), airfield road", "ENEMY", "SHGPEVAT----"),
    ("RPG team, building rooftop",             "ENEMY", "SHGPUCAA---F"),
    ("60 mm mortar firing",                    "ENEMY", "SHGPUCFHE---"),
    ("Enemy OP/sentry — 2 PAX",                "ENEMY", "SHGPUCIR----"),
    ("IED — suspect device on track",          "ENEMY", "SHGPUCWM----"),
    ("Sniper team, urban building",            "ENEMY", "SHGPUCIS----"),
    ("Militia runner / reinforcement",         "ENEMY", "SHGPUCI-----"),
    ("Civilian crowd on DZ — clear approach",  "POI",   "SNGPI-------"),
    ("Obstacle / barrier — road blocked",      "POI",   "SFGPGPRD----"),
]


async def inject_contacts(client: httpx.AsyncClient, ops: list[SimOp],
                          speed: float) -> None:
    interval = max(2.0, 12.0 / speed)
    await asyncio.sleep(interval * 0.3)
    n = 0
    while True:
        await asyncio.sleep(interval)
        op = _recce_or_any(ops)
        if not op:
            continue
        desc, type_, sidc = random.choice(CONTACT_TEMPLATES)
        spread = random.uniform(150, 600)
        brg    = random.uniform(90, 270)    # contacts generally south/around the airfield
        clat   = op.lat + spread * math.cos(math.radians(brg)) * LAT_DEG_PER_M
        clon   = op.lon + spread * math.sin(math.radians(brg)) * lon_deg_per_m(op.lat)
        grid   = f"{clat:.4f},{clon:.4f}"
        n += 1
        r = await api(client, "POST", "/tactical-objects", token=op.token, json={
            "type": type_, "symbol_code": sidc,
            "latitude":  round(clat, 6), "longitude": round(clon, 6),
            "affiliation": "ENEMY" if type_ == "ENEMY" else "FRIENDLY",
            "notes":    f"{desc} · {grid}",
            "echelon": "", "rotation": 0.0, "geometry": "",
            "visibility": "COMPANY",
        })
        if r:
            log.info("⚠️  %s marks: %s (#%d)", op.callsign, desc, n)
        await api(client, "POST", "/messages", token=op.token, json={
            "content": f"CONTACT — {desc}, grid {grid}",
            "message_type": "BROADCAST",
        })


async def inject_spot_reports(client: httpx.AsyncClient, ops: list[SimOp],
                              speed: float) -> None:
    interval = max(3.0, 20.0 / speed)
    await asyncio.sleep(interval * 0.6)
    activities = [
        "DEFFENDING prepared position",
        "MOVING east on airfield perimeter road",
        "WITHDRAWING toward city centre",
        "FIRING from rooftop — direction north",
        "EMPLACING obstacle at road junction",
        "CONDUCTING fire — 60 mm mortar",
    ]
    n = 0
    while True:
        await asyncio.sleep(interval)
        op = _recce_or_any(ops)
        if not op:
            continue
        grid = f"{op.lat:.4f},{op.lon:.4f}"
        payload = {
            "size":        random.choice(["1-2", "3-5", "6-10", "10+"]),
            "activity":    random.choice(activities),
            "location":    grid,
            "unit":        random.choice(["militia", "NSAG", "armed group", "irregular"]),
            "time":        "current",
            "equipment":   random.choice(["AK-47", "PKM", "RPG-7", "60mm mortar", "technical"]),
            "direction":   random.choice(["N", "NE", "E", "SE", "S", "SW", "W", "NW"]),
            "distance":    random.choice([100, 200, 350, 500, 800]),
            "description": "SPOT report from recce / forward element",
        }
        r = await api(client, "POST", "/reports", token=op.token, json={
            "type": "SPOT", "payload": payload,
        })
        if r:
            n += 1
            log.info("📋 %s SPOT %s %s @ %s (#%d)",
                     op.callsign, payload["size"], payload["unit"], grid, n)


async def inject_81mm_fire_missions(client: httpx.AsyncClient, ops: list[SimOp],
                                    speed: float, phase_idx_state: dict) -> None:
    """81 mm fire support — mortar FDC calls for fire aligned with current phase.

    Φ1 AMBER   : ILLUM over DZ to mark ground for lead aircraft
    Φ2 BRONZE  : HE registration on fence-line OPs; SMOKE screen on terminal approach
    Φ3 CRIMSON : HE on terminal / tower approach; ILLUM for night assault; SMOKE
    Φ4 IRON    : Shift gun to AGP; HE on station strongpoint approach; SMOKE west face
    Φ5 GRANITE : ILLUM on perimeter; suppressive HE on any counter-attack route
    """
    interval = max(5.0, 30.0 / speed)
    await asyncio.sleep(interval * 0.4)
    n = 0
    thunder = next((o for o in ops if o.callsign == "THUNDER-FDC" and o.token), None)
    if not thunder:
        thunder = next((o for o in ops if "THUNDER" in o.callsign and o.token), None)

    phase_targets = {
        # phase_idx : [(lat, lon, mission_type, ammo, qty, desc), ...]
        0: [  # Φ1 AMBER — ILLUM
            (DZ_NORTH.lat, DZ_NORTH.lon, "ILLUMINATION", "ILLUM", 2,
             "ILLUM DZ NORTH — mark ground for lead C-130 serial"),
            (DZ_EAST.lat,  DZ_EAST.lon,  "ILLUMINATION", "ILLUM", 1,
             "ILLUM DZ EAST — secondary DZ marking"),
        ],
        1: [  # Φ2 BRONZE — registration + SMOKE
            (AIRFIELD_N.bearing_m(0, 500).lat, AIRFIELD_N.bearing_m(0, 500).lon,
             "ADJUST_FIRE", "HE", 3,
             "ADJUST FIRE — T2 fence-line OPs, north runway threshold"),
            (AIRFIELD_CTRL.bearing_m(270, 300).lat, AIRFIELD_CTRL.bearing_m(270, 300).lon,
             "SUPPRESSION", "SMOKE", 4,
             "SMOKE — screen terminal western approach for B Coy advance"),
        ],
        2: [  # Φ3 CRIMSON — main assault fire support
            (AIRFIELD_CTRL.lat, AIRFIELD_CTRL.lon,
             "FIRE_FOR_EFFECT", "HE", 6,
             "FFE T1 — terminal strongpoint, A Coy LD H-1 min"),
            (AIRFIELD.bearing_m(0, 700).bearing_m(270, 100).lat,
             AIRFIELD.bearing_m(0, 700).bearing_m(270, 100).lon,
             "SUPPRESSION", "HE", 4,
             "SUPPRESS T2 — technical/DShK N approach, keep heads down"),
            (AIRFIELD_N.lat, AIRFIELD_N.lon,
             "ILLUMINATION", "ILLUM", 3,
             "ILLUM — north runway, A Coy assault illumination"),
            (AIRFIELD.bearing_m(180, 1_200).lat, AIRFIELD.bearing_m(180, 1_200).lon,
             "SUPPRESSION", "HE", 4,
             "SUPPRESS T6 — road junction S, prevent militia reinforcement"),
        ],
        3: [  # Φ4 IRON — C Coy advance to station
            (STATION.bearing_m(270, 500).lat, STATION.bearing_m(270, 500).lon,
             "FIRE_FOR_EFFECT", "HE", 6,
             "FFE T4 — station western face, C Coy axis LANCE prep"),
            (STATION.bearing_m(270, 600).lat, STATION.bearing_m(270, 600).lon,
             "SUPPRESSION", "SMOKE", 4,
             "SMOKE — mask C Coy assault on station from western approach"),
            (CITY_CENTRE.bearing_m(90, 400).lat, CITY_CENTRE.bearing_m(90, 400).lon,
             "SUPPRESSION", "HE", 3,
             "SUPPRESS T3 — enemy 60mm mortar in market compound"),
        ],
        4: [  # Φ5 GRANITE — consolidation
            (AIRFIELD.bearing_m(180, 1_400).lat, AIRFIELD.bearing_m(180, 1_400).lon,
             "ILLUMINATION", "ILLUM", 2,
             "ILLUM — south approach, reveal any counter-attack forming up"),
            (STATION.bearing_m(180, 600).lat, STATION.bearing_m(180, 600).lon,
             "ILLUMINATION", "ILLUM", 2,
             "ILLUM — station south, perimeter illumination"),
        ],
    }

    posted_by_phase: set[int] = set()

    while True:
        await asyncio.sleep(interval)
        phase = phase_idx_state.get("idx", 0)
        phase = max(0, min(len(PHASES) - 1, phase))

        if thunder and thunder.token:
            shooter = thunder
        else:
            shooter = _recce_or_any(ops)
        if not shooter:
            continue

        targets = phase_targets.get(phase, [])
        if not targets:
            continue

        target = random.choice(targets)
        tlat, tlon, mtype, ammo, qty, desc = target

        # Observer bearing from gun line
        dlat = (tlat - GUN_LINE.lat) * 111_000
        dlon = (tlon - GUN_LINE.lon) * 111_000 * math.cos(math.radians(GUN_LINE.lat))
        brg  = math.degrees(math.atan2(dlon, dlat)) % 360

        r = await api(client, "POST", "/fire-missions", token=shooter.token, json={
            "latitude":     round(tlat, 6),
            "longitude":    round(tlon, 6),
            "altitude":     430.0,
            "direction":    round(brg, 1),
            "mission_type": mtype,
            "ammunition":   ammo,
            "quantity":     qty,
            "description":  f"[81mm] {desc} | Φ{phase+1} {PHASES[phase].code}",
        })
        if r:
            n += 1
            log.info("💥 %s 81mm %s ×%d %s @ %.4f,%.4f (#%d)",
                     shooter.callsign, ammo, qty, mtype, tlat, tlon, n)

        # Broadcast to all units
        await api(client, "POST", "/messages", token=shooter.token, json={
            "content": (f"FIRE MISSION — 81mm {ammo} ×{qty} {mtype}\n"
                        f"Target: {desc}\nGrid: {tlat:.4f},{tlon:.4f} | Brg: {brg:.0f}°\n"
                        f"PHASE: Φ{phase+1} {PHASES[phase].code}"),
            "message_type": "BROADCAST",
        })


async def inject_tic_alerts(client: httpx.AsyncClient, ops: list[SimOp],
                            speed: float) -> None:
    interval = max(8.0, 50.0 / speed)
    await asyncio.sleep(interval * 0.9)
    n = 0
    while True:
        await asyncio.sleep(interval)
        op = _recce_or_any(ops)
        if not op:
            continue
        type_ = random.choices(
            ["TIC", "MEDICAL", "EVAC", "LOST_COMMS"],
            weights=[7, 2, 1, 1])[0]
        r = await api(client, "POST", "/alerts", token=op.token, json={
            "type":      type_,
            "latitude":  round(op.lat, 6),
            "longitude": round(op.lon, 6),
        })
        if r:
            n += 1
            log.info("🚨 %s ALERT %s @ %.4f,%.4f (#%d)",
                     op.callsign, type_, op.lat, op.lon, n)


async def inject_phase_radio(client: httpx.AsyncClient, ops: list[SimOp],
                             phase_idx_state: dict, speed: float) -> None:
    """Broadcast phase-change radio traffic when the phase clock advances."""
    last_phase = -1
    phase_messages = {
        0: ("MOREAU-6", "ALL STATIONS — H-HOUR. Serial 1 away. AMBER AMBER AMBER. "
            "DZ NORTH: 1 BN stick away. Wind 080/12. No chutes fouled. OUT."),
        1: ("LAMBERT-6", "BLADE this is STEEL — all callsigns at FUP. "
            "GHOST reports fence-line OPs active, 2 sentries confirmed. "
            "A and B Coy advance on EAGLE in 5 mikes. FDC confirm targets registered. OVER."),
        2: ("ACOY-6",    "MOREAU-6 this is ACOY — EAGLE ASSAULT BEGUN. "
            "A Coy on the wire, north threshold. PKM right flank suppressed. "
            "B Coy advancing terminal. Request 81mm SMOKE terminal western face NOW. OVER."),
        3: ("CCOY-6",    "EAGLE secured. CCOY now on LANCE axis eastward. "
            "IED belt confirmed grid 22.395E — bypassing via eastern track. "
            "Station estimated 20 min. Request 81mm FFE western station approach. OVER."),
        4: ("MOREAU-6",  "ALL STATIONS — IRON SKY IRON SKY IRON SKY. "
            "OBJ EAGLE and OBJ STATION secured. Consolidate now. "
            "A Coy: runway perimeter. B Coy: terminal. C Coy: station. "
            "2 BN: DZ reserve. 81mm: standby ILLUM pattern. WELL DONE. OUT."),
    }
    while True:
        await asyncio.sleep(1.5)
        ph_idx = phase_idx_state.get("idx", 0)
        if ph_idx == last_phase:
            continue
        last_phase = ph_idx
        if ph_idx not in phase_messages:
            continue
        callsign, text = phase_messages[ph_idx]
        sender = next((o for o in ops if o.callsign == callsign and o.token), None)
        if not sender:
            sender = next((o for o in ops if o.token), None)
        if sender:
            await api(client, "POST", "/messages", token=sender.token, json={
                "content": text, "message_type": "BROADCAST",
            })
            log.info("📻 [%s] %s", callsign, text[:80])


# ── Reset ────────────────────────────────────────────────────────────────────
async def reset_world(client: httpx.AsyncClient, admin_token: str) -> tuple[int, int, int]:
    n_obj = 0
    for o in (await api(client, "GET", "/tactical-objects", token=admin_token) or []):
        if o.get("type") in (ALL_TG_TYPES | NON_TG_TYPES):
            r = await api(client, "DELETE", f"/tactical-objects/{o['id']}", token=admin_token)
            if r is not None:
                n_obj += 1
    n_op = 0
    for o in (await api(client, "GET", "/opords", token=admin_token) or []):
        title  = o.get("title") if isinstance(o, dict) else ""
        opnum  = o.get("opord_number") if isinstance(o, dict) else ""
        if "IRON SKY" in (title or "") or "5RPC" in (opnum or ""):
            r = await api(client, "DELETE", f"/opords/{o['id']}", token=admin_token)
            if r is not None:
                n_op += 1
    sim_callsigns = {o.callsign for o in _regiment_orbat()}
    n_users = 0
    for op in (await api(client, "GET", "/operators", token=admin_token) or []):
        if (isinstance(op, dict) and op.get("callsign") in sim_callsigns
                and op.get("callsign") != ARGS.admin):
            r = await api(client, "DELETE", f"/operators/{op['id']}", token=admin_token)
            if r is not None:
                n_users += 1
    return n_obj, n_op, n_users


# ── Main ─────────────────────────────────────────────────────────────────────
async def amain() -> None:
    log.info("OPERATION IRON SKY — Kananga (DRC) airborne simulator")
    log.info("Backend: %s  (path prefix: %r)", BASE, PATH_PREFIX or "<none>")

    async with httpx.AsyncClient(base_url=ORIGIN, timeout=20.0) as client:
        # Health check
        try:
            h = await client.get(_p("/health"), timeout=5)
            log.info("Health: HTTP %d", h.status_code)
        except httpx.ConnectError as e:
            sys.exit(f"❌  Cannot reach {BASE} — {e}")
        except httpx.ConnectTimeout:
            sys.exit(f"❌  Timeout connecting to {BASE}")
        except httpx.HTTPError as e:
            log.warning("Health check failed: %s — continuing.", e)

        # Auth
        admin_token = await login(client, ARGS.admin, ARGS.password)
        if not admin_token:
            sys.exit(f"❌  Login failed for {ARGS.admin} @ {BASE}")
        sim_utils.save_backend(ARGS.backend)
        log.info("Authenticated as %s.", ARGS.admin)
        global MISSION_ID
        MISSION_ID = await sim_utils.create_mission_async(
            client, BASE, admin_token, ARGS.mission_name,
            map_center_lat=-5.900, map_center_lng=22.368, map_zoom=14)

        if ARGS.reset:
            n_obj, n_op, n_users = await reset_world(client, admin_token)
            log.info("Reset: %d TGs · %d OPORDs · %d sim operators removed.",
                     n_obj, n_op, n_users)

        # ── Static plant ──────────────────────────────────────────────────
        log.info("── Planting tactical objects …")
        items  = build_static_objects()
        sem    = asyncio.Semaphore(8)
        async def _post(item):
            async with sem:
                return await api(client, "POST", "/tactical-objects",
                                 token=admin_token, json=item)
        results  = await asyncio.gather(*[_post(it) for it in items])
        ok       = sum(1 for r in results if r)
        log.info("   %d / %d tactical objects planted.", ok, len(items))

        # ── OPORD ─────────────────────────────────────────────────────────
        log.info("── Creating OPORD …")
        op_payload = build_opord()
        op_resp    = await api(client, "POST", "/opords",
                               token=admin_token, json=op_payload)
        op_id      = op_resp.get("id", -1) if op_resp else -1
        if op_id > 0:
            log.info("✓ OPORD id=%d: %s", op_id, op_payload["title"])
        else:
            log.warning("OPORD creation failed — check backend logs.")

        if ARGS.no_live:
            log.info("--no-live set — static plant complete. Open the tactical map:")
            log.info("   Kananga Airport: %.4f, %.4f", AIRFIELD.lat, AIRFIELD.lon)
            log.info("   Train Station:   %.4f, %.4f", STATION.lat,  STATION.lon)
            return

        # ── Register live operators ────────────────────────────────────────
        log.info("── Registering regiment ORBAT …")
        orbat = _regiment_orbat()
        for op in orbat:
            await register_or_login(client, admin_token, op)
        active = [o for o in orbat if o.token]
        log.info("   %d / %d operators active.", len(active), len(orbat))

        if not active:
            log.error("No operators could be registered. Aborting live phase.")
            return

        # ── Phase clock state ─────────────────────────────────────────────
        phase_state = {"idx": 0}
        log.info("🪂  Φ1 AMBER — Airborne insertion begins. IRON SKY is LIVE.")
        log.info("    Kananga Airport  (OBJ EAGLE):   %.4f, %.4f",
                 AIRFIELD.lat, AIRFIELD.lon)
        log.info("    Train Station    (OBJ STATION): %.4f, %.4f",
                 STATION.lat,  STATION.lon)
        log.info("    DZ NORTH:                       %.4f, %.4f",
                 DZ_NORTH.lat, DZ_NORTH.lon)

        # ── Launch all coroutines ──────────────────────────────────────────
        tasks = [
            asyncio.create_task(
                advance_phase_clock(phase_state, ARGS.speed, not ARGS.once)),
            asyncio.create_task(
                inject_contacts(client, active, ARGS.speed)),
            asyncio.create_task(
                inject_spot_reports(client, active, ARGS.speed)),
            asyncio.create_task(
                inject_81mm_fire_missions(client, active, ARGS.speed, phase_state)),
            asyncio.create_task(
                inject_tic_alerts(client, active, ARGS.speed)),
            asyncio.create_task(
                inject_phase_radio(client, active, phase_state, ARGS.speed)),
        ]
        for op in active:
            tasks.append(asyncio.create_task(
                drive_operator(client, op, phase_state, ARGS.speed)))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            pass
        finally:
            for t in tasks:
                t.cancel()
            log.info("IRON SKY simulator stopped.")


def main() -> None:
    # Derive speed from --steps/--dt if --speed not explicitly given
    if ARGS.speed is None:
        if ARGS.dt is not None:
            ARGS.speed = TICK_SECONDS / ARGS.dt
        else:
            ARGS.speed = 2.0  # default

    timeout: float | None = (
        ARGS.steps * ARGS.dt
        if ARGS.steps is not None and ARGS.dt is not None
        else None
    )

    async def _run() -> None:
        try:
            if timeout:
                await asyncio.wait_for(amain(), timeout=timeout)
            else:
                await amain()
        except asyncio.TimeoutError:
            log.info("steps×dt duration elapsed — simulation complete")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("Stopped.")


if __name__ == "__main__":
    main()
