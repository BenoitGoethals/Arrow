#!/usr/bin/env python3
"""
Arrow Simulator — OPERATION STEEL TIDE
=======================================

1-75 Ranger Bn (-) conducts an air-assault raid on the Port of Zeebrugge
LNG / container terminal (Belgium, 51.342°N 3.196°E) to destroy critical
infrastructure and deny port access.

MISSION  : Destroy Zeebrugge LNG terminal, neutralise enemy security force,
           exfil to alternate DZ.

FRIENDLY FORCES — Task Force STEEL
  Coy RANGER (1st/75 Ranger Bn, A Coy)
    COY HQ     : RANGER-6 (CO), RANGER-5 (XO), RANGER-7 (1SG), FO, JTAC, RTO
    1st PLT    : RANGER-1-6 (PLT LDR) + A/B/C Teams  → OBJ HAMMER (terminal)
    2nd PLT    : RANGER-2-6               + A/B/C Teams  → OBJ ANVIL  (dock ctrl)
    3rd PLT    : RANGER-3-6 (ASSAULT)     + A/B/C Teams  → breach / blocking
    WPNS PLT   : 81mm mortar section (2 tubes) + HMG team
  Lift         : 4× MH-47G (160th SOAR), call-signs STEEL-1 thru STEEL-4
  CAS          : 4× F/A-18C, call-signs HORNET 1-1 thru 1-4
  ISR          : MQ-9 SHADOW-21, persistent CAS stack offshore
  MEDEVAC      : DUSTOFF (UH-60M)

ENEMY
  Port security company (conscript), approx 80 PAX
  2× BMP-2 IFV (main gate + southern quay)
  MANPADS team (roof of terminal control building)
  4× guard positions (towers around terminal)
  Static 12.7 mm HMG (north pier)
  Moored patrol boat (eastern quay)

PHASE PLAN
  H-60  FOB Lombardsijde brief & load
  H-0   MH-47s depart FOB — NOE flight over North Sea
  H+15  DZ FALCON (insertion) — open field 2.5 km NNE of terminal
  H+20  Assembly Area RANGER — consolidate & confirm orders
  H+25  PL ALPHA crossed — assault begins
  H+35  PL BRAVO crossed — 81mm fires lifted; F/A-18 CAS on call
  H+45  OBJ HAMMER (terminal) seized — RANGER-1
        OBJ ANVIL (dock control) seized — RANGER-2
  H+60  Exploitation & demolition charges placed
  H+75  Break contact — PL CHARLIE / exfil to DZ EAGLE (western beach)
  H+90  MH-47s recover at DZ EAGLE — exfil complete

Run:
  uv run python simulate_zeebrugge_assault.py
  uv run python simulate_zeebrugge_assault.py --backend http://localhost:6001
  uv run python simulate_zeebrugge_assault.py --no-live    # plant only
  uv run python simulate_zeebrugge_assault.py --reset      # wipe & re-plant
  uv run python simulate_zeebrugge_assault.py --speed 4
"""

from __future__ import annotations

import argparse, asyncio, json, logging, math, os, random, sys, time
from dataclasses import dataclass
from typing import Optional

import httpx
import sim_utils

# ── CLI ─────────────────────────────────────────────────────────────────────────
DEFAULT_BACKEND = (
    os.environ.get("ARROW_BACKEND_URL")
    or sim_utils.load_saved_backend()
    or "https://78.21.255.210:6200/api"
)

parser = argparse.ArgumentParser(description="Arrow — OPERATION STEEL TIDE (Zeebrugge)")
parser.add_argument("--backend",      default=DEFAULT_BACKEND)
parser.add_argument("--admin",        default="benoit")
parser.add_argument("--password",     default="ranger14")
parser.add_argument("--reset",        action="store_true",
                    help="Wipe previous STEEL TIDE objects and re-plant")
parser.add_argument("--no-live",      action="store_true",
                    help="Plant static plan only, skip live movement")
parser.add_argument("--speed",        type=float, default=2.0)
parser.add_argument("--mission-name", default="Operation Steel Tide")
ARGS = parser.parse_args()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("zt")

BASE = ARGS.backend.rstrip("/")
sim_utils.save_backend(BASE)
ORIGIN, PATH_PREFIX = sim_utils.split_base(BASE)

# ── Geo helpers ──────────────────────────────────────────────────────────────────
def _lat_m(m: float) -> float: return m / 111_320.0
def _lon_m(lat: float, m: float) -> float:
    return m / (111_320.0 * math.cos(math.radians(lat)))

@dataclass(frozen=True)
class LL:
    lat: float
    lon: float
    def off(self, n_m: float, e_m: float) -> "LL":
        return LL(self.lat + _lat_m(n_m), self.lon + _lon_m(self.lat, e_m))
    def brg(self, bearing_deg: float, dist_m: float) -> "LL":
        r = math.radians(bearing_deg)
        return self.off(dist_m * math.cos(r), dist_m * math.sin(r))
    def p(self) -> list[float]: return [self.lat, self.lon]

def dist_m(a: LL, b: LL) -> float:
    dlat = (b.lat - a.lat) * 111_320
    dlon = (b.lon - a.lon) * 111_320 * math.cos(math.radians((a.lat + b.lat) / 2))
    return math.hypot(dlat, dlon)

def step(a: LL, b: LL, speed_ms: float, dt: float) -> LL:
    d = dist_m(a, b)
    if d < 1: return b
    move = min(speed_ms * dt, d)
    dlat = (b.lat - a.lat) * 111_320
    dlon = (b.lon - a.lon) * 111_320 * math.cos(math.radians(a.lat))
    brg  = math.atan2(dlon, dlat)
    return LL(a.lat + move * math.cos(brg) * _lat_m(1),
               a.lon + move * math.sin(brg) * _lon_m(a.lat, 1))

# ── Key locations — Port of Zeebrugge, Belgium ──────────────────────────────────
# LNG / Container terminal complex
TERMINAL      = LL(51.3420, 3.1900)   # OBJ HAMMER — LNG terminal
DOCK_CTRL     = LL(51.3390, 3.2050)   # OBJ ANVIL  — dock control building
NORTH_PIER    = LL(51.3480, 3.2000)   # HMG position, north pier
MAIN_GATE     = LL(51.3410, 3.1780)   # enemy main gate / BMP-2 #1
SOUTH_QUAY    = LL(51.3360, 3.1950)   # BMP-2 #2
PATROL_BOAT   = LL(51.3370, 3.2080)   # moored patrol boat
MANPADS       = LL(51.3430, 3.1920)   # MANPADS on roof

# Friendly
DZ_FALCON     = LL(51.3680, 3.1960)   # Primary DZ — insertion 2.8 km NNE
DZ_EAGLE      = LL(51.3350, 3.1500)   # Exfil DZ — western beach
AA_RANGER     = LL(51.3600, 3.1900)   # Assembly Area after DZ
FOB_LAUNCH    = LL(51.4800, 2.7500)   # FOB Lombardsijde (start)

# Phase lines (west–east transects across AO)
PL_ALPHA_W    = LL(51.3560, 3.1500)
PL_ALPHA_E    = LL(51.3560, 3.2200)
PL_BRAVO_W    = LL(51.3490, 3.1500)
PL_BRAVO_E    = LL(51.3490, 3.2200)
PL_CHARLIE_W  = LL(51.3330, 3.1500)
PL_CHARLIE_E  = LL(51.3330, 3.2200)

# Coy boundary (southern limit — FLOT)
FLOT_W        = LL(51.3280, 3.1400)
FLOT_E        = LL(51.3280, 3.2300)

# CFL / NFL
CFL_W         = LL(51.3510, 3.1500)
CFL_E         = LL(51.3510, 3.2200)

# Objective areas (polygon corners)
def _obj_box(center: LL, n: float, e: float) -> list[list[float]]:
    """Rectangle around center, ±n_m north, ±e_m east."""
    c = center
    return [c.off(n, -e).p(), c.off(n, e).p(),
            c.off(-n, e).p(), c.off(-n, -e).p()]

OBJ_HAMMER_BOX = _obj_box(TERMINAL,   120, 160)
OBJ_ANVIL_BOX  = _obj_box(DOCK_CTRL,   80, 100)

# ── Operator roster ───────────────────────────────────────────────────────────────
# (callsign, rank, role, platoon-label)
RANGERS = [
    # COY HQ
    ("RANGER-6",   "CPT", "BATTLE_CAPTAIN", "HQ"),
    ("RANGER-5",   "1LT", "OPS",            "HQ"),
    ("RANGER-7",   "CSM", "OPS",            "HQ"),
    ("RANGER-FO",  "CPT", "FO",             "HQ"),
    ("RANGER-JTAC","SSG", "CAS",            "HQ"),
    ("RANGER-RTO", "SPC", "OPERATOR",       "HQ"),
    # 1st PLT
    ("RANGER-1-6", "1LT", "OPERATOR",       "1PLT"),
    ("RANGER-1-7", "SSG", "OPERATOR",       "1PLT"),
    ("RNG-1A1",    "SGT", "OPERATOR",       "1PLT"),
    ("RNG-1A2",    "SPC", "OPERATOR",       "1PLT"),
    ("RNG-1A3",    "SPC", "OPERATOR",       "1PLT"),
    ("RNG-1B1",    "SGT", "OPERATOR",       "1PLT"),
    ("RNG-1B2",    "SPC", "OPERATOR",       "1PLT"),
    ("RNG-1B3",    "SPC", "OPERATOR",       "1PLT"),
    ("RNG-1C1",    "SGT", "OPERATOR",       "1PLT"),
    ("RNG-1C2",    "SPC", "OPERATOR",       "1PLT"),
    ("RNG-1C3",    "SPC", "OPERATOR",       "1PLT"),
    # 2nd PLT
    ("RANGER-2-6", "1LT", "OPERATOR",       "2PLT"),
    ("RANGER-2-7", "SSG", "OPERATOR",       "2PLT"),
    ("RNG-2A1",    "SGT", "OPERATOR",       "2PLT"),
    ("RNG-2A2",    "SPC", "OPERATOR",       "2PLT"),
    ("RNG-2A3",    "SPC", "OPERATOR",       "2PLT"),
    ("RNG-2B1",    "SGT", "OPERATOR",       "2PLT"),
    ("RNG-2B2",    "SPC", "OPERATOR",       "2PLT"),
    ("RNG-2B3",    "SPC", "OPERATOR",       "2PLT"),
    ("RNG-2C1",    "SGT", "OPERATOR",       "2PLT"),
    ("RNG-2C2",    "SPC", "OPERATOR",       "2PLT"),
    ("RNG-2C3",    "SPC", "OPERATOR",       "2PLT"),
    # 3rd PLT (breach / blocking)
    ("RANGER-3-6", "1LT", "OPERATOR",       "3PLT"),
    ("RANGER-3-7", "SSG", "OPERATOR",       "3PLT"),
    ("RNG-3A1",    "SGT", "OPERATOR",       "3PLT"),
    ("RNG-3A2",    "SPC", "OPERATOR",       "3PLT"),
    ("RNG-3B1",    "SGT", "OPERATOR",       "3PLT"),
    ("RNG-3B2",    "SPC", "OPERATOR",       "3PLT"),
    # WPNS PLT
    ("RANGER-W6",  "SSG", "OPERATOR",       "WPNS"),
    ("RNG-MTR1",   "SPC", "OPERATOR",       "WPNS"),
    ("RNG-MTR2",   "SPC", "OPERATOR",       "WPNS"),
    ("RNG-HMG1",   "SPC", "OPERATOR",       "WPNS"),
    # MEDEVAC
    ("DUSTOFF-1",  "SPC", "MED",            "MED"),
    ("DUSTOFF-2",  "SPC", "MED",            "MED"),
]

# ── HTTP helpers ──────────────────────────────────────────────────────────────────
HDR: dict = {}
MID: int  = 0          # mission id

def _hdr() -> dict:
    return {**HDR, "X-Mission-ID": str(MID)} if MID else HDR

def _post(client: httpx.Client, path: str, body: dict) -> dict | None:
    r = client.post(f"{BASE}{path}", json=body, headers=_hdr(), timeout=12)
    if r.status_code in (200, 201):
        return r.json()
    log.warning("POST %s → %d %s", path, r.status_code, r.text[:120])
    return None

def _get(client: httpx.Client, path: str) -> list | dict | None:
    r = client.get(f"{BASE}{path}", headers=_hdr(), timeout=12)
    return r.json() if r.ok else None

def _tobj(client: httpx.Client, obj_type: str, lat: float, lon: float,
           notes: str = "", affiliation: str = "FRIENDLY",
           symbol: str = "", echelon: str = "",
           geometry: dict | None = None) -> dict | None:
    body = {
        "type":        obj_type,
        "latitude":    lat,
        "longitude":   lon,
        "notes":       notes,
        "affiliation": affiliation,
        "echelon":     echelon,
    }
    if symbol: body["symbol_code"] = symbol
    if geometry:
        body["geometry"] = json.dumps(geometry)
    return _post(client, "/tactical-objects", body)

def _line(client: httpx.Client, obj_type: str, coords: list[LL],
          notes: str, affiliation: str = "FRIENDLY") -> dict | None:
    geom = {"type": "line", "coords": [p.p() for p in coords]}
    # Use midpoint for lat/lon
    mid = coords[len(coords) // 2]
    return _tobj(client, obj_type, mid.lat, mid.lon, notes, affiliation,
                 geometry=geom)

def _poly(client: httpx.Client, obj_type: str, corners: list[list[float]],
          notes: str, affiliation: str = "FRIENDLY") -> dict | None:
    geom = {"type": "polygon", "coords": corners}
    # centroid
    clat = sum(c[0] for c in corners) / len(corners)
    clon = sum(c[1] for c in corners) / len(corners)
    return _tobj(client, obj_type, clat, clon, notes, affiliation, geometry=geom)

def _fire(client: httpx.Client, lat: float, lon: float,
          mission_type: str, ammo: str, qty: int, desc: str,
          direction: float = 0.0) -> dict | None:
    return _post(client, "/fire-missions", {
        "latitude":     lat,
        "longitude":    lon,
        "altitude":     0.0,
        "direction":    direction,
        "mission_type": mission_type,
        "ammunition":   ammo,
        "quantity":     qty,
        "description":  desc,
    })

def _report(client: httpx.Client, rtype: str, payload: dict) -> dict | None:
    return _post(client, "/reports", {"type": rtype, "payload": payload})

# ── Static plan ───────────────────────────────────────────────────────────────────

def plant_plan(client: httpx.Client, op_ids: list[int]) -> None:
    log.info("Planting tactical graphics …")

    # ── Phase lines ────────────────────────────────────────────────────────────
    _line(client, "PHASE_LINE",
          [PL_ALPHA_W, PL_ALPHA_E], "PL ALPHA")
    _line(client, "PHASE_LINE",
          [PL_BRAVO_W, PL_BRAVO_E], "PL BRAVO")
    _line(client, "PHASE_LINE",
          [PL_CHARLIE_W, PL_CHARLIE_E], "PL CHARLIE — exfil trigger")
    log.info("  Phase lines planted")

    # ── FLOT / boundary ────────────────────────────────────────────────────────
    _line(client, "FLOT",
          [FLOT_W, FLOT_E], "FLOT — Southern Limit of Advance")
    _line(client, "BOUNDARY",
          [LL(51.3280, 3.1400), LL(51.3700, 3.1400)],
          "Western COY Boundary")
    _line(client, "BOUNDARY",
          [LL(51.3280, 3.2300), LL(51.3700, 3.2300)],
          "Eastern COY Boundary")
    log.info("  FLOT + boundaries planted")

    # ── CFL / NFL ──────────────────────────────────────────────────────────────
    _line(client, "CFL",
          [CFL_W, CFL_E], "CFL — Mortar fires clear south of this line H+35")
    _line(client, "FSCL",
          [LL(51.3600, 3.1400), LL(51.3600, 3.2300)],
          "FSCL — CAS/mortar deconfliction line")
    log.info("  Fire coordination lines planted")

    # ── Objective areas ────────────────────────────────────────────────────────
    _poly(client, "OBJ_AREA",
          OBJ_HAMMER_BOX, "OBJ HAMMER — LNG Terminal (1st PLT)")
    _poly(client, "OBJ_AREA",
          OBJ_ANVIL_BOX,  "OBJ ANVIL  — Dock Control Building (2nd PLT)")
    # RP (Release Point) before objectives
    _tobj(client, "MARKER",
          AA_RANGER.off(-400, 0).lat, AA_RANGER.off(-400, 0).lon,
          "RP RED — release point before objectives")
    log.info("  Objective areas planted")

    # ── DZ / LZ markers ───────────────────────────────────────────────────────
    _tobj(client, "POI",
          DZ_FALCON.lat, DZ_FALCON.lon,
          "DZ FALCON — Primary insertion DZ (H+15)\n4× MH-47G touchdown\nSector clear NNE")
    _tobj(client, "POI",
          DZ_EAGLE.lat, DZ_EAGLE.lon,
          "DZ EAGLE — Exfil DZ (H+90)\nWestern beach, accessible H+75+\n2 sorties MH-47G")
    _tobj(client, "MARKER",
          AA_RANGER.lat, AA_RANGER.lon,
          "AA RANGER — Assembly Area\nConsolidate post-DZ\nH+20 → H+25")
    log.info("  DZ / LZ / AA markers planted")

    # ── Routes ────────────────────────────────────────────────────────────────
    # Main assault axis
    _line(client, "ROUTE",
          [DZ_FALCON, AA_RANGER,
           PL_ALPHA_W.off(0, 350), PL_BRAVO_W.off(0, 350),
           TERMINAL],
          "AXIS STEEL — Main assault route 1st/2nd PLT")
    # Breach element (3rd PLT western flank)
    _line(client, "ROUTE",
          [AA_RANGER,
           MAIN_GATE.off(200, -200),
           MAIN_GATE],
          "AXIS IRON — 3rd PLT breach route (western flank)")
    # Exfil route
    _line(client, "ROUTE",
          [TERMINAL.off(0, -100),
           PL_CHARLIE_W.off(0, 300),
           DZ_EAGLE],
          "EXFIL ROUTE — Break contact west → DZ EAGLE")
    log.info("  Routes planted")

    # ── Enemy positions ────────────────────────────────────────────────────────
    enemies = [
        (MAIN_GATE,   "ENEMY BMP-2 #1 — Main gate, reinforced position"),
        (SOUTH_QUAY,  "ENEMY BMP-2 #2 — Southern quay, hull-down position"),
        (NORTH_PIER,  "ENEMY HMG 12.7mm — North pier, static position"),
        (MANPADS,     "ENEMY MANPADS team — Terminal roof, Igla-S"),
        (PATROL_BOAT, "ENEMY Patrol boat — Moored, eastern quay"),
        (TERMINAL.off(0, 80),  "ENEMY Guard post Α — Terminal east gate"),
        (TERMINAL.off(0, -80), "ENEMY Guard post Β — Terminal west gate"),
        (DOCK_CTRL.off(60, 0), "ENEMY Guard post Γ — Dock control north"),
        (DOCK_CTRL.off(-60,0), "ENEMY Guard post Δ — Dock control south"),
        (MAIN_GATE.off(-200,0),"ENEMY Mortar position — enemy 82mm, south of gate"),
    ]
    for pos, note in enemies:
        _tobj(client, "ENEMY", pos.lat, pos.lon, note,
              affiliation="HOSTILE",
              symbol="SHGPUCA---D----")   # hostile armor
    log.info("  %d enemy positions planted", len(enemies))

    # ── Named areas ────────────────────────────────────────────────────────────
    # Port security perimeter (approximate)
    perimeter = [
        LL(51.3470, 3.1750).p(), LL(51.3490, 3.2150).p(),
        LL(51.3310, 3.2150).p(), LL(51.3310, 3.1750).p(),
    ]
    _poly(client, "ZONE", perimeter,
          "ENEMY SECURITY PERIMETER — ~80 PAX port security coy",
          affiliation="HOSTILE")
    log.info("  Enemy perimeter zone planted")

    # ── Pre-planned fire missions (81mm) ───────────────────────────────────────
    fire_ids: list[int] = []
    fires = [
        (MAIN_GATE,         "ADJUST_FIRE",  "HE",    6,  "TGT ZB-001 — Enemy main gate BMP-2"),
        (NORTH_PIER,        "FIRE_FOR_EFFECT","HE",  8,  "TGT ZB-002 — North pier HMG, mortar prep"),
        (DOCK_CTRL.off(80,0),"FIRE_FOR_EFFECT","SMOKE",4,"TGT ZB-003 — Smoke screen dock approach"),
        (SOUTH_QUAY,        "SUPPRESSION",  "HE",    6,  "TGT ZB-004 — Southern quay BMP-2 suppression"),
        (MAIN_GATE.off(-200,0),"FIRE_FOR_EFFECT","HE",8, "TGT ZB-005 — Enemy mortar position"),
    ]
    for pos, mtype, ammo, qty, desc in fires:
        fm = _fire(client, pos.lat, pos.lon, mtype, ammo, qty, desc)
        if fm: fire_ids.append(fm["id"])
    log.info("  %d pre-planned fire missions created", len(fire_ids))

    # ── OPORD ──────────────────────────────────────────────────────────────────
    plant_opord(client, fire_ids, op_ids)

    # ── Strike Package ─────────────────────────────────────────────────────────
    plant_strike_package(client, op_ids, fire_ids)

    log.info("Static plan complete.")


def plant_opord(client: httpx.Client, fire_ids: list[int], op_ids: list[int]) -> None:
    opord_body = {
        "title":         "OPORD 01 — OPERATION STEEL TIDE",
        "opord_number":  "01",
        "dtg":           "011800ZJUN2026",
        "time_zone":     "Z",
        "classification":"UNCLASSIFIED // EXERCISE",
        "references":    "FRAGO 01-26 1/75 RGR BN; ANNEXE A — Air Plan; ANNEXE B — Fire Support",
        "task_organization": (
            "TF STEEL:\n"
            "  A COY / 1-75 RGR (RANGER-6)\n"
            "    1st PLT — Assault (OBJ HAMMER)\n"
            "    2nd PLT — Assault (OBJ ANVIL)\n"
            "    3rd PLT — Breach / Block (Main Gate)\n"
            "    WPNS PLT — 2× 81mm mortar, 1× HMG\n"
            "  160th SOAR DET — 4× MH-47G (infil/exfil)\n"
            "  4× F/A-18C HORNET — CAS on call (JTAC RANGER-JTAC)\n"
            "  DUSTOFF (UH-60M) — MEDEVAC standby"
        ),
        "situation": {
            "enemy": (
                "Port security company (est 80 PAX, conscript quality) holds the LNG "
                "terminal and dock control at Port of Zeebrugge. Two BMP-2 IFVs occupy "
                "hull-down positions at the main gate (north) and southern quay. One MANPADS "
                "team (Igla-S) is roof-mounted on the terminal control building. A 12.7 mm "
                "static HMG covers the north pier. A patrol boat is moored on the eastern quay. "
                "An 82 mm mortar position is sited approximately 200 m south of the main gate. "
                "Enemy ROE: defend in place, alert state AMBER (no active sensor). "
                "CoA 1 (most likely): static defence with no counter-assault capability. "
                "CoA 2 (most dangerous): rapid reinforcement from Bruges garrison (ETA 35 min)."
            ),
            "friendly": (
                "Higher: 1-75 RGR BN conducts deep raid in support of maritime interdiction ops. "
                "Adjacent: Maritime patrol assets (P-8) maintain ISR over North Sea corridor. "
                "Own: A COY airborne, 4× MH-47G departing FOB Lombardsijde."
            ),
            "attachments": "160th SOAR, JTAC, DUSTOFF",
            "terrain_weather": (
                "Flat coastal terrain, tidal flats to the west. Wind 280/12 kt. "
                "Viz unrestricted, 1/8 cloud 2000 ft. Sea state 2. NOE route over North Sea "
                "avoids Belgian air-defence radar coverage."
            ),
        },
        "mission": (
            "A COY / 1-75 RGR REGT conducts an air-assault raid on Port of Zeebrugge "
            "LNG terminal (51.342N 3.190E) NLT H+45 to DESTROY the terminal infrastructure "
            "and NEUTRALISE the port security force in order to deny enemy use of the port "
            "for logistics resupply. Exfil complete NLT H+90."
        ),
        "execution": {
            "commanders_intent": (
                "Seize DZ FALCON NLT H+15, consolidate at AA RANGER, execute simultaneous "
                "breach and assault on OBJ HAMMER and OBJ ANVIL NLT H+45, place demolition "
                "charges, break contact to DZ EAGLE NLT H+75. Priority fires: enemy BMP-2s "
                "prior to LD. Priority task: secure MANPADS before helo exfil."
            ),
            "concept_of_operations": (
                "PHASE 1 — INFIL (H-60 to H+20):\n"
                "  4× MH-47G depart FOB Lombardsijde on NOE route over North Sea. "
                "  SHADOW-21 MQ-9 conducts pre-assault ISR. "
                "  81mm fires not yet authorised (noise discipline). "
                "\nPHASE 2 — ASSAULT (H+20 to H+60):\n"
                "  H+20: Assembly Area RANGER — RANGER-6 confirms assault.\n"
                "  H+25: Cross PL ALPHA. 3rd PLT western flank (AXIS IRON) — breach main gate.\n"
                "  H+30: 81mm fires — TGT ZB-001 (gate), ZB-002 (pier HMG), ZB-005 (mortar pos).\n"
                "  H+35: Cross PL BRAVO. 81mm fires LIFT. F/A-18 CAS HOT for immediate requests.\n"
                "  H+40: 3rd PLT clears main gate; 1st PLT clears OBJ HAMMER; 2nd PLT clears OBJ ANVIL.\n"
                "  H+45: Objectives secured. RANGER-6 confirms clearance.\n"
                "  H+45-H+60: Exploitation — demolition charges placed on LNG storage; "
                "  sensitive materials exploitation; personnel accounting.\n"
                "\nPHASE 3 — EXFIL (H+60 to H+90):\n"
                "  H+60: RANGER-6 calls DUSTOFF if CASEVAC required.\n"
                "  H+65: Cross PL CHARLIE. 3rd PLT provides rearguard.\n"
                "  H+75: Arrive DZ EAGLE. JTAC confirms airspace clear. 81mm smoke screen east.\n"
                "  H+90: MH-47s recover. Strike complete."
            ),
            "tasks_by_element": (
                "1st PLT — Main effort — Seize OBJ HAMMER (LNG terminal). "
                "Assign A Team breach, B/C assault. Neutralise MANPADS ASAP.\n"
                "2nd PLT — Supporting effort — Seize OBJ ANVIL (dock control). "
                "Maintain contact with 1st PLT right flank.\n"
                "3rd PLT — Supporting effort — Breach main gate (AXIS IRON), "
                "block north approach road, prevent reinforcement from Bruges.\n"
                "WPNS PLT — 81mm fires on pre-planned TGTs. HMG covers exfil route.\n"
                "JTAC — CAS control. HORNET 1-1 immediate on TIC call. F/A-18s carry "
                "GBU-32 JDAM + AIM-9X. On-call stack at 15,000 ft 20 NM offshore."
            ),
            "fire_support": (
                "Pre-planned 81mm targets: ZB-001 thru ZB-005 (see ANNEXE B).\n"
                "CFL: PL BRAVO. Mortar fires north of CFL require RANGER-FO approval.\n"
                "FSCL: 600 m north of PL ALPHA. CAS south requires JTAC clearance.\n"
                "4× F/A-18C HORNET: on-call H+35 to H+90. "
                "Callsigns HORNET 1-1, 1-2, 1-3, 1-4.\n"
                "MEDEVAC: DUSTOFF on 10-minute standby, located at FOB Lombardsijde."
            ),
            "rules_of_engagement": (
                "Positive identification required before engaging. "
                "Do not engage patrol boat unless it threatens exfil route. "
                "Non-combatants at port — no fire within 50 m of civilian structures "
                "without RANGER-6 approval."
            ),
        },
        "sustainment": {
            "supply": "Each Ranger carries 2× basic loads, 3 days ration, 2L water. "
                      "No resupply planned — raid profile.",
            "maintenance": "No vehicle maintenance. Individual weapon serviceability pre-mission.",
            "medical": "DUSTOFF on 10-minute strip-alert at FOB. CASEVAC via 9-liner to RANGER-6. "
                       "DUSTOFF-1/2 (MEDEVAC) collocated with AA RANGER H+20 to H+75.",
            "transportation": "4× MH-47G. Serial: STEEL-1 (COY HQ + 1PLT), STEEL-2 (2PLT), "
                              "STEEL-3 (3PLT), STEEL-4 (WPNS + MEDEVAC). "
                              "Exfil: 2 sorties from DZ EAGLE.",
        },
        "command_signal": {
            "command_post":   "RANGER-6 co-located with 1st PLT at OBJ HAMMER H+40.",
            "succession":     "RANGER-6 → RANGER-5 → RANGER-1-6.",
            "radio_freqs":    "Primary: 43.750 MHz FM. Alt: 46.500 MHz FM. "
                              "CAS: 349.800 UHF. MEDEVAC: 40.500 MHz FM.",
            "signals":        "INFIL clear: red chem-light NW corner DZ FALCON. "
                              "Objectives secure: RANGER-6 'STEEL TIDE' on primary freq. "
                              "Exfil ready: green smoke DZ EAGLE.",
            "challenge_password": "THUNDER / LIGHTNING",
        },
        "status": "PUBLISHED",
    }

    r = _post(client, "/opord", opord_body)
    if r:
        log.info("OPORD created (id=%s)", r.get("id"))
    else:
        log.warning("OPORD creation failed")


def plant_strike_package(client: httpx.Client, op_ids: list[int],
                          fire_ids: list[int]) -> None:
    # JTAC + FO operator ids (first 6 = COY HQ incl FO and JTAC)
    hq_ids = op_ids[:6] if len(op_ids) >= 6 else op_ids[:2]

    body = {
        "name":              "STRIKE PACKAGE — STEEL TIDE",
        "target_lat":        TERMINAL.lat,
        "target_lon":        TERMINAL.lon,
        "target_description": (
            "Port of Zeebrugge LNG Terminal — primary structural demolition target. "
            "Secondary: Dock control building (OBJ ANVIL)."
        ),
        "operator_ids": op_ids,
        "fire_mission_ids": fire_ids,
        "assets": {
            "air_support": [
                {
                    "aircraft":        "F/A-18C Hornet",
                    "callsign":        "HORNET 1-1",
                    "ordnance":        "2× GBU-32 JDAM, 2× AIM-9X, 578 rds 20mm",
                    "station_time_min": 75,
                    "frequency":       "349.800 UHF",
                    "notes":           "Element lead. Strike priority: MANPADS roof then BMP-2s.",
                },
                {
                    "aircraft":        "F/A-18C Hornet",
                    "callsign":        "HORNET 1-2",
                    "ordnance":        "2× GBU-32 JDAM, 2× AIM-9X, 578 rds 20mm",
                    "station_time_min": 75,
                    "frequency":       "349.800 UHF",
                    "notes":           "Wingman. Secondary target: patrol boat if threatening.",
                },
                {
                    "aircraft":        "F/A-18C Hornet",
                    "callsign":        "HORNET 1-3",
                    "ordnance":        "4× Mk-82, 2× AIM-9X, 578 rds 20mm",
                    "station_time_min": 75,
                    "frequency":       "349.800 UHF",
                    "notes":           "Armed over-watch. CAS on immediate call H+35.",
                },
                {
                    "aircraft":        "F/A-18C Hornet",
                    "callsign":        "HORNET 1-4",
                    "ordnance":        "4× Mk-82, 2× AIM-9X, 578 rds 20mm",
                    "station_time_min": 75,
                    "frequency":       "349.800 UHF",
                    "notes":           "Reserve / CASEVAC escort if DUSTOFF threatened.",
                },
            ],
            "drones": [
                {
                    "platform": "MQ-9 Reaper",
                    "callsign": "SHADOW-21",
                    "loiter_lat": DZ_FALCON.off(2000, 0).lat,
                    "loiter_lon": DZ_FALCON.off(2000, 0).lon,
                    "notes":    "Persistent ISR H-60 to H+90. EO/IR, Hellfire armed.",
                },
            ],
            "sniper_overwatch": [
                {
                    "callsign":            "OVERWATCH-1",
                    "position_lat":        TERMINAL.off(500, -600).lat,
                    "position_lon":        TERMINAL.off(500, -600).lon,
                    "sector_of_fire":      "North approach, main gate, terminal perimeter",
                    "engagement_criteria": "BMP-2 movement toward DZ FALCON or exfil route",
                },
            ],
            "comms": {
                "primary_freq":   "43.750 MHz FM",
                "alternate_freq": "46.500 MHz FM",
                "waveform":       "SINCGARS / AES-256",
                "pace_plan":      "Primary: VHF FM 43.750 / Alt: VHF FM 46.500 / "
                                  "Contingency: SAT via RANGER-5 / Emergency: burst beacon",
            },
            "assault_plan": {
                "phases": [
                    {
                        "name":        "INFIL",
                        "description": "H-60 to H+20 — Air movement FOB to DZ FALCON",
                        "actions":     "NOE flight over North Sea. SHADOW-21 pre-assault ISR. "
                                       "Maintain emission control (EMCON).",
                    },
                    {
                        "name":        "ASSAULT",
                        "description": "H+20 to H+60 — DZ FALCON → AA RANGER → objectives",
                        "actions":     "1PLT: OBJ HAMMER (terminal). 2PLT: OBJ ANVIL (dock ctrl). "
                                       "3PLT: Breach main gate, block north road. "
                                       "WPNS PLT: 81mm fires on ZB-001/002/005, smoke ZB-003.",
                    },
                    {
                        "name":        "EXPLOITATION",
                        "description": "H+45 to H+60 — Demolition and SSE",
                        "actions":     "Demolition charges on LNG tanks and pipeline manifold. "
                                       "SSE terminal control room. CASEVAC if required.",
                    },
                    {
                        "name":        "EXFIL",
                        "description": "H+60 to H+90 — Break contact → DZ EAGLE",
                        "actions":     "3PLT rearguard. 81mm smoke DZ EAGLE. "
                                       "MH-47 recovery 2 sorties. Manifest accountability.",
                    },
                ],
                "breach_points":      ["Main gate (3rd PLT)", "Terminal west fence (1st PLT A-team)"],
                "actions_on_objective": (
                    "Stack on breach point. Initiate on RANGER-6 command. "
                    "A-team breach, B-team assault, C-team overwatch. "
                    "MANPADS neutralised first by 1A before terminal entry. "
                    "Consolidate within 5 min of OBJ HAMMER clear."
                ),
                "consolidation": (
                    "Perimeter: 1PLT NE, 2PLT SE, 3PLT NW. "
                    "RANGER-7 accountability. Casualties forward to DUSTOFF. "
                    "RANGER-6 sends SALUTE to higher within 10 min."
                ),
            },
            "exfil_routes": [
                {
                    "name":        "PRIMARY",
                    "type":        "AIR",
                    "description": "MH-47G recovery at DZ EAGLE (western beach) — 2 sorties. "
                                   "Load plan: STEEL-1 (HQ+1PLT), STEEL-2 (2PLT), "
                                   "STEEL-3 (3PLT), STEEL-4 (WPNS+MEDEVAC).",
                },
                {
                    "name":        "ALTERNATE",
                    "type":        "GROUND",
                    "description": "Emergency ground exfil west along N34 coast road if "
                                   "DZ EAGLE compromised. RV at Blankenberge harbour (51.315°N 3.133°E).",
                },
                {
                    "name":        "EMERGENCY",
                    "type":        "WATER",
                    "description": "Zodiac extraction from western quay if all DZs compromised. "
                                   "Coordinate with maritime patrol on CH-15.",
                },
            ],
            "electronic_warfare": [
                {
                    "system":           "AN/PRC-155 MUOS",
                    "callsign":         "RANGER-COMMS",
                    "frequency_bands":  "UHF SATCOM",
                    "objective":        "SIGINT",
                    "notes":            "Monitor enemy push-to-talk nets 155.525 MHz during assault.",
                },
            ],
        },
    }

    r = _post(client, "/strike-packages", body)
    if r:
        log.info("Strike package created (id=%s)", r.get("id"))
        # Activate immediately
        pkid = r.get("id")
        act = client.post(f"{BASE}/strike-packages/{pkid}/activate",
                          headers=_hdr(), timeout=10)
        if act.status_code == 200:
            log.info("Strike package ACTIVATED")
    else:
        log.warning("Strike package creation failed")


# ── Operator registration ─────────────────────────────────────────────────────────

def register_operators(client: httpx.Client) -> list[int]:
    """Register Rangers; return their operator ids.

    Uses /auth/register/admin (ADMIN-only, higher rate limit).
    Falls back to callsign lookup for already-existing operators.
    """
    # Fetch current operator list for lookup
    ops_r  = client.get(f"{BASE}/operators", headers=HDR, timeout=15)
    existing: dict[str, int] = {}
    if ops_r.status_code == 200:
        for op in ops_r.json():
            existing[op["callsign"]] = op["id"]

    ids: list[int] = []
    for callsign, rank, role, _ in RANGERS:
        if callsign in existing:
            ids.append(existing[callsign])
            log.debug("  → %s already exists (id=%d)", callsign, existing[callsign])
            continue

        body = {"callsign": callsign, "password": "ranger14", "rank": rank, "role": role}
        # Use admin register endpoint — higher rate limit, ADMIN token required
        r = client.post(f"{BASE}/auth/register/admin", json=body,
                        headers=HDR, timeout=12)
        if r.status_code == 429:
            # Rate limited — wait 20 s and retry once
            log.info("  Rate limited, waiting 20 s …")
            time.sleep(20)
            r = client.post(f"{BASE}/auth/register/admin", json=body,
                            headers=HDR, timeout=12)

        if r.status_code in (200, 201):
            # Register returns TokenOut (no id) — look up by callsign
            ops_r2 = client.get(f"{BASE}/operators", headers=HDR, timeout=10)
            if ops_r2.status_code == 200:
                op = next((o for o in ops_r2.json() if o["callsign"] == callsign), None)
                if op:
                    ids.append(op["id"])
                    existing[callsign] = op["id"]
                    log.info("  ✓ %s (%s %s) id=%d", callsign, rank, role, op["id"])
        elif r.status_code == 409:
            # Created concurrently — look up
            ops_r2 = client.get(f"{BASE}/operators", headers=HDR, timeout=10)
            if ops_r2.status_code == 200:
                op = next((o for o in ops_r2.json() if o["callsign"] == callsign), None)
                if op:
                    ids.append(op["id"])
                    log.debug("  → %s adopted (id=%d)", callsign, op["id"])
        else:
            log.warning("  ! %s register failed: %d %s", callsign, r.status_code, r.text[:80])

        time.sleep(0.3)   # avoid hammering the endpoint

    log.info("Rangers ready: %d operators", len(ids))
    return ids


def assign_operators_to_mission(client: httpx.Client, mission_id: int,
                                  op_ids: list[int]) -> None:
    r = client.post(f"{BASE}/missions/{mission_id}/operators",
                    json={"operator_ids": op_ids},
                    headers=HDR, timeout=15)
    if r.status_code in (200, 201):
        log.info("Linked %d operators to mission %d", len(op_ids), mission_id)
    elif r.status_code == 409:
        # Some operators already in another mission — assign the uncontested ones
        body = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        conflicts = {c["callsign"] for c in body.get("detail", {}).get("conflicts", [])}
        free_ids  = [oid for cs, _, _, _ in RANGERS
                     if cs not in conflicts
                     for oid in [next((i for i, (c,_,_,_) in enumerate(RANGERS) if c==cs), None)]
                     if oid is not None]
        # Simpler: just re-fetch operator list and filter
        ops_r = client.get(f"{BASE}/operators", headers=HDR, timeout=10)
        if ops_r.status_code == 200:
            free = [o["id"] for o in ops_r.json()
                    if o["callsign"] not in conflicts and o["id"] in op_ids]
            if free:
                r2 = client.post(f"{BASE}/missions/{mission_id}/operators",
                                 json={"operator_ids": free},
                                 headers=HDR, timeout=15)
                log.info("Linked %d free operators (skipped %d in conflict)",
                         len(free), len(conflicts))
    else:
        log.warning("Operator assignment failed: %d %s", r.status_code, r.text[:120])


# ── Live movement ────────────────────────────────────────────────────────────────

async def live_movement(token: str, op_ids: list[int]) -> None:
    """Animate Rangers through the operation phases."""
    speed   = ARGS.speed
    TICK    = 5.0 / speed        # real seconds between updates
    SPEED_MS = 5.0               # Rangers move at 5 m/s (fast walk under fire)
    HELO_MS  = 80.0              # MH-47G ~80 m/s

    headers = {"Authorization": f"Bearer {token}",
               "X-Mission-ID": str(MID)}

    async with httpx.AsyncClient(timeout=8, verify=False) as client:
        # Initial positions — all Rangers on FOB
        positions = {oid: FOB_LAUNCH for oid in op_ids}

        async def push(oid: int, pos: LL, hdg: float = 0):
            await client.post(f"{BASE}/tracking/position",
                              json={"latitude": pos.lat, "longitude": pos.lon,
                                    "heading": hdg, "speed": SPEED_MS},
                              headers=headers)

        async def push_all(hdg: float = 0):
            for oid in op_ids:
                await push(oid, positions[oid], hdg)
            await asyncio.sleep(TICK)

        log.info("Phase 1 — INFIL: Rangers moving from FOB to DZ FALCON …")
        # Phase 1: helo flight FOB → DZ FALCON
        for _ in range(int(60 / TICK)):
            for oid in op_ids:
                positions[oid] = step(positions[oid], DZ_FALCON, HELO_MS, TICK)
            await push_all(hdg=230)

        log.info("Phase 2 — Assembly at AA RANGER …")
        for _ in range(int(30 / TICK)):
            for oid in op_ids:
                positions[oid] = step(positions[oid], AA_RANGER, SPEED_MS, TICK)
            await push_all(hdg=190)

        log.info("Phase 3 — Assault: Rangers advancing on objectives …")
        # Group 1 (first half) → OBJ HAMMER
        g1 = op_ids[:len(op_ids)//2]
        # Group 2 (second half) → OBJ ANVIL / flank
        g2 = op_ids[len(op_ids)//2:]

        for _ in range(int(90 / TICK)):
            for oid in g1:
                positions[oid] = step(positions[oid], TERMINAL, SPEED_MS, TICK)
            for oid in g2:
                positions[oid] = step(positions[oid], DOCK_CTRL, SPEED_MS, TICK)
            await push_all(hdg=185)

            # TIC alert when first operator gets close to terminal
            if (dist_m(positions[g1[0]], TERMINAL) < 200
                    and not getattr(live_movement, '_tic_sent', False)):
                live_movement._tic_sent = True
                await client.post(f"{BASE}/alerts", json={"type": "TIC"},
                                  headers=headers)
                await client.post(f"{BASE}/reports",
                                  json={"type": "CONTACT",
                                        "payload": {"location": "OBJ HAMMER perimeter",
                                                    "contact": "BMP-2 engaging from main gate",
                                                    "grid": "31UDS 8821 4310",
                                                    "action": "Assault continuing"}},
                                  headers=headers)
                log.info("TIC alert + CONTACT report sent")

        log.info("Phase 4 — Consolidation & demo charges …")
        await asyncio.sleep(20 / speed)

        log.info("Phase 5 — Exfil: Rangers moving to DZ EAGLE …")
        for _ in range(int(90 / TICK)):
            for oid in op_ids:
                positions[oid] = step(positions[oid], DZ_EAGLE, SPEED_MS, TICK)
            await push_all(hdg=260)

        # MEDEVAC report (sim)
        await client.post(f"{BASE}/reports",
                          json={"type": "CASEVAC",
                                "payload": {"line1_grid": "31UDS 8802 4315",
                                            "line2_casualties": "2",
                                            "line3_urgency": "PRIORITY",
                                            "line4_equipment": "None",
                                            "line5_patients": "2× ambulatory",
                                            "line6_security": "Troops in area",
                                            "line7_marking": "Green smoke",
                                            "line8_nationality": "US MILITARY",
                                            "line9_cbrn": "None"}},
                          headers=headers)
        log.info("9-liner CASEVAC report sent")

        log.info("Phase 6 — Helo exfil FOB …")
        for _ in range(int(60 / TICK)):
            for oid in op_ids:
                positions[oid] = step(positions[oid], FOB_LAUNCH, HELO_MS, TICK)
            await push_all(hdg=50)

        log.info("OPERATION STEEL TIDE COMPLETE — all Rangers returned to FOB")

        if True:  # loop
            live_movement._tic_sent = False
            await live_movement(token, op_ids)


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    global HDR, MID

    with httpx.Client(timeout=15) as client:
        # Login
        r = client.post(f"{BASE}/auth/login",
                        data={"username": ARGS.admin, "password": ARGS.password})
        r.raise_for_status()
        token = r.json()["access_token"]
        HDR   = {"Authorization": f"Bearer {token}"}
        log.info("Logged in as %s", ARGS.admin)

        # Reset if requested
        if ARGS.reset:
            log.info("Reset: wiping existing STEEL TIDE objects …")
            objs_r = client.get(f"{BASE}/tactical-objects", headers=HDR, timeout=15)
            if objs_r.status_code == 200:
                for obj in objs_r.json():
                    if any(kw in (obj.get("notes") or "")
                           for kw in ["STEEL TIDE", "OBJ HAMMER", "OBJ ANVIL",
                                      "DZ FALCON", "DZ EAGLE", "PL ALPHA", "PL BRAVO",
                                      "FLOT", "HORNET", "SHADOW", "ZB-", "AA RANGER"]):
                        client.delete(f"{BASE}/tactical-objects/{obj['id']}",
                                      headers=HDR, timeout=10)
                log.info("  Tactical objects cleared")

        # Create mission
        MID = sim_utils.create_mission_sync(
            client, BASE, token,
            name=ARGS.mission_name,
            description=(
                "1-75 Ranger Bn (-) air-assault raid on Port of Zeebrugge LNG terminal. "
                "Destroy terminal infrastructure, neutralise security force, exfil via DZ EAGLE."
            ),
            map_center_lat=TERMINAL.lat,
            map_center_lng=TERMINAL.lon,
            map_zoom=14,
        )
        if not MID:
            log.error("Cannot create/find mission — aborting")
            sys.exit(1)
        log.info("Mission id=%d", MID)

        # Register operators
        log.info("Registering Rangers …")
        op_ids = register_operators(client)

        # Assign operators to mission
        if op_ids:
            assign_operators_to_mission(client, MID, op_ids)

        # Plant static plan
        plant_plan(client, op_ids)

        if ARGS.no_live:
            log.info("--no-live: static plan planted. Done.")
            return

    # Live movement (async)
    log.info("Starting live movement simulation …")
    asyncio.run(live_movement(token, op_ids))


if __name__ == "__main__":
    main()
