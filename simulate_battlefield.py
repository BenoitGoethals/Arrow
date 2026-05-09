#!/usr/bin/env python3
"""
Arrow Battlefield Designer — Operation EAGLE
=============================================

Plants a coherent company-attack scenario into the tactical-graphics layer:
DELTA Company attacks enemy strongpoint OBJ EAGLE near Dendermonde, Belgium,
with 1 PL and 2 PL forward, 3 PL in reserve.

Every graphic kind in the palette gets exercised so the web map and the
Android render layer can be verified end-to-end:

  - Objective area (polygon, COY)
  - FLOT, FLET, Phase lines, Boundary (lines)
  - Attack axes at PL and SEC echelons
  - Defense (reserve), Counterattack
  - Ambush (known enemy), Block, Bypass, Withdraw

Run with the backend up and a known ADMIN account:

  uv run python simulate_battlefield.py
  uv run python simulate_battlefield.py --backend http://prod.host:6200/api
  uv run python simulate_battlefield.py --reset    # wipe existing TG objects
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from dataclasses import dataclass

import httpx

# ── Tactical graphic types the backend understands ───────────────────────────

POINT_TYPES = {"ATK_AXIS", "COUNTERATTACK", "AMBUSH", "DEF_AREA",
               "BLOCK", "BYPASS", "WITHDRAW"}
LINE_TYPES  = {"BOUNDARY", "FLET", "FLOT", "PHASE_LINE"}
POLY_TYPES  = {"OBJ_AREA"}
TG_TYPES    = POINT_TYPES | LINE_TYPES | POLY_TYPES


# ── Geo helpers ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LatLon:
    lat: float
    lon: float

    def offset_m(self, north_m: float, east_m: float) -> "LatLon":
        # At 51°N, 1° lat ≈ 111 320 m, 1° lon ≈ 69 700 m.
        # Plenty accurate for a few-km battlefield sketch.
        d_lat = north_m / 111_320.0
        d_lon = east_m  / (111_320.0 * math.cos(math.radians(self.lat)))
        return LatLon(self.lat + d_lat, self.lon + d_lon)

    def as_pair(self) -> list[float]:
        return [self.lat, self.lon]


# Centre of the operation — OBJ EAGLE, just south-east of Dendermonde
OBJ_CENTER = LatLon(51.0260, 4.1010)


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def login(client: httpx.Client, callsign: str, password: str) -> str:
    r = client.post("/auth/login", data={"username": callsign, "password": password})
    if r.status_code != 200:
        sys.exit(f"login failed ({r.status_code}): {r.text}")
    payload = r.json()
    if payload.get("mfa_required"):
        sys.exit("admin account has MFA enabled — use a non-MFA admin for the simulator")
    return payload["access_token"]


def post_object(client: httpx.Client, token: str, obj: dict) -> int:
    r = client.post(
        "/tactical-objects",
        json=obj,
        headers={"Authorization": f"Bearer {token}"},
    )
    if r.status_code != 201:
        log.warning("POST failed %s: %s", r.status_code, r.text[:200])
        return -1
    return r.json()["id"]


def reset_tactical_graphics(client: httpx.Client, token: str) -> int:
    """Delete every existing TG_* object so the sketch starts clean."""
    h = {"Authorization": f"Bearer {token}"}
    listed = client.get("/tactical-objects", headers=h).json()
    n = 0
    for o in listed:
        if o.get("type") in TG_TYPES:
            r = client.delete(f"/tactical-objects/{o['id']}", headers=h)
            if r.status_code == 204:
                n += 1
    return n


# ── Battlefield definition ───────────────────────────────────────────────────

def build_operation() -> list[dict]:
    """Return the full list of TacticalObjectIn payloads for Operation EAGLE."""
    c = OBJ_CENTER
    items: list[dict] = []

    # ── OBJ EAGLE — enemy strongpoint, polygon, company-sized objective ──
    obj_polygon = [
        c.offset_m( 250, -200), c.offset_m( 250,  200),
        c.offset_m(-250,  250), c.offset_m(-250, -200),
    ]
    items.append({
        "type": "OBJ_AREA",
        "latitude":  obj_polygon[0].lat, "longitude": obj_polygon[0].lon,
        "echelon": "COY",
        "notes":   "OBJ EAGLE — enemy company strongpoint",
        "geometry": json.dumps({
            "type": "polygon",
            "coords": [p.as_pair() for p in obj_polygon],
        }),
    })

    # ── FLET — Forward Line of Enemy Troops, ~600 m east of OBJ ──
    flet_line = [
        c.offset_m( 1500, 600), c.offset_m( 800, 700), c.offset_m(0, 700),
        c.offset_m(-800, 700), c.offset_m(-1500, 600),
    ]
    items.append({
        "type": "FLET",
        "latitude":  flet_line[0].lat, "longitude": flet_line[0].lon,
        "notes":   "Estimated FLET — coy +",
        "geometry": json.dumps({"type": "line",
                                "coords": [p.as_pair() for p in flet_line]}),
    })

    # ── FLOT — Forward Line of Own Troops, ~1500 m west of OBJ ──
    flot_line = [
        c.offset_m( 1500, -1500), c.offset_m( 600, -1450),
        c.offset_m(-600, -1450), c.offset_m(-1500, -1500),
    ]
    items.append({
        "type": "FLOT",
        "latitude":  flot_line[0].lat, "longitude": flot_line[0].lon,
        "echelon": "COY",
        "notes":   "FLOT — DELTA Coy",
        "geometry": json.dumps({"type": "line",
                                "coords": [p.as_pair() for p in flot_line]}),
    })

    # ── Phase Line ALPHA = Line of Departure (LD), along the FLOT ──
    pl_alpha = [c.offset_m( 1400, -1400), c.offset_m(-1400, -1400)]
    items.append({
        "type": "PHASE_LINE",
        "latitude":  pl_alpha[0].lat, "longitude": pl_alpha[0].lon,
        "notes":   "PL ALPHA — Line of Departure (H-hour)",
        "geometry": json.dumps({"type": "line",
                                "coords": [p.as_pair() for p in pl_alpha]}),
    })

    # ── Phase Line BRAVO = Assault Position, ~400 m west of OBJ ──
    pl_bravo = [c.offset_m( 1200, -500), c.offset_m(-1200, -500)]
    items.append({
        "type": "PHASE_LINE",
        "latitude":  pl_bravo[0].lat, "longitude": pl_bravo[0].lon,
        "notes":   "PL BRAVO — Assault Position",
        "geometry": json.dumps({"type": "line",
                                "coords": [p.as_pair() for p in pl_bravo]}),
    })

    # ── Boundary between 1 PL (north) and 2 PL (south), east-west ──
    boundary = [c.offset_m(0, -1400), c.offset_m(0, 800)]
    items.append({
        "type": "BOUNDARY",
        "latitude":  boundary[0].lat, "longitude": boundary[0].lon,
        "echelon": "PL",
        "notes":   "Inter-platoon boundary  1 PL // 2 PL",
        "geometry": json.dumps({"type": "line",
                                "coords": [p.as_pair() for p in boundary]}),
    })

    # ── 1 PL — main effort, attack from north-west ──
    p_1pl = c.offset_m(700, -700)
    items.append({
        "type": "ATK_AXIS",
        "latitude": p_1pl.lat, "longitude": p_1pl.lon,
        "rotation": 135,                              # facing south-east
        "echelon": "PL",
        "notes":   "1 PL — main effort, AXIS HAWK",
    })
    # 1 PL — two sections forward
    items.append({
        "type": "ATK_AXIS",
        "latitude": c.offset_m(900, -500).lat,
        "longitude": c.offset_m(900, -500).lon,
        "rotation": 135, "echelon": "SEC",
        "notes": "1-1 SEC",
    })
    items.append({
        "type": "ATK_AXIS",
        "latitude": c.offset_m(500, -900).lat,
        "longitude": c.offset_m(500, -900).lon,
        "rotation": 120, "echelon": "SEC",
        "notes": "1-2 SEC",
    })
    # Team-level pinpoint move within 1-1 SEC
    items.append({
        "type": "ATK_AXIS",
        "latitude": c.offset_m(950, -350).lat,
        "longitude": c.offset_m(950, -350).lon,
        "rotation": 140, "echelon": "TM",
        "notes": "1-1-A TM lead",
    })

    # ── 2 PL — supporting effort, attack from south-west ──
    p_2pl = c.offset_m(-700, -700)
    items.append({
        "type": "ATK_AXIS",
        "latitude": p_2pl.lat, "longitude": p_2pl.lon,
        "rotation": 45,                               # facing north-east
        "echelon": "PL",
        "notes":   "2 PL — supporting effort, AXIS FALCON",
    })
    items.append({
        "type": "ATK_AXIS",
        "latitude": c.offset_m(-500, -900).lat,
        "longitude": c.offset_m(-500, -900).lon,
        "rotation": 60, "echelon": "SEC",
        "notes": "2-1 SEC",
    })
    items.append({
        "type": "ATK_AXIS",
        "latitude": c.offset_m(-900, -500).lat,
        "longitude": c.offset_m(-900, -500).lon,
        "rotation": 30, "echelon": "SEC",
        "notes": "2-2 SEC",
    })

    # ── 3 PL — reserve in hasty defense at LD ──
    items.append({
        "type": "DEF_AREA",
        "latitude": c.offset_m(0, -1300).lat,
        "longitude": c.offset_m(0, -1300).lon,
        "rotation": 90,           # opening east, toward the enemy
        "echelon": "PL",
        "notes": "3 PL — reserve, hasty defense at LD",
    })

    # ── Counterattack — pre-planned, from reserve into south flank ──
    items.append({
        "type": "COUNTERATTACK",
        "latitude": c.offset_m(-300, -1100).lat,
        "longitude": c.offset_m(-300, -1100).lon,
        "rotation": 60,
        "echelon": "PL",
        "notes": "ON-ORDER CATK — 3 PL into south flank if 2 PL stalls",
    })

    # ── Known enemy ambush position — north chokepoint ──
    items.append({
        "type": "AMBUSH",
        "latitude": c.offset_m(1100, -100).lat,
        "longitude": c.offset_m(1100, -100).lon,
        "rotation": 225,          # opens south-west, covering our axis
        "echelon": "SEC",
        "notes": "EN AMBUSH — section, RPG + MG, confirmed by recce",
    })

    # ── Bypass corridor around the ambush ──
    items.append({
        "type": "BYPASS",
        "latitude": c.offset_m(1300, -300).lat,
        "longitude": c.offset_m(1300, -300).lon,
        "rotation": 90,
        "echelon": "PL",
        "notes": "Bypass north of ambush — 1 PL alt route",
    })

    # ── Block — prevent enemy reinforcement from the east ──
    items.append({
        "type": "BLOCK",
        "latitude": c.offset_m(0, 1100).lat,
        "longitude": c.offset_m(0, 1100).lon,
        "rotation": 90,           # block facing east
        "echelon": "COY",
        "notes": "Block east — interdict EN reinforcement axis",
    })

    # ── Withdraw route — back through LD if attack culminates ──
    items.append({
        "type": "WITHDRAW",
        "latitude": c.offset_m(0, -200).lat,
        "longitude": c.offset_m(0, -200).lon,
        "rotation": 270,          # arrow points west (rear)
        "echelon": "COY",
        "notes": "Withdraw route — through PL ALPHA, RV at FLOT centre",
    })

    return items


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Arrow battlefield designer")
    parser.add_argument("--backend",  default="http://localhost:6001",
                        help="Backend base URL (e.g. http://host:6200/api in prod)")
    parser.add_argument("--admin",    default="benoit",
                        help="ADMIN callsign (default: benoit)")
    parser.add_argument("--password", default="ranger14",
                        help="ADMIN password (default: ranger14)")
    parser.add_argument("--reset",    action="store_true",
                        help="Delete every existing tactical-graphic before planting")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    global log
    log = logging.getLogger("battlefield")

    with httpx.Client(base_url=args.backend.rstrip("/"), timeout=15.0) as client:
        log.info("Logging in as %s @ %s …", args.admin, args.backend)
        token = login(client, args.admin, args.password)
        log.info("Authenticated.")

        if args.reset:
            n = reset_tactical_graphics(client, token)
            log.info("Reset: removed %d existing tactical graphics.", n)

        items = build_operation()
        log.info("Planting Operation EAGLE — %d tactical graphics around %.4f, %.4f",
                 len(items), OBJ_CENTER.lat, OBJ_CENTER.lon)

        ok = 0
        for item in items:
            obj_id = post_object(client, token, item)
            if obj_id > 0:
                ok += 1
                tag = item.get("echelon") or "—"
                label = (item.get("notes") or item["type"]).split("\n", 1)[0][:60]
                log.info("  + #%-4d  %-13s  %-4s  %s", obj_id, item["type"], tag, label)

    log.info("Done. %d / %d graphics planted.", ok, len(items))
    log.info("Open the web Tactical Map — pan to %.4f, %.4f and toggle the "
             "Tactical Graphics panel to see the operation.",
             OBJ_CENTER.lat, OBJ_CENTER.lon)


if __name__ == "__main__":
    main()
