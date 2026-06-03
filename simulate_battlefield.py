#!/usr/bin/env python3
"""
Arrow Battlefield Designer — Operation IRON ARDENNES
====================================================

Plants FOUR company-level attack plans against four real villages in the
Belgian Ardennes:

  · A CO  attacks  OBJ HAWK   at Bastogne
  · B CO  attacks  OBJ EAGLE  at Houffalize
  · C CO  attacks  OBJ FALCON at La Roche-en-Ardenne
  · D CO  attacks  OBJ KITE   at Vielsalm

Each plan exercises every tactical graphic in the palette and adds realistic
enemy units (BMP, T-72, ATGM, mortar, sniper, MANPADS) and friendly POIs
(CP, BAS, LZ, AMMO/POL points), tagged with NATO echelon and FRIENDLY /
ENEMY affiliation so the renderer can colour them correctly.

Run:
  uv run python simulate_battlefield.py
  uv run python simulate_battlefield.py --backend https://78.21.255.210:6001
  uv run python simulate_battlefield.py --reset      # wipe existing TGs first
  uv run python simulate_battlefield.py --no-move    # plan-only (no movement in this simulator)
  uv run python simulate_battlefield.py --steps 60 --dt 1.5
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from dataclasses import dataclass
import httpx

import sim_utils

# ── Path-prefix handling ─────────────────────────────────────────────────────
_path_prefix: str = ""
MISSION_ID: int | None = None


def _p(path: str) -> str:
    if not _path_prefix or path.startswith(_path_prefix + "/") or path == _path_prefix:
        return path
    return _path_prefix + path

# ── Tactical graphic types the backend understands ───────────────────────────
POINT_TG_TYPES = {"ATK_AXIS", "COUNTERATTACK", "AMBUSH", "DEF_AREA",
                  "BLOCK", "BYPASS", "WITHDRAW"}
LINE_TG_TYPES  = {"BOUNDARY", "FLET", "FLOT", "PHASE_LINE"}
POLY_TG_TYPES  = {"OBJ_AREA"}
ALL_TG_TYPES   = POINT_TG_TYPES | LINE_TG_TYPES | POLY_TG_TYPES
NON_TG_TYPES   = {"ENEMY", "POI", "MARKER", "OBJECTIVE", "ROUTE", "ZONE"}


# ── Geo helpers ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LatLon:
    lat: float
    lon: float

    def offset_m(self, north_m: float, east_m: float) -> "LatLon":
        d_lat = north_m / 111_320.0
        d_lon = east_m  / (111_320.0 * math.cos(math.radians(self.lat)))
        return LatLon(self.lat + d_lat, self.lon + d_lon)

    def bearing_m(self, bearing_deg: float, distance_m: float) -> "LatLon":
        rad = math.radians(bearing_deg)
        return self.offset_m(
            north_m=distance_m * math.cos(rad),
            east_m =distance_m * math.sin(rad),
        )

    def as_pair(self) -> list[float]:
        return [self.lat, self.lon]


# ── Four Ardennes objectives, real coordinates ──────────────────────────────
PLANS = [
    # (CO,       OBJ name,  village,            centre,                       axis bearing °)
    ("A CO",    "HAWK",    "Bastogne",          LatLon(50.0028, 5.7178), 270.0),  # attack from E → W
    ("B CO",    "EAGLE",   "Houffalize",        LatLon(50.1300, 5.7910), 210.0),  # from NE → SW
    ("C CO",    "FALCON",  "La Roche-en-Ardenne", LatLon(50.1817, 5.5783), 90.0),  # from W → E
    ("D CO",    "KITE",    "Vielsalm",          LatLon(50.2811, 5.9128), 180.0),  # from N → S
]


# ── HTTP helpers ─────────────────────────────────────────────────────────────
def login(client: httpx.Client, callsign: str, password: str) -> str:
    r = client.post(_p("/auth/login"), data={"username": callsign, "password": password})
    if r.status_code != 200:
        sys.exit(f"login failed ({r.status_code}): {r.text}")
    payload = r.json()
    if payload.get("mfa_required"):
        sys.exit("admin account has MFA enabled — use a non-MFA admin for the simulator")
    return payload["access_token"]


def post_object(client: httpx.Client, token: str, obj: dict) -> int:
    h: dict[str, str] = {"Authorization": f"Bearer {token}"}
    if MISSION_ID:
        h["X-Mission-ID"] = str(MISSION_ID)
    r = client.post(_p("/tactical-objects"), json=obj, headers=h)
    if r.status_code != 201:
        log.warning("POST failed %s: %s", r.status_code, r.text[:200])
        return -1
    return r.json()["id"]


def reset_tactical_graphics(client: httpx.Client, token: str) -> int:
    h = {"Authorization": f"Bearer {token}"}
    listed = client.get(_p("/tactical-objects"), headers=h).json()
    n = 0
    for o in listed:
        if o.get("type") in (ALL_TG_TYPES | NON_TG_TYPES):
            r = client.delete(_p(f"/tactical-objects/{o['id']}"), headers=h)
            if r.status_code == 204:
                n += 1
    return n


# ── Plan builder ─────────────────────────────────────────────────────────────
def build_company_plan(coy: str, obj_name: str, village: str,
                       centre: LatLon, axis_bearing: float) -> list[dict]:
    """Return the full set of TacticalObjectIn payloads for one company plan.

    Axis convention: ``axis_bearing`` is the bearing (clockwise from N) FROM
    which the friendly attack comes — i.e. the arrow points opposite to this.
    Phase lines are perpendicular to the axis at successive depths.
    """
    items: list[dict] = []

    # Heading of the attack arrow (away from AA, into OBJ)
    atk_heading = (axis_bearing + 180.0) % 360.0
    perp_left   = (atk_heading - 90.0) % 360.0
    perp_right  = (atk_heading + 90.0) % 360.0

    # Anchors for symmetric flanks (left/right relative to the attack heading)
    LEFT_M  = 700
    RIGHT_M = 700
    DEPTH_FORWARD = 2_500    # distance from OBJ toward AA along the axis
    DEPTH_FLET    = 600      # FLET sits forward of OBJ centre by this much

    aa            = centre.bearing_m(axis_bearing, DEPTH_FORWARD)
    aa_left       = aa.bearing_m(perp_left,  LEFT_M)
    aa_right      = aa.bearing_m(perp_right, RIGHT_M)
    pl_atk_left   = aa.bearing_m(atk_heading, 600).bearing_m(perp_left,  LEFT_M)
    pl_atk_right  = aa.bearing_m(atk_heading, 600).bearing_m(perp_right, RIGHT_M)
    pl_obj_left   = centre.bearing_m(axis_bearing, 600).bearing_m(perp_left,  LEFT_M)
    pl_obj_right  = centre.bearing_m(axis_bearing, 600).bearing_m(perp_right, RIGHT_M)
    pl_exp_left   = centre.bearing_m(atk_heading, 800).bearing_m(perp_left,  LEFT_M)
    pl_exp_right  = centre.bearing_m(atk_heading, 800).bearing_m(perp_right, RIGHT_M)
    flet_left     = centre.bearing_m(axis_bearing, DEPTH_FLET).bearing_m(perp_left,  LEFT_M)
    flet_right    = centre.bearing_m(axis_bearing, DEPTH_FLET).bearing_m(perp_right, RIGHT_M)
    flot_left     = aa.bearing_m(perp_left,  LEFT_M  + 300)
    flot_right    = aa.bearing_m(perp_right, RIGHT_M + 300)
    bndy_a        = aa
    bndy_b        = centre.bearing_m(atk_heading, 400)

    def tg(type_: str, lat: float, lon: float, *,
           affiliation: str = "FRIENDLY", echelon: str = "",
           notes: str = "", rotation: float = 0.0,
           geometry: str = "") -> dict:
        return {
            "type": type_, "latitude": lat, "longitude": lon,
            "affiliation": affiliation, "echelon": echelon,
            "notes": notes, "rotation": rotation, "geometry": geometry,
            "symbol_code": "", "visibility": "COMPANY",
        }

    def line(type_: str, pts: list[LatLon]) -> dict:
        return tg(type_, pts[0].lat, pts[0].lon,
                  geometry=f'{{"type":"line","coords":{[p.as_pair() for p in pts]}}}'
                          .replace("'", '"'))

    def poly(type_: str, pts: list[LatLon], **kw) -> dict:
        d = tg(type_, pts[0].lat, pts[0].lon,
               geometry=f'{{"type":"polygon","coords":{[p.as_pair() for p in pts]}}}'
                       .replace("'", '"'), **kw)
        return d

    # ── 1. Friendly OBJ — polygon around the village ─────────────────────
    obj_poly = [
        centre.offset_m( 350, -300), centre.offset_m( 350,  300),
        centre.offset_m(-250,  350), centre.offset_m(-250, -350),
    ]
    items.append(poly("OBJ_AREA", obj_poly, echelon="COY",
                      notes=f"OBJ {obj_name} — {coy} objective ({village})"))

    # ── 2. Friendly axes of advance — main + supporting ─────────────────
    items.append(tg("ATK_AXIS",
                    *aa_left.bearing_m(atk_heading, 500).as_pair(),
                    echelon="PL", rotation=atk_heading,
                    notes=f"{coy} main effort — 1 PL axis to OBJ {obj_name}"))
    items.append(tg("ATK_AXIS",
                    *aa_right.bearing_m(atk_heading, 500).as_pair(),
                    echelon="PL", rotation=atk_heading,
                    notes=f"{coy} supporting effort — 2 PL axis to OBJ {obj_name}"))

    # ── 3. Friendly defensive / supporting graphics ─────────────────────
    items.append(tg("DEF_AREA",
                    *centre.bearing_m(atk_heading, 1_200).as_pair(),
                    echelon="PL", rotation=axis_bearing,
                    notes=f"{coy} 3 PL reserve / consolidation BP"))
    items.append(tg("COUNTERATTACK",
                    *centre.bearing_m(atk_heading, 1_400).bearing_m(perp_right, 400).as_pair(),
                    echelon="PL", rotation=axis_bearing,
                    notes=f"{coy} 3 PL CT-ATK BPT — east flank"))
    items.append(tg("BLOCK",
                    *centre.bearing_m(perp_left, 1_100).as_pair(),
                    echelon="SEC", rotation=perp_right,
                    notes=f"{coy} block enemy reinforcement from W"))
    items.append(tg("BYPASS",
                    *centre.bearing_m(perp_right, 700).as_pair(),
                    echelon="PL", rotation=atk_heading,
                    notes=f"{coy} bypass route — right flank"))
    items.append(tg("WITHDRAW",
                    *aa.bearing_m(atk_heading, 200).as_pair(),
                    echelon="PL", rotation=axis_bearing,
                    notes=f"{coy} withdrawal route via AA"))

    # ── 4. Enemy graphics — defending the village ───────────────────────
    items.append(tg("DEF_AREA",
                    *centre.offset_m(50, 0).as_pair(),
                    affiliation="ENEMY", echelon="COY", rotation=axis_bearing,
                    notes=f"Enemy mech inf coy defends {village}"))
    items.append(tg("AMBUSH",
                    *centre.bearing_m(axis_bearing, 1_200).bearing_m(perp_left, 300).as_pair(),
                    affiliation="ENEMY", echelon="SEC", rotation=atk_heading,
                    notes="Suspected enemy ambush on approach"))

    # ── 5. Line graphics (lines need geometry coords list) ───────────────
    items.append(line("FLOT", [flot_left, flot_right]))
    items[-1]["echelon"] = "COY"
    items[-1]["notes"]   = f"FLOT — {coy} line of own troops"

    items.append(line("FLET", [flet_left, flet_right]))
    items[-1]["affiliation"] = "ENEMY"
    items[-1]["echelon"]     = "COY"
    items[-1]["notes"]       = f"FLET — enemy forward line at {village}"

    items.append(line("PHASE_LINE", [pl_atk_left, pl_atk_right]))
    items[-1]["notes"] = f"PL ATTACK — {coy} LD"
    items.append(line("PHASE_LINE", [pl_obj_left, pl_obj_right]))
    items[-1]["notes"] = f"PL {obj_name} — limit of advance"
    items.append(line("PHASE_LINE", [pl_exp_left, pl_exp_right]))
    items[-1]["notes"] = f"PL EXPLOIT — beyond {village}"

    items.append(line("BOUNDARY", [bndy_a, bndy_b]))
    items[-1]["echelon"] = "PL"
    items[-1]["notes"]   = f"{coy} 1/2 PL boundary"

    # ── 6. Enemy units (ENEMY type, MIL-STD-2525C SIDC) ──────────────────
    enemy_units = [
        ("Enemy mech inf platoon",  "SHGPUCIZ----", centre.offset_m( 100,  -50)),
        ("Enemy T-72 platoon",      "SHGPUCAA----", centre.offset_m( 200,  150)),
        ("Enemy AT/ATGM team",      "SHGPUCAA---F", centre.offset_m( -80,  120)),
        ("Enemy 120 mm mortar",     "SHGPUCFHE---", centre.offset_m( 350,  -50)),
        ("Enemy sniper team",       "SHGPUCFS----", centre.offset_m(-150,  -50)),
        ("Enemy MANPADS",           "SHGPUCDS----", centre.offset_m( 300,  300)),
        ("Enemy technical w/ DShK", "SHGPEVAT----", centre.offset_m(  50, -250)),
    ]
    for desc, sidc, ll in enemy_units:
        items.append({
            "type": "ENEMY", "symbol_code": sidc,
            "latitude": ll.lat, "longitude": ll.lon,
            "affiliation": "ENEMY",
            "notes": f"{desc} — IVO {village}",
            "echelon": "", "rotation": 0.0, "geometry": "",
            "visibility": "COMPANY",
        })

    # ── 7. Friendly POIs (CCP, BAS, LZ, fuel, ammo) ──────────────────────
    poi_units = [
        ("CCP",             "SFGPIME-----", aa.bearing_m(axis_bearing, 200)),
        ("BAS / role 1",    "SFGPIMS-----", aa.bearing_m(axis_bearing, 350)),
        ("LZ ALPHA",        "SFGPIBA-----", aa.bearing_m(perp_right, 500)),
        ("AMMO point",      "SFGPIRP-----", aa.bearing_m(perp_left, 400)),
        ("POL point",       "SFGPIRP-----", aa.bearing_m(axis_bearing, 450).bearing_m(perp_right, 200)),
        ("HQ / TOC",        "SFGPUH------", aa.bearing_m(axis_bearing, 250).bearing_m(perp_left, 150)),
    ]
    for desc, sidc, ll in poi_units:
        items.append({
            "type": "POI", "symbol_code": sidc,
            "latitude": ll.lat, "longitude": ll.lon,
            "affiliation": "FRIENDLY",
            "notes": f"{coy} {desc}",
            "echelon": "", "rotation": 0.0, "geometry": "",
            "visibility": "COMPANY",
        })

    return items


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    default_backend = (
        os.environ.get("ARROW_BACKEND_URL")
        or sim_utils.load_saved_backend()
        or "http://localhost:6001"
    )
    parser = argparse.ArgumentParser(description="Arrow battlefield — Operation IRON ARDENNES")
    parser.add_argument("--backend",
                        default=default_backend,
                        help=f"Backend base URL (defaults to last-used: {default_backend}). "
                             "May include a path prefix, e.g. https://78.21.255.210:6200/api")
    parser.add_argument("--admin",    default="benoit", help="ADMIN callsign")
    parser.add_argument("--password", default="ranger14", help="ADMIN password")
    parser.add_argument("--reset",    action="store_true",
                        help="Delete every existing tactical-graphic/enemy/POI before planting")
    parser.add_argument("--mission-name", default="Operation Iron Ardennes",
                        help="Mission name to create or adopt (default: Operation Iron Ardennes)")
    parser.add_argument("--no-move",  action="store_true",
                        help="Plan-only mode — accepted for interface parity (no movement in this simulator)")
    parser.add_argument("--steps",    type=int, default=80,
                        help="Movement steps — accepted for interface parity (not used by this simulator)")
    parser.add_argument("--dt",       type=float, default=2.0,
                        help="Seconds between steps — accepted for interface parity (not used by this simulator)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    global log, _path_prefix, MISSION_ID
    log = logging.getLogger("battlefield")

    origin, _path_prefix = sim_utils.split_base(args.backend)
    with httpx.Client(base_url=origin, timeout=15.0) as client:
        log.info("Logging in as %s @ %s …", args.admin, args.backend)
        token = login(client, args.admin, args.password)
        log.info("Authenticated.")
        sim_utils.save_backend(args.backend)
        MISSION_ID = sim_utils.create_mission_sync(
            client, args.backend, token, args.mission_name,
            map_center_lat=50.12, map_center_lng=5.72, map_zoom=11)

        if args.reset:
            n = reset_tactical_graphics(client, token)
            log.info("Reset: removed %d existing tactical / enemy / POI objects.", n)

        total_ok, total_all = 0, 0
        for coy, obj_name, village, centre, bearing in PLANS:
            items = build_company_plan(coy, obj_name, village, centre, bearing)
            total_all += len(items)
            log.info("── %s · OBJ %s · %s (%.4f, %.4f) — %d objects",
                     coy, obj_name, village, centre.lat, centre.lon, len(items))
            for item in items:
                obj_id = post_object(client, token, item)
                if obj_id > 0:
                    total_ok += 1
                    aff   = item.get("affiliation", "FRIENDLY")
                    ech   = item.get("echelon") or "—"
                    label = (item.get("notes") or item["type"]).split("\n", 1)[0][:60]
                    log.info("   + #%-4d %-13s %-8s %-4s  %s",
                             obj_id, item["type"], aff, ech, label)

    log.info("Done. %d / %d objects planted across %d company plans.",
             total_ok, total_all, len(PLANS))
    log.info("Centre of mass: Belgian Ardennes (~50.15 N, 5.75 E). Open the "
             "Tactical Map and pan to one of the four objectives.")


if __name__ == "__main__":
    main()
