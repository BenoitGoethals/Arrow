"""Operation IRON SHROUD — full-spectrum CBRN strike on the Russian Federation.

Covers all major geographic regions:
  European Russia · Urals · Western Siberia · Central Siberia
  Eastern Siberia · Russian Far East · Arctic · North Caucasus

Uses all six NATO CBRN message types (CBRN_1 … CBRN_6) with realistic
zone radii, wind vectors, agent assignments, and delivery systems.

Run:
  uv run python simulate_russia_cbrn.py
  uv run python simulate_russia_cbrn.py --backend https://78.21.255.210:6200/api
  uv run python simulate_russia_cbrn.py --reset
  uv run python simulate_russia_cbrn.py --seed 42
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import sim_utils

UTC = timezone.utc
log = logging.getLogger("russia-cbrn")

# ── Target database ──────────────────────────────────────────────────────────
# (name, lat, lon, region, priority)
# priority: 1=strategic, 2=operational, 3=tactical

TARGETS = [
    # ── European Russia ──────────────────────────────────────────────────────
    ("Moscow — Kremlin / STAVKA",           55.7558,  37.6173, "European Russia", 1),
    ("Moscow — Zhukovsky Air Base",         55.5983,  38.1167, "European Russia", 2),
    ("St. Petersburg — City Centre",        59.9311,  30.3609, "European Russia", 1),
    ("St. Petersburg — Baltic Fleet HQ",    59.8789,  29.6922, "European Russia", 1),
    ("Kaliningrad — Baltiysk Naval Base",   54.6500,  19.9000, "European Russia", 1),
    ("Murmansk — Northern Fleet HQ",        68.9585,  33.0827, "European Russia", 1),
    ("Murmansk — Severomorsk Naval",        69.0706,  33.4167, "European Russia", 1),
    ("Severodvinsk — Submarine Yard",       64.5635,  39.8302, "European Russia", 1),
    ("Pskov — 76th Guards Airborne",        57.8194,  28.3314, "European Russia", 2),
    ("Voronezh — Air Defence HQ",           51.6755,  39.2088, "European Russia", 2),
    ("Rostov-on-Don — Southern Mil Dist",   47.2357,  39.7015, "European Russia", 1),
    ("Volgograd — Logistics Hub",           48.7080,  44.5133, "European Russia", 2),
    ("Saratov — Engels-2 Nuclear Base",     51.5924,  46.0347, "European Russia", 1),
    ("Plesetsk Cosmodrome",                 62.9269,  40.5772, "European Russia", 1),
    ("Arkhangelsk — Northern Fleet Spt",    64.5401,  40.5433, "European Russia", 2),
    ("Novgorod — Logistics Node",           58.5241,  31.2746, "European Russia", 3),
    ("Tver — Air Defence",                  56.8587,  35.9176, "European Russia", 3),
    ("Bryansk — Logistics / Rail",          53.2434,  34.3656, "European Russia", 3),
    ("Kursk — Forward Supply",              51.7373,  36.1873, "European Russia", 2),
    ("Belgorod — Forward HQ",              50.5950,  36.5875, "European Russia", 2),
    ("Kozelsk — ICBM Silo Field",           54.0333,  35.8000, "European Russia", 1),

    # ── Urals ────────────────────────────────────────────────────────────────
    ("Yekaterinburg — Ural Mil Dist HQ",    56.8389,  60.6057, "Urals",           1),
    ("Chelyabinsk — Tank Factory",          55.1644,  61.4368, "Urals",           2),
    ("Perm — Rocket Engine Plant",          58.0105,  56.2502, "Urals",           2),
    ("Ufa — Fuel / Chemical Industry",      54.7388,  55.9721, "Urals",           2),
    ("Nizhny Tagil — Ural Tank Plant",      57.9106,  59.9811, "Urals",           1),
    ("Zlatoust — Arms Manufacture",         55.1688,  59.7016, "Urals",           3),
    ("Magnitogorsk — Steel Metallurgy",     53.4088,  58.9806, "Urals",           3),
    ("Tatishchevo — ICBM Silo Field",       51.7167,  45.5833, "Urals",           1),

    # ── Western Siberia ──────────────────────────────────────────────────────
    ("Novosibirsk — Scientific City",       55.0084,  82.9357, "W. Siberia",      1),
    ("Omsk — Tank & Armour Plant",          54.9885,  73.3242, "W. Siberia",      2),
    ("Tyumen — Oil / Energy HQ",            57.1527,  68.0002, "W. Siberia",      2),
    ("Surgut — Oil Infrastructure",         61.2540,  73.3961, "W. Siberia",      3),
    ("Barnaul — Mobile ICBM Garrison",      53.3498,  83.6720, "W. Siberia",      1),
    ("Novokuznetsk — Steel & Coal",         53.7557,  87.1099, "W. Siberia",      3),
    ("Tobolsk — Petrochemical",             58.1978,  68.2537, "W. Siberia",      3),
    ("Uzhur — ICBM Silo Field",             55.3167,  89.8167, "W. Siberia",      1),

    # ── Central Siberia ──────────────────────────────────────────────────────
    ("Krasnoyarsk — Atomic City",           56.0153,  92.8932, "C. Siberia",      1),
    ("Krasnoyarsk-26 — Plutonium",          56.1203,  93.0011, "C. Siberia",      1),
    ("Achinsk — Alumina Refinery",          56.2706,  90.4964, "C. Siberia",      3),
    ("Abakan — Air Base",                   53.7236,  91.4424, "C. Siberia",      3),
    ("Norilsk — Industrial Complex",        69.3535,  88.2024, "C. Siberia",      2),
    ("Tomsk — Nuclear Research",            56.4977,  84.9744, "C. Siberia",      2),

    # ── Eastern Siberia ──────────────────────────────────────────────────────
    ("Irkutsk — Air Army HQ",               52.2978, 104.2964, "E. Siberia",      1),
    ("Irkutsk ICBM — Silo Field",           52.8000, 103.5000, "E. Siberia",      1),
    ("Ulan-Ude — Helicopter Plant",         51.8270, 107.6060, "E. Siberia",      2),
    ("Chita — Mil District Fwd",            52.0346, 113.4988, "E. Siberia",      2),
    ("Bratsk — Hydroelectric Dam",          56.1513, 101.6167, "E. Siberia",      3),
    ("Angarsk — Petroleum Refinery",        52.5362, 103.8877, "E. Siberia",      3),

    # ── Russian Far East ─────────────────────────────────────────────────────
    ("Vladivostok — Pacific Fleet HQ",      43.1198, 131.8869, "Far East",        1),
    ("Fokino — Submarine Base",             42.9667, 132.4000, "Far East",        1),
    ("Khabarovsk — Far East Mil HQ",        48.4827, 135.0840, "Far East",        1),
    ("Komsomolsk — Sukhoi Jet Factory",     50.5513, 137.0083, "Far East",        1),
    ("Petropavlovsk — Submarine Base",      53.0452, 158.6572, "Far East",        1),
    ("Magadan — Strategic Port",            59.5680, 150.8068, "Far East",        2),
    ("Birobidzhan — EAO Capital",           48.8050, 132.9200, "Far East",        3),
    ("Sakhalin — Kholmsk Port",             47.0417, 142.0543, "Far East",        2),

    # ── Arctic ───────────────────────────────────────────────────────────────
    ("Tiksi — Arctic Military",             71.6406, 128.8699, "Arctic",          2),
    ("Anadyr — Chukotka Base",              64.7333, 177.5167, "Arctic",          2),
    ("Novaya Zemlya — Test Site",           73.5000,  54.8500, "Arctic",          1),
    ("Salekhard — Arctic Logistics",        66.5330,  66.6167, "Arctic",          3),
    ("Naryan-Mar — Arctic Port",            67.6389,  53.0072, "Arctic",          3),

    # ── North Caucasus ───────────────────────────────────────────────────────
    ("Krasnodar — Air Army HQ",             45.0328,  38.9769, "N. Caucasus",     1),
    ("Sevastopol — Black Sea Fleet",        44.6166,  33.5254, "N. Caucasus",     1),
    ("Maykop — 7th Mountain Army Base",     44.6107,  40.1069, "N. Caucasus",     2),
    ("Grozny — Forward Air Base",           43.3181,  45.6981, "N. Caucasus",     2),
    ("Mozdok — Strategic Air Base",         43.7336,  44.6533, "N. Caucasus",     2),
    ("Astrakhan — Caspian Flotilla",        46.3497,  48.0408, "N. Caucasus",     2),
    ("Kapustin Yar — Missile Test",         48.5667,  45.7833, "N. Caucasus",     1),
]

# ── CBRN agent data ──────────────────────────────────────────────────────────
AGENTS = {
    "C": [
        ("Novichok-A234",   "MISSILE",   "A-234 binary nerve agent, persistent"),
        ("VX nerve agent",  "MISSILE",   "Persistent G-series agent, oil-like"),
        ("Sarin (GB)",      "AIR",       "Volatile G-series, rapid dispersal"),
        ("Soman (GD)",      "AIR",       "G-series, ageing counteracts atropine"),
        ("Mustard (HD)",    "ARTILLERY", "Blister agent, persistent ground hazard"),
        ("Lewisite (L)",    "ARTILLERY", "Blister agent / arsenic compound"),
        ("Phosgene (CG)",   "AIR",       "Choking agent, heavier than air"),
        ("Hydrogen cyanide","MISSILE",   "Blood agent, rapid lethality"),
    ],
    "B": [
        ("Anthrax (B. anthracis)", "MISSILE", "Spore-forming — persistent soil contamination"),
        ("Plague (Y. pestis)",     "AIR",     "Pneumonic variant — person-to-person spread"),
        ("Tularemia (F. tular.)",  "AIR",     "Low dose lethal, aerosol effective"),
        ("Botulinum toxin",        "MISSILE", "Most toxic substance known, food/water"),
        ("Smallpox (V. major)",    "AIR",     "Eradicated — max panic potential"),
        ("Venezuelan EEE",         "AIR",     "Encephalitis — anti-personnel"),
        ("Brucellosis (B. meli.)", "AIR",     "Incapacitating, high morbidity"),
    ],
    "R": [
        ("Cs-137 dirty bomb",  "GROUND",    "Long half-life, persistent beta/gamma"),
        ("Co-60 dirty bomb",   "MISSILE",   "High gamma emitter, dense contamination"),
        ("Sr-90 dispersal",    "AIR",       "Bone-seeker, replaces calcium"),
        ("Am-241 aerosol",     "AIR",       "Alpha emitter, inhalation hazard"),
        ("Pu-239 dispersal",   "GROUND",    "Weapons-grade, extreme persistence"),
        ("I-131 cloud",        "AIR",       "Thyroid uptake, post-blast dispersal"),
    ],
    "N": [
        ("Tactical nuclear (15 kT)",   "MISSILE", "Sub-strategic warhead"),
        ("Tactical nuclear (50 kT)",   "MISSILE", "Theatre warhead — W76 equivalent"),
        ("Strategic warhead (300 kT)", "MISSILE", "SLBM/ICBM delivery"),
        ("Strategic warhead (800 kT)", "MISSILE", "Heavy ICBM — area denial"),
        ("Enhanced radiation (1 kT)",  "MISSILE", "Neutron bomb — reduced blast"),
        ("Airburst (100 kT)",          "MISSILE", "Maximum EMP / thermal radius"),
    ],
}

# CBRN type → category weights (C/B/R/N)
TYPE_WEIGHTS = {
    "CBRN_1": {"C": 4, "B": 1, "R": 3, "N": 2},   # Initial observation
    "CBRN_2": {"C": 3, "B": 2, "R": 3, "N": 2},   # Downwind estimate
    "CBRN_3": {"C": 1, "B": 0, "R": 6, "N": 3},   # Radiological warning
    "CBRN_4": {"C": 4, "B": 2, "R": 3, "N": 4},   # Recon survey (full)
    "CBRN_5": {"C": 5, "B": 3, "R": 2, "N": 2},   # Actual contamination
    "CBRN_6": {"C": 4, "B": 4, "R": 2, "N": 1},   # Detailed unit report
}

# Zone radii (metres) per category
ZONE_INNER = {
    "C": (800,   4_000),
    "B": (2_000, 8_000),
    "R": (1_500, 6_000),
    "N": (8_000, 60_000),
}
ZONE_DOWNWIND = {
    "C": (8_000,  40_000),
    "B": (30_000, 120_000),
    "R": (15_000, 80_000),
    "N": (60_000, 350_000),
}
ZONE_HALF_ANGLE = {
    "C": (20, 45),
    "B": (25, 60),
    "R": (20, 50),
    "N": (15, 35),
}

DELIVERIES = ["MISSILE", "AIR", "ARTILLERY", "GROUND", "UNKNOWN"]


@dataclass
class Strike:
    target_name: str
    lat: float
    lon: float
    region: str
    priority: int
    cbrn_type: str           # CBRN_1 … CBRN_6
    category: str            # C / B / R / N
    agent: str
    delivery: str
    description: str
    wind_dir: float
    wind_kts: float
    zone_inner_m: float
    zone_downwind_m: float
    zone_half_angle: float
    yield_kt: float | None
    minutes_ago: int
    serial: str = ""


def build_scenario(rng: random.Random) -> list[Strike]:
    strikes: list[Strike] = []
    serial_counter: dict[str, int] = {}
    now_ref = 0

    def add(target_idx: int, cbrn_type: str, minutes_ago: int,
            force_cat: str | None = None) -> None:
        name, lat, lon, region, priority = TARGETS[target_idx]

        weights = TYPE_WEIGHTS[cbrn_type].copy()
        if force_cat:
            cat = force_cat
        else:
            cats   = [k for k, v in weights.items() if v > 0]
            ws     = [weights[k] for k in cats]
            cat    = rng.choices(cats, weights=ws)[0]

        agent_entry = rng.choice(AGENTS[cat])
        agent_name, _, agent_desc = agent_entry

        # Delivery — prefer what the agent suggests, but randomise
        pref_delivery = agent_entry[1]
        delivery = rng.choices(
            [pref_delivery, rng.choice(DELIVERIES)],
            weights=[4, 1]
        )[0]

        wind_dir  = round(rng.uniform(0, 359), 1)
        wind_kts  = round(rng.uniform(5, 25), 1)

        z1_lo, z1_hi = ZONE_INNER[cat]
        z2_lo, z2_hi = ZONE_DOWNWIND[cat]
        ha_lo, ha_hi = ZONE_HALF_ANGLE[cat]

        # Priority 1 targets get bigger zones
        scale = 1.0 + (2 - priority) * 0.4
        z1 = round(rng.uniform(z1_lo, z1_hi) * scale)
        z2 = round(rng.uniform(z2_lo, z2_hi) * scale)
        ha = round(rng.uniform(ha_lo, ha_hi), 1)

        yield_kt: float | None = None
        if cat == "N":
            if "800" in agent_name:
                yield_kt = round(rng.uniform(600, 900), 0)
            elif "300" in agent_name:
                yield_kt = round(rng.uniform(250, 350), 0)
            elif "100" in agent_name:
                yield_kt = round(rng.uniform(80, 120), 0)
            elif "50" in agent_name:
                yield_kt = round(rng.uniform(40, 60), 0)
            elif "15" in agent_name:
                yield_kt = round(rng.uniform(10, 20), 0)
            else:
                yield_kt = round(rng.uniform(0.5, 5), 1)

        key = f"{cbrn_type}-{cat}-{region[:3]}"
        serial_counter[key] = serial_counter.get(key, 0) + 1
        serial = f"ALPHA-{cbrn_type}-{cat}-{serial_counter[key]:03d}"

        desc = f"IRON SHROUD strike: {agent_name} on {name}"
        if yield_kt:
            desc += f" ({yield_kt:g} kT)"

        strikes.append(Strike(
            target_name    = name,
            lat            = lat,
            lon            = lon,
            region         = region,
            priority       = priority,
            cbrn_type      = cbrn_type,
            category       = cat,
            agent          = agent_name,
            delivery       = delivery,
            description    = desc,
            wind_dir       = wind_dir,
            wind_kts       = wind_kts,
            zone_inner_m   = z1,
            zone_downwind_m= z2,
            zone_half_angle= ha,
            yield_kt       = yield_kt,
            minutes_ago    = minutes_ago,
            serial         = serial,
        ))

    n = len(TARGETS)

    # ── Wave 1 (T-480..T-360): Strategic nuclear / radiological — capitals + ICBM fields ──
    log.info("Building Wave 1 — strategic nuclear decapitation strikes…")
    strategic = [i for i, t in enumerate(TARGETS) if t[4] == 1]   # priority-1 only
    for i, idx in enumerate(strategic):
        cat = "N" if i % 3 != 2 else "R"
        add(idx, "CBRN_1", 480 - i * 4, force_cat=cat)

    # ── Wave 2 (T-360..T-240): CBRN_3 radiological warning — nuclear facilities ──
    log.info("Building Wave 2 — radiological contamination warnings…")
    nuclear_sites = [
        i for i, t in enumerate(TARGETS)
        if any(kw in t[0] for kw in ["Nuclear", "Plutonium", "ICBM", "Cosmodrome",
                                      "Novaya", "Test", "Atomic", "Research"])
    ]
    for i, idx in enumerate(nuclear_sites):
        add(idx, "CBRN_3", 360 - i * 8, force_cat="R")

    # ── Wave 3 (T-240..T-120): CBRN_4 recon surveys — all regions ──
    log.info("Building Wave 3 — recon surveys across all regions…")
    for i, idx in enumerate(range(n)):
        add(idx, "CBRN_4", 240 - (i * 240 // n))

    # ── Wave 4 (T-180..T-90): CBRN_2 downwind estimates — chemical strikes ──
    log.info("Building Wave 4 — chemical downwind estimates…")
    mil_targets = [i for i, t in enumerate(TARGETS)
                   if any(kw in t[0] for kw in ["Fleet", "Air", "Army", "Mil", "Naval",
                                                  "Base", "HQ", "Garrison", "Airborne"])]
    for i, idx in enumerate(mil_targets):
        add(idx, "CBRN_2", 180 - i * 3, force_cat="C")

    # ── Wave 5 (T-90..T-30): CBRN_5 actual contamination — eastern + arctic ──
    log.info("Building Wave 5 — contamination reports — Far East & Arctic…")
    east_arctic = [i for i, t in enumerate(TARGETS)
                   if t[3] in ("Far East", "Arctic", "E. Siberia")]
    for i, idx in enumerate(east_arctic):
        add(idx, "CBRN_5", 90 - i * 2)

    # ── Wave 6 (T-60..T-0): CBRN_6 detailed unit reports — secondary hits ──
    log.info("Building Wave 6 — detailed unit reports — secondary strikes…")
    industrial = [i for i, t in enumerate(TARGETS)
                  if any(kw in t[0] for kw in ["Factory", "Plant", "Steel", "Refinery",
                                                 "Oil", "Fuel", "Chemical", "Coal",
                                                 "Metallurgy", "Alumina", "Petrochemical"])]
    for i, idx in enumerate(industrial):
        add(idx, "CBRN_6", 60 - i * 2)

    # ── Wave 7 (T-15..T-0): biological — final saturation ──
    log.info("Building Wave 7 — biological saturation — priority-1 cities…")
    cities = [i for i, t in enumerate(TARGETS)
              if t[4] == 1 and t[3] not in ("Arctic",)]
    for i, idx in enumerate(cities):
        add(idx, "CBRN_1", 15 - (i % 15), force_cat="B")

    # Sort oldest-first for chronological WS delivery
    strikes.sort(key=lambda s: -s.minutes_ago)
    return strikes


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def post_strike(api: sim_utils.Api, token: str, s: Strike, now: datetime) -> bool:
    dtg = (now - timedelta(minutes=s.minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload: dict = {
        "msg_type":             s.cbrn_type,
        "serial":               s.serial,
        "dtg":                  dtg,
        "target":               s.target_name,
        "region":               s.region,
        "agent_category":       s.category,
        "agent":                s.agent,
        "delivery":             s.delivery,
        "wind_direction":       s.wind_dir,
        "wind_speed_kts":       s.wind_kts,
        "wind_speed":           round(s.wind_kts * 1.852, 1),
        "latitude":             s.lat,
        "longitude":            s.lon,
        "zone_inner_m":         s.zone_inner_m,
        "zone_downwind_m":      s.zone_downwind_m,
        "zone_downwind_angle_deg": s.zone_half_angle,
        "description":          s.description,
        "operation":            "IRON SHROUD",
        "priority":             s.priority,
    }
    if s.yield_kt is not None:
        payload["yield_kt"] = s.yield_kt

    body = {"type": s.cbrn_type, "payload": payload}
    try:
        api.post("/reports", token, body)
        return True
    except Exception as exc:
        log.warning("POST /reports failed: %s", exc)
        return False


def reset_cbrn(api: sim_utils.Api, token: str) -> int:
    try:
        reports = api.get("/reports", token)
    except Exception:
        return 0
    n = 0
    for r in reports:
        if r.get("type", "").startswith("CBRN"):
            try:
                api.patch(f"/reports/{r['id']}", token, {"status": "REJECTED"})
                n += 1
            except Exception:
                pass
    return n


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    default_backend = (
        os.environ.get("ARROW_BACKEND_URL")
        or sim_utils.load_saved_backend()
        or "http://localhost:6001"
    )
    parser = argparse.ArgumentParser(
        description="Operation IRON SHROUD — full-spectrum CBRN strike on Russia")
    parser.add_argument("--backend", default=default_backend,
                        help=f"Backend URL (default: {default_backend})")
    parser.add_argument("--admin",    default="benoit",   help="Admin callsign")
    parser.add_argument("--password", default="ranger14", help="Admin password")
    parser.add_argument("--seed",     type=int, default=None, help="RNG seed for reproducibility")
    parser.add_argument("--reset",    action="store_true",
                        help="Mark all existing CBRN reports as REJECTED before posting")
    parser.add_argument("--mission-name", default="Operation Iron Shroud",
                        help="Mission name to create/adopt")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    rng = random.Random(args.seed)

    log.info("═" * 62)
    log.info("  OPERATION IRON SHROUD — full-spectrum CBRN / Russia")
    log.info("  Targets: %d locations across 8 geographic regions", len(TARGETS))
    log.info("  Backend: %s", args.backend)
    log.info("═" * 62)

    api = sim_utils.Api(args.backend)
    token = api.login(args.admin, args.password)
    sim_utils.save_backend(args.backend)

    mid = api.create_mission(
        token, args.mission_name,
        description="Full-spectrum CBRN saturation of the Russian Federation.",
        map_center_lat=62.0, map_center_lng=90.0, map_zoom=4,
    )
    if mid:
        api.mission_id = mid

    if args.reset:
        n = reset_cbrn(api, token)
        log.info("Reset: marked %d existing CBRN report(s) as REJECTED.", n)

    scenario = build_scenario(rng)
    log.info("Scenario built: %d strikes total.", len(scenario))
    log.info("Submitting…\n")

    now = datetime.now(UTC)
    ok = 0
    by_type: dict[str, int] = {}
    by_cat:  dict[str, int] = {}
    by_region: dict[str, int] = {}

    ICON = {"C": "☣", "B": "🦠", "R": "☢", "N": "💥"}

    for s in scenario:
        if post_strike(api, token, s, now):
            ok += 1
            by_type[s.cbrn_type]  = by_type.get(s.cbrn_type, 0) + 1
            by_cat[s.category]    = by_cat.get(s.category, 0) + 1
            by_region[s.region]   = by_region.get(s.region, 0) + 1
            log.info("  %s %-8s %-6s  %-42s  [%s]",
                     ICON.get(s.category, "?"), s.cbrn_type, s.category,
                     s.target_name[:42], s.region)

    log.info("")
    log.info("═" * 62)
    log.info("  Submitted %d/%d strikes", ok, len(scenario))
    log.info("")
    log.info("  By CBRN type:")
    for t in ["CBRN_1", "CBRN_2", "CBRN_3", "CBRN_4", "CBRN_5", "CBRN_6"]:
        if by_type.get(t):
            log.info("    %-8s  %d", t, by_type[t])
    log.info("")
    log.info("  By agent category:")
    for cat, icon in ICON.items():
        if by_cat.get(cat):
            log.info("    %s %-2s  %d", icon, cat, by_cat[cat])
    log.info("")
    log.info("  By region:")
    for region in ["European Russia", "Urals", "W. Siberia", "C. Siberia",
                   "E. Siberia", "Far East", "Arctic", "N. Caucasus"]:
        if by_region.get(region):
            log.info("    %-20s  %d", region, by_region[region])
    log.info("═" * 62)
    log.info("  Open /cops/cbrn/ to see all %d hazard zones on the map.", ok)


if __name__ == "__main__":
    main()
