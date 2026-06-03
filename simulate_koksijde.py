#!/usr/bin/env python3
"""
Arrow Air-Assault Simulator — OPERATION HAMMERHEAD
===================================================

Coy RANGER (~135 PAX) conducts an air-assault with 2× CH-47F on Koksijde
Airfield (ICAO EBFN, 51.0900N 2.6531E, Belgium) to destroy the defending
enemy infantry company, seize the runway / control tower / hangars, and
link up with mech Coy VIPER (M2A3 Bradley) for long-term defence.

Friendly forces — Task Force RANGER
  Coy RANGER — 1/75 Ranger Bn
    HQ           : RANGER-6 (CO), RANGER-5 (XO), RANGER-7 (1SG), RANGER-FO
    1 PL (ME)    : RNG-1-6 (LDR) + 2× squads     → seize OBJ FALCON (control tower)
    2 PL         : RNG-2-6 (LDR) + 2× squads     → seize OBJ HAWK  (hangars)
    3 PL (SE/RES): RNG-3-6 (LDR) + WPN squad     → seize OBJ EAGLE (ammo dump)
    WPN det      : RNG-W6        (2× 60 mm mortars)
  Lift           : CH47-1, CH47-2 (160th SOAR — 2 sorties total)
  CAS / ISR      : SHADOW-21 (MQ-9 Reaper),  APACHE-22 (AH-64E)
  Reinforcement  : Coy VIPER (mech inf) — VIPER-6 + 3 PL, arrives by ground

Enemy forces — defending the airfieldad
  Mech Inf Coy (-)   ~120 PAX, BTR-80 IFV
  Tank Plt (3× T-72) hangar dispersal
  Mortar Sec         (2× 120 mm)
  ATGM tm × 2        (Kornet)
  MANPADS tm         (Igla)
  AAA section        (ZU-23-2)
  C2 in control tower

Phase plan:
  Φ0 (H-2)  Final brief at FOB; CH-47s loaded
  Φ1 (H-0)  CH-47s launch from FOB Lombardsijde (~51.150N 2.747E)
  Φ2 (H+12) CH-47s arrive at LZ EAGLE (south of runway, open polder)
  Φ3 (H+20) Touchdown; assault element pushes north onto airfield
  Φ4 (H+30) OBJ FALCON (control tower) — 1 PL ME
  Φ5 (H+45) OBJ HAWK  (hangars)        — 2 PL
  Φ6 (H+60) OBJ EAGLE (ammo dump)      — 3 PL
  Φ7 (H+90) Coy RANGER consolidates perimeter; CH-47s exfil
  Φ8 (H+180) Coy VIPER linkup from south via N396
  Φ9 (H+240) Combined defence

Works like simulate.py / simulate_north_wind.py:
  • Defaults to the production backend  https://78.21.255.210:6200/api
  • Async HTTP via httpx
  • Plants OPORD + tactical control graphics + enemy ORBAT
  • Registers live operators; CH-47s fly in from FOB, Rangers seize
    objectives, Coy VIPER arrives by ground for linkup
  • Periodic SPOT reports, contact marks, fire missions, TIC alerts

Run:
  uv run python simulate_koksijde.py
  uv run python simulate_koksijde.py --backend http://192.168.0.240:6001
  uv run python simulate_koksijde.py --speed 4
  uv run python simulate_koksijde.py --no-live
  uv run python simulate_koksijde.py --reset
  uv run python simulate_koksijde.py --no-move
  uv run python simulate_koksijde.py --steps 60 --dt 1.5
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
from dataclasses import dataclass
from typing import Optional

import httpx

import sim_utils

# ── CLI / persistent config ─────────────────────────────────────────────────
DEFAULT_BACKEND = (
    os.environ.get("ARROW_BACKEND_URL")
    or sim_utils.load_saved_backend()
    or "https://78.21.255.210:6200/api"
)

parser = argparse.ArgumentParser(description="Arrow — OPERATION HAMMERHEAD (Koksijde air-assault)")
parser.add_argument("--backend",  default=DEFAULT_BACKEND,
                    help=f"Backend base URL (default: {DEFAULT_BACKEND})")
parser.add_argument("--admin",    default="benoit",   help="Seed ADMIN callsign")
parser.add_argument("--password", default="ranger14", help="Seed ADMIN password")
parser.add_argument("--reset",    action="store_true",
                    help="Wipe TGs/enemies/POIs, prior HAMMERHEAD OPORD, overlays, sim operators first")
parser.add_argument("--no-live",  action="store_true",
                    help="Plant static OPORD + tactical objects then exit")
parser.add_argument("--no-move",  action="store_true", dest="no_live",
                    help="Alias for --no-live: plant plan only, skip movement simulation")
parser.add_argument("--skip-snapshots", action="store_true",
                    help="Don't request server-side OSM-tile snapshots")
parser.add_argument("--speed",    type=float, default=None,
                    help="Time multiplier (default 2× → full op ≈ 4 min)")
parser.add_argument("--steps",    type=int, default=None,
                    help="Movement steps. If given with --dt, derives speed (speed = TICK_SECONDS / dt) "
                         "and limits run to steps × dt real seconds.")
parser.add_argument("--dt",       type=float, default=None,
                    help="Seconds between steps. If given with --steps, derives speed and total duration.")
parser.add_argument("--loop",     action="store_true", default=True,
                    help="After Φ9 loop back to Φ1 so the demo keeps running (default on)")
parser.add_argument("--once",     dest="loop", action="store_false",
                    help="Stop after Φ9 instead of looping")
parser.add_argument("--mission-name", default="Operation Hammerhead",
                    help="Mission name to create or adopt (default: Operation Hammerhead)")
ARGS = parser.parse_args()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("hh")

BASE = ARGS.backend.rstrip("/")
MISSION_ID: int | None = None

ORIGIN, PATH_PREFIX = sim_utils.split_base(BASE)


# ── Tactical object type sets ───────────────────────────────────────────────
POINT_TG_TYPES = {"ATK_AXIS", "COUNTERATTACK", "AMBUSH", "DEF_AREA",
                  "BLOCK", "BYPASS", "WITHDRAW"}
LINE_TG_TYPES  = {"BOUNDARY", "FLET", "FLOT", "PHASE_LINE"}
POLY_TG_TYPES  = {"OBJ_AREA", "ZONE"}
ALL_TG_TYPES   = POINT_TG_TYPES | LINE_TG_TYPES | POLY_TG_TYPES
NON_TG_TYPES   = {"ENEMY", "POI", "MARKER", "OBJECTIVE", "ROUTE"}


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


# ── Koksijde Airfield (EBFN) — real coordinates ─────────────────────────────
# Centre of mass of the airfield; runway 06/24, length ~2895 m.
AIRFIELD     = LatLon(51.0900, 2.6531)
RWY_W_END    = LatLon(51.0937, 2.6437)     # west threshold (RWY 06)
RWY_E_END    = LatLon(51.0858, 2.6624)     # east threshold (RWY 24)
CONTROL_TOWER = LatLon(51.0897, 2.6486)    # OBJ FALCON
HANGAR_NW    = LatLon(51.0928, 2.6470)     # OBJ HAWK
AMMO_DUMP    = LatLon(51.0867, 2.6620)     # OBJ EAGLE
# LZ EAGLE — open polder ~1.2 km SE of the runway threshold; far enough that
# touchdown isn't directly observed from the control tower (line of trees).
LZ_EAGLE     = LatLon(51.0790, 2.6610)
# LZ FALCON — alternate, NW of the runway (used by Wave 2 if RWY 06 is hot)
LZ_FALCON    = LatLon(51.0985, 2.6390)
# FOB Lombardsijde — coastal Belgian Army base ~7 km E of the AO
FOB_LAUNCH   = LatLon(51.1480, 2.7470)
# Reinforcement Coy VIPER assembles south at N396 junction near Veurne
VIPER_AA     = LatLon(51.0480, 2.6420)
# RP RED — where VIPER picks up the linkup south of the airfield
RP_RED       = LatLon(51.0760, 2.6530)


# ── Operation phases ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Phase:
    idx: int
    code: str
    label: str
    seconds_at_speed_1: float    # how long this phase lasts at speed=1

PHASES: list[Phase] = [
    Phase(0, "PREP",       "Final brief at FOB Lombardsijde; CH-47s loaded",                30.0),
    Phase(1, "LAUNCH",     "CH-47s launch from FOB; nap-of-the-earth flight to LZ EAGLE",   30.0),
    Phase(2, "INFIL",      "CH-47s arrive at LZ EAGLE; touchdown",                          20.0),
    Phase(3, "ASSAULT",    "Rangers push N from LZ; suppress airfield perimeter",           30.0),
    Phase(4, "OBJ_FALCON", "1 PL seizes OBJ FALCON (control tower)",                        30.0),
    Phase(5, "OBJ_HAWK",   "2 PL seizes OBJ HAWK (hangars / T-72 dispersal)",               30.0),
    Phase(6, "OBJ_EAGLE",  "3 PL seizes OBJ EAGLE (ammo dump)",                             25.0),
    Phase(7, "CONSOLIDATE","Coy RANGER consolidates perimeter; CH-47s exfil empty",         30.0),
    Phase(8, "LINKUP",     "Coy VIPER ground-moves to RP RED, conducts linkup",             40.0),
    Phase(9, "DEFEND",     "Combined RANGER + VIPER defence; airhead established",          60.0),
]


# ── HTTP plumbing ───────────────────────────────────────────────────────────
def _p(path: str) -> str:
    if not PATH_PREFIX or path.startswith(PATH_PREFIX + "/") or path == PATH_PREFIX:
        return path
    return PATH_PREFIX + path

_API_FAIL_COUNT = 0

async def api(client: httpx.AsyncClient, method: str, path: str,
              token: str = "", **kwargs) -> Optional[dict]:
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
        log.warning("login %s → %d %s", callsign, r.status_code, r.text[:120])
    except Exception as exc:
        log.warning("login %s → %s", callsign, exc)
    return None


# ── Tactical-object builder ─────────────────────────────────────────────────
def build_tactical_objects() -> list[dict]:
    """All planted tactical objects: OBJ polys, LZs, axes, FLET, enemy ORBAT,
    friendly POIs, defence perimeter, phase lines, boundaries."""
    items: list[dict] = []
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

    # ── 1. Airfield outline (large OBJ polygon) ───────────────────────────
    af_poly = [
        AIRFIELD.offset_m(  500, -1_500),
        AIRFIELD.offset_m(  500,  1_500),
        AIRFIELD.offset_m( -400,  1_500),
        AIRFIELD.offset_m( -400, -1_500),
    ]
    items.append(poly("OBJ_AREA", af_poly, echelon="COY",
                      notes="OBJ HAMMERHEAD — Koksijde Airfield (EBFN) — Coy RANGER objective"))

    # OBJECTIVE marker (🚩) at the airfield centre — visible at low zoom so
    # the BC can see "Coy RANGER seizes EBFN" even when zoomed out across BE.
    # Notes are formatted as ``title\ndescription\nMGRS:…`` because the web
    # objective renderer pulls the first line as the title.
    items.append({
        "type": "OBJECTIVE", "symbol_code": "",
        "latitude": AIRFIELD.lat, "longitude": AIRFIELD.lon,
        "affiliation": "FRIENDLY", "echelon": "COY",
        "notes": ("OBJ HAMMERHEAD\n"
                  "Coy RANGER air-assault on Koksijde Airfield (EBFN).\n"
                  "Seize runway, control tower, hangars; defeat EN inf coy."),
        "rotation": 0.0, "geometry": "", "visibility": "COMPANY",
    })

    # ── 2. Sub-objectives — OBJ_AREA polygon + OBJECTIVE flag at the
    #     centroid so they're prominent at any zoom.
    for centre, name, ech, who, narrative in [
        (CONTROL_TOWER, "FALCON", "PL", "1 PL ME",
         "Seize control tower intact; preserve EN C2 documents/comms."),
        (HANGAR_NW,     "HAWK",   "PL", "2 PL",
         "Clear hangar complex; destroy 3× T-72 in revetments before CT-ATK."),
        (AMMO_DUMP,     "EAGLE",  "SQD","3 PL",
         "Secure ammo + fuel dump intact; deny EN demolition."),
    ]:
        pts = [centre.offset_m( 120, -150), centre.offset_m( 120,  150),
               centre.offset_m(-120,  150), centre.offset_m(-120, -150)]
        items.append(poly("OBJ_AREA", pts, echelon=ech,
                          notes=f"OBJ {name} — {who}"))
        items.append({
            "type": "OBJECTIVE", "symbol_code": "",
            "latitude": centre.lat, "longitude": centre.lon,
            "affiliation": "FRIENDLY", "echelon": ech,
            "notes": f"OBJ {name}\n{who} — {narrative}",
            "rotation": 0.0, "geometry": "", "visibility": "COMPANY",
        })

    # ── 3. Landing zones — proper LZ graphics ────────────────────────────
    # Each LZ gets:
    #   (a) a 16-pt circular ZONE polygon (NATO LZ depiction radius ≈ 80 m)
    #   (b) a heliport POI marker at the centre (HMM-Class symbol)
    #   (c) a touchdown-axis ATK_AXIS arrow showing the direction CH-47s
    #       face on touchdown — for LZ EAGLE that's NORTH (facing OBJ).
    def _circle(centre: LatLon, radius_m: float, n: int = 16) -> list[LatLon]:
        out: list[LatLon] = []
        for i in range(n):
            ang = 2 * math.pi * i / n
            out.append(centre.offset_m(radius_m * math.cos(ang),
                                        radius_m * math.sin(ang)))
        return out

    LZ_DEFS = [
        (LZ_EAGLE,  "EAGLE",  80, NORTH,
         "PRI LZ — initial assault element (2× CH-47F, Wave 1)"),
        (LZ_FALCON, "FALCON", 70, NORTH,
         "ALT LZ — only if RWY 06 hot or LZ EAGLE compromised"),
    ]
    for lz, name, radius, heading, role in LZ_DEFS:
        # (a) circular ZONE polygon
        items.append(poly("ZONE", _circle(lz, radius), echelon="COY",
                          notes=f"LZ {name} — {role}"))
        # (b) heliport POI in the centre — uses the MIL-STD-2525C "Helicopter
        #     Landing Zone" symbol (SFGPIBA-H----) — the H modifier is the
        #     standard helo marking. We fall back to airbase if the renderer
        #     doesn't know the H modifier (still gets a recognisable icon).
        items.append({"type": "POI", "symbol_code": "SFGPIBA-----",
                      "latitude": lz.lat, "longitude": lz.lon,
                      "affiliation": "FRIENDLY", "echelon": "COY",
                      "notes": f"LZ {name} (helo touchdown) — {role}",
                      "rotation": 0.0, "geometry": "",
                      "visibility": "COMPANY"})
        # (c) touchdown direction arrow — CH-47 nose points this way on landing
        items.append(tg("ATK_AXIS", *lz.bearing_m(heading, radius + 40).as_pair(),
                        echelon="COY", rotation=heading,
                        notes=f"LZ {name} touchdown axis — CH-47 nose {int(heading):03d}°"))
        # (d) Inner "touchdown" octagon at half radius — strengthens the
        #     visual centre of the LZ at high zoom so the BC sees both the
        #     hover-cone (outer circle) and the rotor footprint (inner).
        items.append(poly("ZONE", _circle(lz, radius * 0.45, n=8),
                          echelon="",
                          notes=f"LZ {name} — rotor footprint"))
        # (e) MARKER point labelled "LZ {name}" so the text is unambiguous
        #     at any zoom (the heliport POI shows the symbol; this one
        #     gives the textual call-out).
        items.append({"type": "MARKER", "symbol_code": "",
                      "latitude": lz.lat, "longitude": lz.lon,
                      "affiliation": "FRIENDLY", "echelon": "COY",
                      "notes": f"LZ {name}",
                      "rotation": 0.0, "geometry": "",
                      "visibility": "COMPANY"})

    # ── 4. Flight route AA → LZ ──────────────────────────────────────────
    items.append(line("BOUNDARY", [
        FOB_LAUNCH,
        FOB_LAUNCH.offset_m(-3_000, -3_000),       # nap-of-earth dog-leg over polders
        LZ_EAGLE.offset_m( 1_500,  2_000),
        LZ_EAGLE,
    ]))
    items[-1]["affiliation"] = "FRIENDLY"
    items[-1]["echelon"]     = "COY"
    items[-1]["notes"]       = ("AIR ROUTE TURQUOISE — CH-47 ingress; "
                                "NOE flight, max 60 ft AGL, hugs the canal")

    # ── 5. Attack axes from LZ EAGLE onto objectives ─────────────────────
    items.append(tg("ATK_AXIS", *LZ_EAGLE.bearing_m(NORTH, 200).as_pair(),
                    echelon="PL", rotation=350.0,
                    notes="1 PL ME axis — LZ EAGLE → OBJ FALCON (control tower)"))
    items.append(tg("ATK_AXIS", *LZ_EAGLE.bearing_m(NORTH, 200).bearing_m(WEST, 150).as_pair(),
                    echelon="PL", rotation=335.0,
                    notes="2 PL axis — LZ EAGLE → OBJ HAWK (hangars)"))
    items.append(tg("ATK_AXIS", *LZ_EAGLE.bearing_m(NORTH, 200).bearing_m(EAST, 150).as_pair(),
                    echelon="PL", rotation=20.0,
                    notes="3 PL axis — LZ EAGLE → OBJ EAGLE (ammo dump)"))

    # ── 6. Phase lines ───────────────────────────────────────────────────
    pl_assault = AIRFIELD.bearing_m(SOUTH, 600)
    pl_loa     = AIRFIELD.bearing_m(NORTH, 600)
    items.append(line("PHASE_LINE",
                      [pl_assault.bearing_m(WEST, 1_800), pl_assault.bearing_m(EAST, 1_800)]))
    items[-1]["echelon"] = "COY"
    items[-1]["notes"]   = "PL HAMMER — line of departure (south perimeter fence)"
    items.append(line("PHASE_LINE",
                      [pl_loa.bearing_m(WEST, 1_800), pl_loa.bearing_m(EAST, 1_800)]))
    items[-1]["echelon"] = "COY"
    items[-1]["notes"]   = "PL ANVIL — limit of advance (north perimeter)"

    # ── 7. Enemy FLET — runway centreline (where they hold the airfield)
    items.append(line("FLET", [RWY_W_END, RWY_E_END]))
    items[-1]["affiliation"] = "ENEMY"
    items[-1]["echelon"]     = "COY"
    items[-1]["notes"]       = "FLET — EN mech inf coy holds runway"

    # ── 8. Enemy ORBAT inside the airfield ───────────────────────────────
    enemy = [
        ("Enemy mech inf coy HQ",     "SHGPUCI-----", CONTROL_TOWER.offset_m( 100, -50)),
        ("Enemy mech inf plt (BTR-80)","SHGPUCIM----", AIRFIELD.offset_m(  100,  -300)),
        ("Enemy mech inf plt (BTR-80)","SHGPUCIM----", AIRFIELD.offset_m( -100,   400)),
        ("Enemy mech inf plt (dismount)","SHGPUCIZ---", AIRFIELD.offset_m(  150,   200)),
        ("Enemy tank plt (3× T-72)",  "SHGPUCAA----", HANGAR_NW.offset_m(   0,    100)),
        ("Enemy 120 mm mortar sec",   "SHGPUCFHE---", AIRFIELD.offset_m( -350,  -800)),
        ("Enemy ATGM team (Kornet)",  "SHGPUCAA---F", CONTROL_TOWER.offset_m( 80,   50)),
        ("Enemy ATGM team (Kornet)",  "SHGPUCAA---F", AMMO_DUMP.offset_m(   60,  -120)),
        ("Enemy MANPADS (Igla)",      "SHGPUCDS----", AIRFIELD.offset_m( -200,    50)),
        ("Enemy AAA sec (ZU-23-2)",   "SHGPUCDH----", AIRFIELD.offset_m(  -50,  1_100)),
        ("Enemy logistics / fuel",    "SHGPISS-----", AMMO_DUMP.offset_m(  150,    50)),
    ]
    for desc, sidc, ll in enemy:
        items.append({"type": "ENEMY", "symbol_code": sidc,
                      "latitude": ll.lat, "longitude": ll.lon,
                      "affiliation": "ENEMY",
                      "notes": f"EN inf coy · {desc} · EBFN",
                      "echelon": "", "rotation": 0.0, "geometry": "",
                      "visibility": "COMPANY"})

    # Enemy DEF_AREA polygon (hasty defence ring around the airfield)
    en_def = [AIRFIELD.offset_m( 300, -1_200), AIRFIELD.offset_m( 300,  1_200),
              AIRFIELD.offset_m(-300,  1_200), AIRFIELD.offset_m(-300, -1_200)]
    items.append(poly("DEF_AREA", en_def,
                      affiliation="ENEMY", echelon="COY", rotation=NORTH,
                      notes="EN coy hasty defence — perimeter fence + revetments"))

    # ── 9. Friendly defensive perimeter we'll occupy after seizing ───────
    # 3 PL BPs around the airfield once cleared: north / west / east sectors
    def bp(lat_off, lon_off, name, sector):
        c = AIRFIELD.offset_m(lat_off, lon_off)
        return tg("DEF_AREA", c.lat, c.lon, echelon="PL", rotation=NORTH,
                  notes=f"BP {name} — {sector}")

    items.append(bp( 400,    0,  "ALPHA", "1 PL — north sector (covers AA from N396)"))
    items.append(bp(-200, -800,  "BRAVO", "2 PL — west sector (covers RWY 06 threshold)"))
    items.append(bp(-200,  800,  "CHARLIE", "3 PL — east sector (covers RWY 24 threshold)"))

    # CT-ATK reserve in centre (WPN det + CO HQ)
    items.append(tg("COUNTERATTACK", *AIRFIELD.bearing_m(SOUTH, 150).as_pair(),
                    echelon="SEC", rotation=NORTH,
                    notes="WPN det + CO HQ — CT-ATK reserve in centre"))

    # ── 10. Friendly POIs — Coy support nodes ────────────────────────────
    pois = [
        ("RANGER-6 CO TAC",        "SFGPUH------", CONTROL_TOWER.offset_m(-200,    0)),
        ("Coy CCP",                "SFGPIME-----", LZ_EAGLE.offset_m(   100,    0)),
        ("BAS / Role 1 (medic)",   "SFGPIMS-----", LZ_EAGLE.offset_m(    50,   100)),
        ("Ammo / resupply point",  "SFGPIRP-----", LZ_EAGLE.offset_m(   -50,  -100)),
        ("60 mm mortar PA (WPN det)","SFGPUCFHE---", AIRFIELD.offset_m(-300,   200)),
        ("Coy FO position",        "SFGPUUS-----", CONTROL_TOWER.offset_m( 50, -120)),
        ("HLZ — MEDEVAC alternate","SFGPIBA-----", AIRFIELD.offset_m(   0,    800)),
    ]
    for desc, sidc, ll in pois:
        items.append({"type": "POI", "symbol_code": sidc,
                      "latitude": ll.lat, "longitude": ll.lon,
                      "affiliation": "FRIENDLY",
                      "notes": f"Coy RANGER · {desc}",
                      "echelon": "", "rotation": 0.0, "geometry": "",
                      "visibility": "COMPANY"})

    # ── 11. VIPER reinforcement assembly area + linkup route ─────────────
    aa = [VIPER_AA.offset_m(  60, -120), VIPER_AA.offset_m(  60,  120),
          VIPER_AA.offset_m( -60,  120), VIPER_AA.offset_m( -60, -120)]
    items.append(poly("ZONE", aa, echelon="COY",
                      notes="AA VIPER — Coy VIPER assembly area (M2A3 Bradley)"))
    items.append({"type": "POI", "symbol_code": "SFGPIBA-----",
                  "latitude": RP_RED.lat, "longitude": RP_RED.lon,
                  "affiliation": "FRIENDLY",
                  "notes": "RP RED — Coy VIPER ↔ Coy RANGER linkup point",
                  "echelon": "", "rotation": 0.0, "geometry": "",
                  "visibility": "COMPANY"})
    items.append(line("BOUNDARY", [VIPER_AA, VIPER_AA.offset_m(2_000, 0),
                                   RP_RED, AIRFIELD.bearing_m(SOUTH, 200)]))
    items[-1]["affiliation"] = "FRIENDLY"
    items[-1]["echelon"]     = "COY"
    items[-1]["notes"]       = "VIPER axis north — N396 → RP RED → airfield"

    return items


# ── OPORD ───────────────────────────────────────────────────────────────────
def build_opord() -> dict:
    return dict(
        title="OPORD 26-HH-01 — OPERATION HAMMERHEAD",
        opord_number="OPORD 26-HH-01",
        dtg="200400ZMAY26",
        classification="UNCLASSIFIED//FOUO  ·  EXERCISE",
        references=(
            "a. Map: BEL NGI 1:50.000 sheet 19/3-4 'Koksijde-Veurne'\n"
            "b. NATO Air-Assault doctrine — ATP-3.2.2.1\n"
            "c. EBFN airfield diagram (BEL Air Component, NOTAM A0042/26)\n"
            "d. TF RANGER SOP 75-3 (Helo Insertion)\n"
            "e. Annex C — Operations Overlay\n"
            "f. Annex F — Air Movement Plan\n"
            "g. Annex K — Linkup Plan (VIPER)"
        ),
        task_organization=(
            "TASK FORCE RANGER (Coy RANGER, 1/75 RGR) — ENABLING TASK 1 HAMMERHEAD\n"
            "  HQ           : RANGER-6 (CO), RANGER-5 (XO), RANGER-7 (1SG), RANGER-FO\n"
            "  1 PL  (ME)   : RNG-1-6 LDR + 3× rifle squads → seize OBJ FALCON\n"
            "  2 PL         : RNG-2-6 LDR + 3× rifle squads → seize OBJ HAWK\n"
            "  3 PL (SE/RES): RNG-3-6 LDR + 2× rifle + WPN sqd → seize OBJ EAGLE\n"
            "  WPN det      : RNG-W6 — 2× 60 mm mortar; M240B × 4; Javelin × 2\n"
            "  CH-47F lift  : CH47-1 + CH47-2 (160th SOAR DET)\n"
            "ATTACHMENTS:\n"
            "  · SHADOW-21 — MQ-9 ISR/CAS (GS, 4 hr on-station)\n"
            "  · APACHE-22 — AH-64E ARMED RECCE (DS to ME, on-call 5 NM south)\n"
            "  · CIMIC TM — BEL host-nation LO with KMar\n"
            "REINFORCEMENT (arrives H+180 by ground):\n"
            "  · Coy VIPER (mech inf) — VIPER-6 CO + 3× rifle PL (M2A3 Bradley)\n"
            "DETACHMENTS: nil"
        ),
        situation={
            "terrain": (
                "OBJ HAMMERHEAD is Koksijde Airfield (ICAO EBFN, 51.0900N 2.6531E), "
                "a single-runway BEL Air Component base on the Belgian coast 5 km W "
                "of Nieuwpoort. Runway 06/24, 2,895 m. OAKOC: Observation excellent "
                "across flat polders; control tower dominates the airfield (15 m AGL). "
                "Cover & concealment NIL on the runway; hangars & revetments provide "
                "good cover at OBJ HAWK; dune line N of the field offers concealment. "
                "Obstacles: 2.4 m perimeter security fence (cut on H-Hour), drainage "
                "ditches along S edge. KEY TERRAIN: control tower (OBJ FALCON), "
                "hangar complex (OBJ HAWK), ammo/fuel dump (OBJ EAGLE), runway "
                "centreline (denies EN reinforcement)."
            ),
            "weather": (
                "BMNT 0427 / Sunrise 0606 / Sunset 2147 / EENT 2326. Illum 4% "
                "(new moon set 1832 — favours night infil). Temp 9–17°C. "
                "Wind W 12–18 kt; below CH-47 brown-out limits at LZ EAGLE. "
                "Vis >10 km, ceiling unrestricted; light data favours H-Hour 0400Z."
            ),
            "enemy_cds": (
                "Defending: Mech infantry company (~120 PAX) augmented by tank plt "
                "(3× T-72), 1× 120 mm mortar section, 2× ATGM teams (Kornet), "
                "1× MANPADS (Igla), 1× AAA section (ZU-23-2). C2 in control tower. "
                "Strength ~85%; morale MEDIUM; defending in hasty perimeter."
            ),
            "enemy_mlcoa": (
                "Hold airfield from prepared positions; mortar fires on LZ EAGLE "
                "within 8 min of touchdown; T-72 plt CT-ATKs from hangar dispersal "
                "if FALCON is lost; ATGM ambush along runway centreline if CH-47s "
                "attempt second wave."
            ),
            "enemy_mdcoa": (
                "Pre-emptive spoiling — leak intel of inbound flight via SIGINT, "
                "ambush LZ EAGLE at touchdown with ZU-23 + mortar TRP, then "
                "withdraw mech plts to hangar complex for prepared defence."
            ),
            "civil": (
                "Civilian populace IVO Koksijde ~22k. NO-STRIKE: town centre, "
                "Onze-Lieve-Vrouw church, Sint-Idesbald primary school. NEO routes "
                "pre-cleared by KMar. Civil airspace closed under NOTAM A0042/26."
            ),
            "friendly_higher": (
                "TF RANGER is BN ME for Operation NORTH BREAKER (BN attack to seize "
                "the Belgian coastal salient). Two adjacent companies (CO STORM "
                "isolates Veurne south, CO SWORD demonstrates west of Lo-Reninge) "
                "fix EN reserves IVO H-Hour."
            ),
            "friendly_adjacent": (
                "Coy STORM — south flank, 8 km E. Coy SWORD — west, 12 km. "
                "BEL host-nation Quick Reaction Force at FOB Lombardsijde on 30-min "
                "alert (Pandur APCs) for QRF / NEO support."
            ),
        },
        mission=(
            "TF RANGER air-assaults with 2× CH-47F at 200400ZMAY26 to seize "
            "Koksijde Airfield (EBFN), destroy the defending EN mech inf company, "
            "and link up with Coy VIPER NLT H+180 IO establish a coastal airhead "
            "for follow-on BN operations into the Belgian coastal sector."
        ),
        execution={
            "intent_purpose": (
                "Establish a usable airhead on the Belgian coast within 4 hours so "
                "the BN can flow follow-on forces by air and rotary lift into the AO."
            ),
            "intent_key_tasks": (
                "1) Seize control tower (FALCON) intact — preserves C2 for follow-on.\n"
                "2) Destroy EN tank plt at OBJ HAWK before it can CT-ATK.\n"
                "3) Secure OBJ EAGLE (ammo/fuel) IO deny EN demolition.\n"
                "4) Linkup with Coy VIPER at RP RED NLT H+180.\n"
                "5) Hand over runway in usable state for C-130 follow-on lift NLT H+240."
            ),
            "intent_end_state": (
                "Coy RANGER + Coy VIPER occupy airfield perimeter; EN coy destroyed "
                "or withdrawn; runway cleared and certified for fixed-wing landing; "
                "TF combat power ≥75%."
            ),
            "conops_maneuver": (
                "10-phase air-assault. Single-lift insertion (2× CH-47F), 3-PL ground "
                "assault, consolidate, then mech linkup.\n"
                "Φ0 PREP        — final brief at FOB Lombardsijde; CH-47s loaded.\n"
                "Φ1 LAUNCH      — CH-47s launch from FOB; NOE flight along Air Route TURQUOISE.\n"
                "Φ2 INFIL       — touchdown LZ EAGLE; PL LDRs confirm orientation.\n"
                "Φ3 ASSAULT     — Coy crosses PL HAMMER (LD); breach perimeter fence.\n"
                "Φ4 OBJ FALCON  — 1 PL ME clears control tower; capture EN C2.\n"
                "Φ5 OBJ HAWK    — 2 PL clears hangar complex; destroy T-72 plt.\n"
                "Φ6 OBJ EAGLE   — 3 PL clears ammo/fuel dump intact.\n"
                "Φ7 CONSOLIDATE — Coy occupies BPs ALPHA/BRAVO/CHARLIE; CH-47s exfil.\n"
                "Φ8 LINKUP      — Coy VIPER from AA → RP RED → linkup via N396.\n"
                "Φ9 DEFEND      — Combined RANGER+VIPER defend airhead; cert RWY."
            ),
            "conops_fires": (
                "PR effort: 1 PL through Φ4, then 2 PL Φ5. Targets pre-planned:\n"
                "  T01 (suppressive) — EN mech plt vic AIRFIELD (-100, +400)\n"
                "  T02 (FFE)         — EN mortar section AIRFIELD (-350, -800)\n"
                "  T03 (smoke)       — control tower northern approach\n"
                "  T04 (FPF)         — south perimeter fence (defensive)\n"
                "APACHE-22 on-call for armour at OBJ HAWK. SHADOW-21 continuous "
                "TFOA over the airfield from H-30 to H+240. NO-STRIKE: town, "
                "school, church."
            ),
            "conops_main_effort": (
                "ME: 1 PL through Φ4 (control tower seizure — preserves C2 capture). "
                "Shifts to 2 PL for Φ5 (destroy T-72 plt before CT-ATK)."
            ),
            "conops_phasing": "PREP → LAUNCH → INFIL → ASSAULT → 3× OBJ → CONS → LINKUP → DEFEND",
            "tasks": (
                "1 PL (ME): seize OBJ FALCON; preserve EN C2 documents/comms.\n"
                "2 PL: seize OBJ HAWK; destroy 3× T-72 IPB by Javelin or M203.\n"
                "3 PL (SE/RES): seize OBJ EAGLE; secure ammo/fuel intact; BPT CT-ATK.\n"
                "WPN det: 60 mm mortar fires on T01–T03; on order shift to FPF (T04).\n"
                "FO: control SHADOW-21 ISR and call APACHE-22 if armour reveals.\n"
                "CH47-1/2: NOE ingress; offload Wave 1; exfil empty NLT H+10.\n"
                "Coy VIPER: SP from AA VIPER H+90; passage of lines through CO STORM "
                "south recon screen; linkup at RP RED H+150; integrate into "
                "perimeter NLT H+180."
            ),
            "coord_timings": (
                "H-72 OPORD issue. H-48 ROC drill (sand table) at FOB.\n"
                "H-24 final intel update; APACHE-22 + SHADOW-21 mission planning.\n"
                "H-2  PCC/PCI complete; CH-47 load-out begins.\n"
                "H-0  (200400ZMAY26) CH-47 launch from FOB.\n"
                "H+12 LZ EAGLE touchdown.\n"
                "H+30 OBJ FALCON.\n"
                "H+45 OBJ HAWK.\n"
                "H+60 OBJ EAGLE.\n"
                "H+90 Coy RANGER consolidated.\n"
                "H+180 NLT linkup with VIPER.\n"
                "H+240 NLT RWY cert for C-130 follow-on."
            ),
            "coord_ccir": (
                "PIR: 1) Location of T-72 plt at H-Hour. 2) EN MANPADS posture "
                "(threat to CH-47 ingress). 3) Indications of EN reinforcement "
                "from Bredene.\n"
                "FFIR: 1) Any CH-47 loss. 2) Coy combat power <70%. 3) Loss of FO. "
                "4) Linkup delay >60 min."
            ),
            "coord_roe": (
                "Standing NATO ROE per AJP-3.4. Hostile act/intent required. PID "
                "before engagement. Surrender opportunities offered IAW Geneva. "
                "NO-STRIKE list briefed at each squad."
            ),
            "coord_risk": (
                "HIGH — air-assault, single lift, hostile MANPADS environment. "
                "Controls: NOE flight; SHADOW-21 SEAD ISR; APACHE-22 IRT 5 NM south; "
                "alternate LZ FALCON; medical Role 2 LM at LZ EAGLE within 15 min "
                "of touchdown; QRF (BEL Pandur) at FOB on 30-min alert."
            ),
            "coord_fscm": (
                "FSCL — runway centreline. CFL — PL HAMMER (LD). "
                "NFA — town of Koksijde, school, church (per NO-STRIKE list).\n"
                "RFA — LZ EAGLE during touchdown window (H-2 to H+15)."
            ),
        },
        sustainment={
            "supply": (
                "Wave 1 carries 1× CDS basic load (1 ammo, 1 medical, 1 water/MRE). "
                "Resupply by ground via VIPER convoy at H+180; subsequent by C-130 "
                "into RWY after H+240."
            ),
            "transport": (
                "Lift: 2× CH-47F (1 sortie each — total ~70 PAX combat-loaded). "
                "Ground: Coy VIPER 4× M2A3 Bradley + 6× HMMWV + 2× LMTV."
            ),
            "maintenance": (
                "UMCP at LZ EAGLE post-Φ7. CH-47 service ceiling unrestricted; "
                "rotor inspection at FOB on return."
            ),
            "personnel": "Strength reports H-Hour / H+30 / H+90 / H+180 / H+240.",
            "epw": (
                "Detainee CCP at LZ EAGLE; biometric enrolment (HIIDE) before "
                "handover to BEL KMar at H+180."
            ),
            "casevac": (
                "CCP at LZ EAGLE. Ground MEDEVAC by VIPER M113 ambulance. "
                "Air MEDEVAC via dedicated NH90 (BEL host-nation 39 SAR Sqn — "
                "their home base, so already on-site capability) on 15-min alert."
            ),
            "medevac": (
                "Role 1 at LZ EAGLE (Coy medic + BAS). Role 2 LM at FOB Lombardsijde. "
                "Role 3 at AZ Sint-Jan Brugge (15 min by helo)."
            ),
        },
        command_signal={
            "command": (
                "CDR with 1 PL during seizure (Φ3–Φ4); XO at LZ EAGLE running CCP. "
                "1SG at Coy CCP."
            ),
            "succession": (
                "RANGER-6 → RANGER-5 (XO) → 1 PL LDR → 2 PL LDR → 3 PL LDR."
            ),
            "control": (
                "SITREP every 15 min from H-Hour to H+90, then every 30 min. "
                "Phase-complete report on each PL/OBJ. Immediate CASEVAC/troop-loss."
            ),
            "pace_primary":     "VHF SINCGARS — CO net 38.275 / FH-A",
            "pace_alternate":   "MBITR PRC-148 secondary 38.300",
            "pace_contingency": "SATCOM TACSAT CH 106 (TF RANGER) / CH 109 (CH-47)",
            "pace_emergency":   "Pyro: red star = withdraw to LZ EAGLE; green smoke = LZ marked",
            "callsigns": (
                "BLACK 6 (CDR), RED (1 PL), WHITE (2 PL), BLUE (3 PL), "
                "WPN (mortars), HAWK (FO), CHALK 1/2 (CH-47s), SHADOW 21 (MQ-9), "
                "APACHE 22 (AH-64E), VIPER 6 (mech CO)."
            ),
            "password": "Challenge: HAMMER / Reply: ANVIL / Running: KOKSIJDE",
        },
    )


def opord_snapshots() -> list[tuple[str, list[float], int, str]]:
    af = AIRFIELD
    out: list[tuple[str, list[float], int, str]] = []
    # Wide overview — airfield + LZ + FOB
    out.append(("AO overview — FOB Lombardsijde → Koksijde EBFN",
                [51.04, 2.55, 51.17, 2.78], 11,
                "Air Route TURQUOISE NOE from FOB to LZ EAGLE; Coy VIPER ground "
                "axis along N396 from south."))
    out.append(("Airfield close-up — OBJ HAMMERHEAD",
                [af.lat - 0.012, af.lon - 0.020, af.lat + 0.012, af.lon + 0.020], 14,
                "Sub-objectives FALCON (control tower), HAWK (hangars / T-72), "
                "EAGLE (ammo dump). LZ EAGLE 1.2 km SE."))
    out.append(("LZ EAGLE detail",
                [LZ_EAGLE.lat - 0.005, LZ_EAGLE.lon - 0.008,
                 LZ_EAGLE.lat + 0.005, LZ_EAGLE.lon + 0.008], 15,
                "PRI LZ for 2× CH-47F single-lift insertion. ALT = LZ FALCON NW."))
    return out


# ── Live operators ─────────────────────────────────────────────────────────
SIM_PASSWORD = "Arrow2525!"

@dataclass
class SimOp:
    callsign: str
    rank: str
    role: str               # ADMIN / BATTLE_CAPTAIN / OPERATOR
    track: str              # which scripted track this op follows
    seat: int = 0           # 0-N within the track (cluster spread)
    token: str = ""
    op_id: int = 0
    lat: float = 0.0
    lon: float = 0.0


def _task_force() -> list[SimOp]:
    """All callsigns the simulator drives across the operation."""
    ops = [
        # Coy RANGER HQ
        SimOp("RANGER-6", "OF-3", "ADMIN",          "CO",      seat=0),
        SimOp("RANGER-5", "OF-2", "BATTLE_CAPTAIN", "CCP",     seat=0),
        SimOp("RANGER-7", "OR-9", "BATTLE_CAPTAIN", "CCP",     seat=1),
        SimOp("RANGER-FO","OR-7", "OPERATOR",       "FO",      seat=0),
        # 1 PL (ME) — OBJ FALCON
        SimOp("RNG-1-6",  "OF-1", "BATTLE_CAPTAIN", "1PL",     seat=0),
        SimOp("RNG-1-1",  "OR-6", "OPERATOR",       "1PL",     seat=1),
        SimOp("RNG-1-2",  "OR-6", "OPERATOR",       "1PL",     seat=2),
        SimOp("RNG-1-3",  "OR-5", "OPERATOR",       "1PL",     seat=3),
        # 2 PL — OBJ HAWK
        SimOp("RNG-2-6",  "OF-1", "BATTLE_CAPTAIN", "2PL",     seat=0),
        SimOp("RNG-2-1",  "OR-6", "OPERATOR",       "2PL",     seat=1),
        SimOp("RNG-2-2",  "OR-6", "OPERATOR",       "2PL",     seat=2),
        SimOp("RNG-2-3",  "OR-5", "OPERATOR",       "2PL",     seat=3),
        # 3 PL (SE) — OBJ EAGLE
        SimOp("RNG-3-6",  "OF-1", "BATTLE_CAPTAIN", "3PL",     seat=0),
        SimOp("RNG-3-1",  "OR-6", "OPERATOR",       "3PL",     seat=1),
        SimOp("RNG-3-2",  "OR-5", "OPERATOR",       "3PL",     seat=2),
        # WPN det
        SimOp("RNG-W6",   "OR-7", "OPERATOR",       "WPN",     seat=0),
        SimOp("RNG-W1",   "OR-5", "OPERATOR",       "WPN",     seat=1),
        # CH-47 lift
        SimOp("CHALK-1",  "OF-2", "BATTLE_CAPTAIN", "CH47-1",  seat=0),
        SimOp("CHALK-2",  "OF-2", "BATTLE_CAPTAIN", "CH47-2",  seat=0),
        # Reinforcement Coy VIPER
        SimOp("VIPER-6",  "OF-3", "BATTLE_CAPTAIN", "VIPER",   seat=0),
        SimOp("VPR-1-6",  "OF-1", "BATTLE_CAPTAIN", "VIPER",   seat=1),
        SimOp("VPR-2-6",  "OF-1", "BATTLE_CAPTAIN", "VIPER",   seat=2),
        SimOp("VPR-3-6",  "OF-1", "BATTLE_CAPTAIN", "VIPER",   seat=3),
    ]
    return ops


# ── Track resolver — where does this operator go at each phase? ─────────────
def waypoint_for(op: SimOp, phase_idx: int) -> LatLon:
    """Return the operator's target LatLon for a given phase index (0..9).

    The track + seat are blended into a small cluster so a platoon doesn't
    stack at exactly one point. CH-47 tracks fly the actual ingress route;
    Ranger tracks walk from LZ EAGLE up to their assigned OBJ; VIPER moves
    by ground from AA VIPER through RP RED to the airfield perimeter.
    """
    # Seat-based offset (north, east) in metres — small cluster spread
    seat_n = (op.seat % 4) * 12 - 18
    seat_e = (op.seat // 4) * 12 - 18

    def at(p: LatLon) -> LatLon:
        return p.offset_m(seat_n + random.uniform(-8, 8),
                          seat_e + random.uniform(-8, 8))

    # CH-47s have their own flight track
    if op.track == "CH47-1":
        if phase_idx <= 0: return at(FOB_LAUNCH)
        if phase_idx == 1: return at(FOB_LAUNCH.offset_m(-2_500, -3_000))   # NOE waypoint
        if phase_idx == 2: return at(LZ_EAGLE.offset_m(60, -60))
        # After insertion CH-47s exfil empty back to FOB
        if phase_idx <= 7: return at(LZ_EAGLE.offset_m(60, -60))
        return at(FOB_LAUNCH)

    if op.track == "CH47-2":
        if phase_idx <= 0: return at(FOB_LAUNCH.offset_m(0, 100))
        if phase_idx == 1: return at(FOB_LAUNCH.offset_m(-2_500, -3_100))
        if phase_idx == 2: return at(LZ_EAGLE.offset_m(60, 60))
        if phase_idx <= 7: return at(LZ_EAGLE.offset_m(60, 60))
        return at(FOB_LAUNCH.offset_m(0, 100))

    # Coy VIPER — sit in AA, then move via RP RED to airfield south perimeter
    if op.track == "VIPER":
        if phase_idx <= 6: return at(VIPER_AA)
        if phase_idx == 7: return at(VIPER_AA.offset_m(600, 100))     # SP from AA
        if phase_idx == 8: return at(RP_RED)
        return at(AIRFIELD.bearing_m(180.0, 250))                      # join perimeter

    # All Ranger tracks (CO/CCP/FO/1PL/2PL/3PL/WPN) — at FOB pre-launch,
    # in flight aboard CH-47s during Φ1, at LZ EAGLE Φ2, then their own OBJ.
    if phase_idx <= 0: return at(FOB_LAUNCH.offset_m(-30, 30))      # pre-loaded near rotors
    if phase_idx == 1: return at(FOB_LAUNCH.offset_m(-2_500, -3_050))  # mid-flight
    if phase_idx == 2: return at(LZ_EAGLE)
    if phase_idx == 3:
        return at(AIRFIELD.bearing_m(180.0, 700))                      # crossing PL HAMMER

    # By phase the platoons head to their objectives
    if op.track == "1PL":
        if phase_idx == 4: return at(CONTROL_TOWER)
        if phase_idx >= 5: return at(AIRFIELD.offset_m(400, 0))         # BP ALPHA (north)
    if op.track == "2PL":
        if phase_idx == 4: return at(AIRFIELD.bearing_m(180.0, 400))    # holding south of HAWK
        if phase_idx == 5: return at(HANGAR_NW)
        if phase_idx >= 6: return at(AIRFIELD.offset_m(-200, -800))     # BP BRAVO (west)
    if op.track == "3PL":
        if phase_idx <= 5: return at(AIRFIELD.bearing_m(180.0, 200))    # SE reserve
        if phase_idx == 6: return at(AMMO_DUMP)
        return at(AIRFIELD.offset_m(-200, 800))                          # BP CHARLIE (east)
    if op.track == "CO":
        if phase_idx <= 3: return at(LZ_EAGLE.offset_m(40, 0))
        if phase_idx == 4: return at(CONTROL_TOWER.offset_m(-100, 0))   # with ME at FALCON
        return at(CONTROL_TOWER.offset_m(-200, 0))                       # Coy TAC
    if op.track == "CCP":
        return at(LZ_EAGLE.offset_m(80, 0))                              # CCP stays at LZ
    if op.track == "FO":
        if phase_idx <= 2: return at(LZ_EAGLE.offset_m(50, 50))
        return at(CONTROL_TOWER.offset_m(60, -100))                       # FO at tower top once held
    if op.track == "WPN":
        if phase_idx <= 2: return at(LZ_EAGLE.offset_m(-30, 0))
        return at(AIRFIELD.offset_m(-300, 200))                           # mortar PA

    return at(LZ_EAGLE)


async def register_or_login(client: httpx.AsyncClient, admin_token: str,
                             op: SimOp) -> None:
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
        log.info("  registered %-10s (%s, track %s)", op.callsign, op.role, op.track)
    else:
        tok = await login(client, op.callsign, SIM_PASSWORD)
        if tok:
            op.token = tok


# Move-speed depends on track — CH-47s are fast, dismounts walk, Bradleys roll
def _speed_ms(op: SimOp, phase_idx: int) -> float:
    if op.track.startswith("CH47"):
        return 60.0 if phase_idx in (1, 8, 9) else 8.0
    if op.track == "VIPER":
        return 12.0    # 43 km/h M2A3 cross-country
    return 2.0         # 7 km/h dismount


TICK_SECONDS = 1.5


async def drive_operator(client: httpx.AsyncClient, op: SimOp,
                         phase_state: dict, speed: float) -> None:
    if not op.token:
        return
    # Seed at the operator's Φ0 waypoint
    seed = waypoint_for(op, 0)
    op.lat, op.lon = seed.lat, seed.lon
    real_tick = max(0.05, TICK_SECONDS / speed)
    while True:
        idx = max(0, min(len(PHASES) - 1, phase_state["idx"]))
        target = waypoint_for(op, idx)
        sim_dt = real_tick * speed
        op.lat, op.lon = step_towards(op.lat, op.lon, target.lat, target.lon,
                                      _speed_ms(op, idx), sim_dt)
        # CH-47s fly at altitude; ground tracks at sea level
        alt = 18.0 if op.track.startswith("CH47") and idx in (1,) else 4.0
        await api(client, "POST", "/tracking/position", token=op.token, json={
            "latitude": op.lat, "longitude": op.lon, "altitude": alt,
        })
        await asyncio.sleep(real_tick)


async def advance_phase_clock(phase_state: dict, speed: float, loop: bool) -> None:
    """Step the phase clock; durations vary per phase from the PHASES table."""
    while True:
        cur = PHASES[max(0, min(len(PHASES) - 1, phase_state["idx"]))]
        dwell = max(0.5, cur.seconds_at_speed_1 / speed)
        await asyncio.sleep(dwell)
        nxt = phase_state["idx"] + 1
        if nxt >= len(PHASES):
            if not loop:
                log.info("🏁 OPERATION HAMMERHEAD complete. Combined defence stable.")
                return
            log.info("🔁 LOOPING — task force re-seeds at FOB Lombardsijde (Φ0).")
            phase_state["idx"] = 0
        else:
            phase_state["idx"] = nxt
        ph = PHASES[phase_state["idx"]]
        log.info("📍 PHASE ADVANCE — Φ%d %s — %s", ph.idx, ph.code, ph.label)


# ── Live event injectors ────────────────────────────────────────────────────
CONTACT_TEMPLATES = [
    ("Enemy mech inf section in hangar",   "ENEMY", "SHGPUCIM----"),
    ("Enemy T-72 spotted in revetment",    "ENEMY", "SHGPUCAA----"),
    ("Enemy ATGM team (Kornet)",           "ENEMY", "SHGPUCAA---F"),
    ("Enemy MANPADS launch detected",      "ENEMY", "SHGPUCDS----"),
    ("Enemy mortar fire received",         "ENEMY", "SHGPUCFHE---"),
    ("EN sniper IVO control tower",        "ENEMY", "SHGPUCIS----"),
    ("Civilian on perimeter — challenged", "POI",   "SNGPI-------"),
    ("Captured EN comms equipment",        "POI",   "SFGPUUS-----"),
    ("LZ marked — green smoke",            "POI",   "SFGPIBA-----"),
]


def _live_actor(ops: list[SimOp]) -> Optional[SimOp]:
    # Prefer forward Rangers (1/2/3 PL); fall back to anyone with a token
    fwd = [o for o in ops if o.track in {"1PL","2PL","3PL","FO"} and o.token and o.lat]
    live = [o for o in ops if o.token and o.lat]
    return random.choice(fwd) if fwd else (random.choice(live) if live else None)


async def inject_contacts(client: httpx.AsyncClient, ops: list[SimOp], speed: float) -> None:
    interval = max(2.0, 10.0 / speed)
    await asyncio.sleep(interval * 0.4)
    n = 0
    while True:
        await asyncio.sleep(interval)
        op = _live_actor(ops)
        if not op:
            continue
        desc, type_, sidc = random.choice(CONTACT_TEMPLATES)
        spread = random.uniform(120, 400)
        clat = op.lat + spread * LAT_DEG_PER_M
        clon = op.lon + random.uniform(-100, 100) * lon_deg_per_m(op.lat)
        r = await api(client, "POST", "/tactical-objects", token=op.token, json={
            "type": type_, "symbol_code": sidc,
            "latitude": round(clat, 6), "longitude": round(clon, 6),
            "affiliation": "ENEMY" if type_ == "ENEMY" else "FRIENDLY",
            "notes": f"{desc} · {op.callsign}",
            "echelon": "", "rotation": 0.0, "geometry": "",
            "visibility": "COMPANY",
        })
        if r:
            n += 1
            log.info("⚠️  %s marks: %s (#%d)", op.callsign, desc, n)
        await api(client, "POST", "/messages", token=op.token, json={
            "content": f"CONTACT — {desc} @ {clat:.4f},{clon:.4f}",
            "message_type": "BROADCAST",
        })


async def inject_spot_reports(client: httpx.AsyncClient, ops: list[SimOp], speed: float) -> None:
    interval = max(3.0, 18.0 / speed)
    await asyncio.sleep(interval * 0.6)
    while True:
        await asyncio.sleep(interval)
        op = _live_actor(ops)
        if not op:
            continue
        payload = {
            "size":     random.choice(["squad", "section", "platoon"]),
            "activity": random.choice([
                "DEFENDING from prepared positions",
                "WITHDRAWING under fire",
                "REINFORCING from hangar dispersal",
                "MORTAR-FIRING from south revetment",
            ]),
            "location":  f"{op.lat:.4f},{op.lon:.4f}",
            "unit":      "EN inf coy",
            "time":      "current",
            "equipment": random.choice(["BTR-80", "T-72", "Kornet ATGM", "Igla MANPADS", "ZU-23-2"]),
            "direction": random.choice(["N", "NE", "E", "SE", "S", "SW", "W", "NW"]),
            "distance":  random.choice([100, 200, 400, 600, 800]),
            "description": f"Spot report from {op.callsign} during OP HAMMERHEAD",
        }
        r = await api(client, "POST", "/reports", token=op.token,
                      json={"type": "SPOT", "payload": payload})
        if r:
            log.info("📋 %s SPOT %s %s @ %.4f,%.4f",
                     op.callsign, payload["size"], payload["equipment"], op.lat, op.lon)


async def inject_fire_missions(client: httpx.AsyncClient, ops: list[SimOp], speed: float) -> None:
    interval = max(4.0, 22.0 / speed)
    await asyncio.sleep(interval * 0.5)
    n = 0
    while True:
        await asyncio.sleep(interval)
        # FO calls for fire if available; otherwise any forward
        fo  = next((o for o in ops if o.callsign == "RANGER-FO" and o.token and o.lat), None)
        op  = fo or _live_actor(ops)
        if not op:
            continue
        dist = random.uniform(300, 800)
        brg  = random.uniform(340, 20)
        tlat = op.lat + dist * math.cos(math.radians(brg)) * LAT_DEG_PER_M
        tlon = op.lon + dist * math.sin(math.radians(brg)) * lon_deg_per_m(op.lat)
        payload = {
            "latitude": round(tlat, 6), "longitude": round(tlon, 6),
            "altitude": 0.0, "direction": round(brg, 1),
            "mission_type": random.choice(["ADJUST_FIRE", "FIRE_FOR_EFFECT",
                                           "SUPPRESSION", "ILLUMINATION"]),
            "ammunition":   random.choice(["HE", "SMOKE", "ILLUM"]),
            "quantity":     random.choice([1, 2, 4, 6]),
            "description":  f"{op.callsign} — CFF on enemy element @ OBJ HAMMERHEAD",
        }
        r = await api(client, "POST", "/fire-missions", token=op.token, json=payload)
        if r:
            n += 1
            log.info("🎯 %s CFF %s × %d %s (#%d)",
                     op.callsign, payload["ammunition"], payload["quantity"],
                     payload["mission_type"], n)


async def inject_tic_alerts(client: httpx.AsyncClient, ops: list[SimOp], speed: float) -> None:
    interval = max(8.0, 45.0 / speed)
    await asyncio.sleep(interval * 0.8)
    n = 0
    while True:
        await asyncio.sleep(interval)
        op = _live_actor(ops)
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


# ── Reset & main ────────────────────────────────────────────────────────────
async def reset_world(client: httpx.AsyncClient,
                      admin_token: str) -> tuple[int, int, int, int]:
    n_obj = 0
    for o in (await api(client, "GET", "/tactical-objects", token=admin_token) or []):
        if isinstance(o, dict) and o.get("type") in (ALL_TG_TYPES | NON_TG_TYPES):
            r = await api(client, "DELETE", f"/tactical-objects/{o['id']}", token=admin_token)
            if r is not None:
                n_obj += 1
    n_op = 0
    for o in (await api(client, "GET", "/opords", token=admin_token) or []):
        title = o.get("title") if isinstance(o, dict) else None
        opnum = o.get("opord_number") if isinstance(o, dict) else None
        if (title and "HAMMERHEAD" in title) or (opnum and opnum.startswith("OPORD 26-HH")):
            r = await api(client, "DELETE", f"/opords/{o['id']}", token=admin_token)
            if r is not None:
                n_op += 1
    n_ov = 0
    for ov in (await api(client, "GET", "/overlays", token=admin_token) or []):
        if isinstance(ov, dict) and "id" in ov:
            r = await api(client, "DELETE", f"/overlays/{ov['id']}", token=admin_token)
            if r is not None:
                n_ov += 1
    sim_callsigns = {o.callsign for o in _task_force()}
    n_users = 0
    for op in (await api(client, "GET", "/operators", token=admin_token) or []):
        if (isinstance(op, dict) and op.get("callsign") in sim_callsigns
                and op.get("callsign") != ARGS.admin):
            r = await api(client, "DELETE", f"/operators/{op['id']}", token=admin_token)
            if r is not None:
                n_users += 1
    return n_obj, n_op, n_ov, n_users


async def amain() -> None:
    log.info("Backend: %s   (path prefix: %r)", BASE, PATH_PREFIX or "<none>")
    async with httpx.AsyncClient(base_url=ORIGIN, timeout=20.0, verify=False) as client:
        log.info("Logging in as seed admin %s …", ARGS.admin)
        admin_token = await login(client, ARGS.admin, ARGS.password)
        if not admin_token:
            sys.exit(f"login failed for {ARGS.admin}. Provide --admin / --password "
                     "for a non-MFA ADMIN account on the backend.")
        sim_utils.save_backend(ARGS.backend)
        log.info("Authenticated.")
        global MISSION_ID
        MISSION_ID = await sim_utils.create_mission_async(
            client, BASE, admin_token, ARGS.mission_name,
            map_center_lat=51.0900, map_center_lng=2.6531, map_zoom=14)

        if ARGS.reset:
            n_obj, n_op, n_ov, n_users = await reset_world(client, admin_token)
            log.info("Reset: %d tactical objects · %d OPORDs · %d overlays · %d sim operators.",
                     n_obj, n_op, n_ov, n_users)

        # ── Static plant ────────────────────────────────────────────────
        items = build_tactical_objects()
        log.info("── Planting %d tactical objects (airfield, LZs, axes, "
                 "enemy ORBAT, friendly POIs, defence perimeter) ──", len(items))
        sem = asyncio.Semaphore(8)
        async def _post(item):
            async with sem:
                return await api(client, "POST", "/tactical-objects",
                                 token=admin_token, json=item)
        results = await asyncio.gather(*[_post(it) for it in items])
        ok = sum(1 for r in results if r)
        log.info("   %d / %d planted", ok, len(items))

        # OPORD
        op_payload = build_opord()
        op_resp = await api(client, "POST", "/opords", token=admin_token, json=op_payload)
        op_id = op_resp.get("id", -1) if op_resp else -1
        if op_id < 0:
            log.warning("OPORD creation failed — see warnings above.")
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

        # Verification
        check_objs = await api(client, "GET", "/tactical-objects", token=admin_token) or []
        check_ops  = await api(client, "GET", "/opords",            token=admin_token) or []
        from collections import Counter as _C
        by_type = _C(o.get("type") for o in check_objs if isinstance(o, dict))
        by_aff  = _C(o.get("affiliation") for o in check_objs if isinstance(o, dict))
        log.info("── Verify ─────────────────────────────────────────────")
        log.info("   tactical objects on server : %d", len(check_objs))
        log.info("   by affiliation             : %s", dict(by_aff))
        log.info("   types present              : %s",
                 ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
        log.info("   HAMMERHEAD OPORDs          : %d",
                 sum(1 for o in check_ops if isinstance(o, dict)
                     and "HAMMERHEAD" in (o.get("title") or "")))

        if ARGS.no_live:
            log.info("--no-live: exiting without driving operators.")
            return

        # ── Live ops — register the task force and run phases ───────────
        log.info("── Registering task force (%.0fx speed) ─────", ARGS.speed)
        tf = _task_force()
        await asyncio.gather(*[register_or_login(client, admin_token, op) for op in tf])
        active = [o for o in tf if o.token]
        log.info("%d / %d operators ready.", len(active), len(tf))

        phase_state = {"idx": 0}
        log.info("📍 START — Φ0 PREP (%s)", PHASES[0].label)

        try:
            await asyncio.gather(
                advance_phase_clock(phase_state, ARGS.speed, ARGS.loop),
                inject_contacts(client, active, ARGS.speed),
                inject_spot_reports(client, active, ARGS.speed),
                inject_fire_missions(client, active, ARGS.speed),
                inject_tic_alerts(client, active, ARGS.speed),
                *[drive_operator(client, op, phase_state, ARGS.speed)
                  for op in active],
            )
        except (KeyboardInterrupt, asyncio.CancelledError):
            log.info("Interrupted — task force frozen at last position.")


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
        pass


if __name__ == "__main__":
    main()
