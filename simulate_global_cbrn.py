"""Operation REGNUM IGNIS — global CBRN exchange simulator.

Generates a wave of NATO CBRN-1 (initial observation) reports covering a
hypothetical exchange between three factions:

    NATO   ── chemical / radiological / low-yield nuclear strikes on
              Russian C2 and key Chinese ports
    RUSSIA ── chemical, radiological and nuclear strikes on NATO HQ and
              forward air bases across Europe and the Pacific
    CHINA  ── chemical and biological strikes on NATO assets in the Pacific
              theatre, plus border exchanges with Russia

Each strike becomes a `/reports` POST with `type="CBRN_4"` and the payload
dict the desktop / Android CBRN map overlay expects (agent_category, serial,
dtg, delivery, wind_direction, wind_speed_kts, latitude, longitude — plus
informational fields like attacker / agent / yield_kt / description).

Re-uses the same URL-persistence + path-prefix conventions as
`simulate_battlefield.py`: pass `--backend http://host/api` once and the URL
is remembered in `~/.config/arrow/simulator.json` for subsequent runs.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import httpx

import sim_utils

UTC = timezone.utc

_path_prefix: str = ""
MISSION_ID: int | None = None


def _p(path: str) -> str:
    if not _path_prefix or path.startswith(_path_prefix + "/") or path == _path_prefix:
        return path
    return _path_prefix + path


# ── Targets ─────────────────────────────────────────────────────────────────
# (display_name, latitude, longitude)
NATO_EUROPE = [
    ("Brussels (HQ NATO)",      50.8503,   4.3517),
    ("Paris (FR HQ)",           48.8566,   2.3522),
    ("Berlin (DE HQ)",          52.5200,  13.4050),
    ("London (UK HQ)",          51.5074,  -0.1278),
    ("Ramstein AB (DE)",        49.4366,   7.5870),
    ("Lakenheath AB (UK)",      52.4093,   0.5615),
    ("Aviano AB (IT)",          46.0319,  12.5965),
    ("Incirlik AB (TR)",        37.0017,  35.4253),
    ("Naples (NAVSO IT)",       40.8518,  14.2681),
    ("Rota (ES Navy)",          36.6234,  -6.3500),
    ("Geilenkirchen (DE)",      50.9608,   6.0431),
]
NATO_AMERICAS = [
    ("Washington DC",           38.9072, -77.0369),
    ("Norfolk Naval Base",      36.8458, -76.2870),
    ("Pearl Harbor (HI)",       21.3530,-157.9554),
]
NATO_PACIFIC = [
    ("Yokosuka (JP)",           35.2918, 139.6707),
    ("Andersen AFB (Guam)",     13.5803, 144.9239),
    ("Taipei",                  25.0330, 121.5654),
    ("Subic Bay (PH)",          14.7833, 120.2833),
]

RU_TARGETS = [
    ("Moscow",                  55.7558,  37.6173),
    ("St. Petersburg",          59.9311,  30.3609),
    ("Kaliningrad",             54.7104,  20.4522),
    ("Sevastopol",              44.6166,  33.5254),
    ("Murmansk",                68.9585,  33.0827),
    ("Volgograd",               48.7080,  44.5133),
    ("Novosibirsk",             55.0084,  82.9357),
    ("Vladivostok",             43.1198, 131.8869),
    ("Plesetsk Cosmodrome",     62.9269,  40.5772),
]

CN_TARGETS = [
    ("Beijing",                 39.9042, 116.4074),
    ("Shanghai",                31.2304, 121.4737),
    ("Guangzhou",               23.1291, 113.2644),
    ("Shenzhen",                22.5429, 114.0596),
    ("Chongqing",               29.4316, 106.9123),
    ("Hainan (Naval)",          20.0179, 110.3492),
    ("Urumqi",                  43.8256,  87.6168),
]


@dataclass
class Strike:
    attacker: str       # NATO | RU | CN
    target:   str       # display name
    lat:      float
    lon:      float
    category: str       # C / B / R / N
    agent:    str       # specific agent name
    delivery: str       # GROUND | AIR | ARTILLERY | MISSILE | UNKNOWN
    wind_dir: float     # 0-359 (meteo direction wind is FROM)
    wind_kts: float
    yield_kt: float | None
    minutes_ago: int
    serial_n: int = 0   # assigned per-attacker during scenario build


# Agent menus per category
_AGENTS = {
    "C": ["VX nerve agent", "Sarin (GB)", "Soman (GD)", "Mustard (HD)", "Novichok-A234"],
    "B": ["Anthrax (B. anthracis)", "Plague (Y. pestis)", "Tularemia", "Botulinum toxin"],
    "R": ["Cs-137 dirty bomb", "Co-60 dirty bomb", "Sr-90 dispersal"],
    "N": ["Tactical nuclear (sub-kT)", "Strategic warhead"],
}


def _serial(attacker: str, cat: str, n: int) -> str:
    return f"{attacker}-{cat}-{n:03d}"


def _rand_strike(rng: random.Random, attacker: str, target: tuple[str, float, float],
                 cat_weights: dict[str, int], minutes_ago: int) -> Strike:
    cat = rng.choices(list(cat_weights), weights=list(cat_weights.values()))[0]
    return Strike(
        attacker = attacker,
        target   = target[0],
        lat      = target[1],
        lon      = target[2],
        category = cat,
        agent    = rng.choice(_AGENTS[cat]),
        delivery = rng.choices(
            ["MISSILE", "AIR", "ARTILLERY", "GROUND", "UNKNOWN"],
            weights=[5, 4, 2, 1, 1])[0],
        wind_dir = rng.uniform(0, 360),
        wind_kts = round(rng.uniform(4, 22), 1),
        yield_kt = round(rng.uniform(0.3, 150), 1) if cat == "N" else None,
        minutes_ago = minutes_ago,
    )


def build_scenario(rng: random.Random) -> list[Strike]:
    """Compose the full exchange. Returns strikes ordered oldest-first."""
    strikes: list[Strike] = []
    counter: dict[str, int] = {"NATO": 0, "RU": 0, "CN": 0}

    def add(attacker: str, t: tuple[str, float, float], weights: dict[str, int], mins_ago: int):
        counter[attacker] += 1
        strikes.append(_rand_strike(rng, attacker, t, weights, mins_ago))

    # — Phase I (T-720..T-540 min): RU opens with chemical strikes on NATO Europe —
    for i, t in enumerate(NATO_EUROPE[:6]):
        add("RU", t, {"C": 6, "R": 1}, 720 - i * 30)
    # — Phase II (T-540..T-420): CN strikes Pacific NATO with chem/bio —
    for i, t in enumerate(NATO_PACIFIC):
        add("CN", t, {"C": 4, "B": 3}, 540 - i * 30)
    # — Phase III (T-420..T-300): NATO retaliates on RU C2 with chem/radio —
    for i, t in enumerate(RU_TARGETS[:6]):
        add("NATO", t, {"C": 4, "R": 3, "N": 1}, 420 - i * 25)
    # — Phase IV (T-300..T-180): NATO strikes CN ports with chem/radio —
    for i, t in enumerate(CN_TARGETS[:5]):
        add("NATO", t, {"C": 3, "R": 3}, 300 - i * 25)
    # — Phase V (T-180..T-90): RU escalates with radiological + low-yield N on NATO Americas —
    for i, t in enumerate(NATO_AMERICAS):
        add("RU", t, {"R": 3, "N": 2}, 180 - i * 30)
    # — Phase VI (T-180..T-60): Sino-Russian border exchange —
    add("CN", ("Vladivostok",       43.1198, 131.8869), {"C": 1, "R": 1}, 150)
    add("RU", ("Urumqi",            43.8256,  87.6168), {"C": 1, "R": 1}, 120)
    add("CN", ("Plesetsk Cosmodrome", 62.9269, 40.5772), {"N": 1},          90)
    # — Phase VII (T-90..T-0): final wave — strategic N exchange on capitals —
    add("RU",  ("Washington DC",  38.9072, -77.0369),  {"N": 1}, 60)
    add("NATO", ("Moscow",        55.7558,  37.6173),  {"N": 1}, 45)
    add("NATO", ("Beijing",       39.9042, 116.4074),  {"N": 1}, 30)
    add("CN",   ("Brussels (HQ NATO)", 50.8503, 4.3517), {"R": 1, "N": 1}, 15)

    # Assign per-attacker serials in order
    serial_idx: dict[str, int] = {"NATO": 0, "RU": 0, "CN": 0}
    for s in strikes:
        serial_idx[s.attacker] += 1
        s.serial_n = serial_idx[s.attacker]
    return strikes


# ── HTTP helpers ────────────────────────────────────────────────────────────
def login(client: httpx.Client, callsign: str, password: str) -> str:
    r = client.post(_p("/auth/login"), data={"username": callsign, "password": password})
    if r.status_code != 200:
        sys.exit(f"login failed ({r.status_code}): {r.text}")
    payload = r.json()
    if payload.get("mfa_required"):
        sys.exit("admin account has MFA enabled — use a non-MFA admin for the simulator")
    return payload["access_token"]


def post_strike(client: httpx.Client, token: str, s: Strike, now: datetime) -> bool:
    dtg = (now - timedelta(minutes=s.minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "msg_type":       "CBRN_4",
        "attacker":       s.attacker,
        "target":         s.target,
        "agent_category": s.category,
        "agent":          s.agent,
        "serial":         _serial(s.attacker, s.category, s.serial_n or 1),
        "dtg":            dtg,
        "delivery":       s.delivery,
        "wind_direction": round(s.wind_dir, 1),
        "wind_speed_kts": s.wind_kts,
        "wind_speed":     round(s.wind_kts * 1.852, 1),  # km/h
        "latitude":       s.lat,
        "longitude":      s.lon,
        "description":    f"{s.attacker} {s.category} strike: {s.agent} on {s.target}"
                          + (f" ({s.yield_kt:g} kT)" if s.yield_kt else ""),
    }
    if s.yield_kt is not None:
        payload["yield_kt"] = s.yield_kt
    body = {"type": "CBRN_4", "payload": payload}
    h: dict[str, str] = {"Authorization": f"Bearer {token}"}
    if MISSION_ID:
        h["X-Mission-ID"] = str(MISSION_ID)
    r = client.post(_p("/reports"), json=body, headers=h)
    if r.status_code != 201:
        log.warning("POST /reports failed %s: %s", r.status_code, r.text[:200])
        return False
    return True


def reset_existing_cbrn(client: httpx.Client, token: str) -> int:
    h = {"Authorization": f"Bearer {token}"}
    reports = client.get(_p("/reports"), headers=h).json()
    n = 0
    for r in reports:
        if r.get("type", "").upper().startswith("CBRN"):
            # Backend has no DELETE on reports; mark as REJECTED instead.
            resp = client.patch(_p(f"/reports/{r['id']}"), headers=h,
                                json={"status": "REJECTED"})
            if resp.status_code in (200, 204):
                n += 1
    return n


# ── Main ────────────────────────────────────────────────────────────────────
log = logging.getLogger("global-cbrn")


def main() -> None:
    default_backend = (
        os.environ.get("ARROW_BACKEND_URL")
        or sim_utils.load_saved_backend()
        or "http://localhost:6001"
    )
    parser = argparse.ArgumentParser(
        description="Operation REGNUM IGNIS — global CBRN exchange simulator (NATO / RU / CN)")
    parser.add_argument("--backend", default=default_backend,
                        help=f"Backend base URL (defaults to last-used: {default_backend}). "
                             "Supports a path prefix, e.g. http://78.21.255.210:6200/api")
    parser.add_argument("--admin",    default="benoit",   help="ADMIN callsign")
    parser.add_argument("--password", default="ranger14", help="ADMIN password")
    parser.add_argument("--seed",     type=int, default=None,
                        help="Deterministic RNG seed (default: random — each run differs)")
    parser.add_argument("--reset",    action="store_true",
                        help="Mark all existing CBRN_* reports as REJECTED before submitting new ones")
    parser.add_argument("--mission-name", default="Operation Regnum Ignis",
                        help="Mission name to create or adopt (default: Operation Regnum Ignis)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    global _path_prefix, MISSION_ID
    rng = random.Random(args.seed)

    origin, _path_prefix = sim_utils.split_base(args.backend)
    log.info("OPERATION REGNUM IGNIS — global CBRN exchange (NATO / RU / CN)")
    log.info("backend=%s admin=%s", args.backend, args.admin)

    with httpx.Client(base_url=origin, timeout=20.0) as client:
        token = login(client, args.admin, args.password)
        sim_utils.save_backend(args.backend)
        MISSION_ID = sim_utils.create_mission_sync(
            client, args.backend, token, args.mission_name,
            map_center_lat=20.0, map_center_lng=10.0, map_zoom=3)

        if args.reset:
            n = reset_existing_cbrn(client, token)
            log.info("Reset: marked %d existing CBRN report(s) as REJECTED.", n)

        scenario = build_scenario(rng)
        log.info("Plan: %d CBRN strikes over the last 12 hours.", len(scenario))

        ok, total = 0, 0
        per_attacker: dict[str, int] = {"NATO": 0, "RU": 0, "CN": 0}
        per_cat:      dict[str, int] = {"C": 0, "B": 0, "R": 0, "N": 0}
        now = datetime.now(UTC)

        # Submit oldest first so the WS stream tells a chronological story.
        for s in sorted(scenario, key=lambda x: -x.minutes_ago):
            total += 1
            if post_strike(client, token, s, now):
                ok += 1
                per_attacker[s.attacker] += 1
                per_cat[s.category] += 1
                marker = {"C": "☣", "B": "☣", "R": "☢", "N": "☢"}[s.category]
                log.info("  %s  %-5s  %s  on  %-22s  (%s, T-%dm)",
                         marker, s.attacker, s.category, s.target, s.agent, s.minutes_ago)

        log.info("Submitted %d/%d strikes.", ok, total)
        log.info("  Per attacker: NATO=%d  RU=%d  CN=%d", *per_attacker.values())
        log.info("  Per category: C=%d  B=%d  R=%d  N=%d", *per_cat.values())
        log.info("Done. Open the Desktop / Android CBRN tab to watch the hazard zones.")


if __name__ == "__main__":
    main()
