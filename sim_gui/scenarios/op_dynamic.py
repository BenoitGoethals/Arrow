"""DYNAMIC scenario — full battalion ops with INSERT → ATTACK → DEFEND → EXTRACT.

`inject()` builds a battlefield rich enough to drive a live demo:

* Every 3 PARA / SOR operator with a valid token is pushed to a starting GPS
  position around the insertion LZ via `POST /tracking/position` (per-operator
  token, not the admin's — see `_seed_positions`).
* 30+ enemy units laid out across the AO in role clusters: mech infantry,
  ATGM, mortar, recon vehicles, snipers, MANPADS / AAA, reserve company,
  armour platoon, outposts and a BN TAC HQ.
* Full control graphics: LZ INSERT, DZ REINFORCE, PZ TALON, OBJ DRAGON,
  defence box, AO boundary, FLOT, three phase lines (LOD / OBJ / DEFEND) and
  an axis of advance.
* Friendly POIs: CP RAVEN, BAS DAGGER, CCP STORM, ORP THUNDER.
* One CAS asset (`GHOSTRIDER-1`, F-16C with 2× GBU-12 and GAU-8) is
  pre-registered via `POST /cas/assets`.

`start_runtime()` drives a four-phase clock that loops indefinitely until the
Stop button fires the `threading.Event`:

* **INSERT  (~ 90 s)** — battalion converges from LZ INSERT toward PL LOD.
* **ATTACK  (~150 s)** — drive to OBJ DRAGON. Heavy TIC / FM / CAS / drone.
* **DEFEND  (~150 s)** — hold defence box. FM and drones dominate.
* **EXTRACT (~ 90 s)** — withdraw to PZ TALON.

At every phase boundary every operator's GPS position is bulk-updated to a
fresh cluster around the phase anchor. During each phase a subset is jittered
every few seconds for liveness so the map keeps moving.
"""

from __future__ import annotations

import random
import threading
import time
from typing import TYPE_CHECKING

from sim_utils import mgrs

from sim_gui.hierarchy_seeder import HierarchyState
from sim_gui.scenarios.base import (
    InjectResult,
    LogCallback,
    ScenarioMeta,
    post_drone_spot,
    post_fire_mission,
    post_logrep,
    post_medevac,
    post_overlay,
    post_salute,
    post_supply_point,
    post_tic,
    set_ops_status,
)
from sim_gui.scenarios.geo import (
    SIDC,
    atk_axis,
    boundary,
    def_area,
    dz,
    enemy,
    flot,
    lz,
    obj_area,
    objective,
    offset_m,
    phase_line,
    poi,
    pz,
)

if TYPE_CHECKING:
    from sim_gui.backend_client import AdminSession

META = ScenarioMeta(
    id="dynamic",
    name="DYNAMIC BN OPERATIONS",
    mission_type="Insert · Attack · Defend · Extract",
    real_world="3 PARA / SOR — phase-driven full-battalion ops",
    aor_center=(50.4669, 4.8674),
    map_zoom=13,
    summary=(
        "Full battalion on the map. Four-phase loop: insert at LZ INSERT, "
        "press to OBJ DRAGON, hold the defence box, extract via PZ TALON. "
        "Continuous TIC alerts, fire missions, drone spots and CAS requests."
    ),
)

VEHICLE_FLAVOR = "airborne"


# ── Phase geometry (offsets from META.aor_center, north/east metres) ─────────

LZ_OFFSET = (-2500, -2500)  # insertion LZ (NW corner)
DZ_OFFSET = (-2200, -2200)
ORP_OFFSET = (-1800, -1800)
LD_OFFSET = (-1000, -1500)  # line of departure target
OBJ_OFFSET = (0, 400)  # objective centre
DEF_OFFSET = (200, 600)
PZ_OFFSET = (2400, 2400)  # PZ TALON (SE corner)
BAS_OFFSET = (-2800, -2400)
CCP_OFFSET = (-2700, -2300)
CP_OFFSET = (-2900, -2500)


PHASES = ["INSERT", "ATTACK", "DEFEND", "EXTRACT"]
PHASE_DURATION = {
    "INSERT": 90.0,
    "ATTACK": 150.0,
    "DEFEND": 150.0,
    "EXTRACT": 90.0,
}
PHASE_ANCHOR = {
    "INSERT": LD_OFFSET,
    "ATTACK": OBJ_OFFSET,
    "DEFEND": DEF_OFFSET,
    "EXTRACT": PZ_OFFSET,
}
PHASE_EVENT_RATES = {
    # (tic, drone, salute, fm, cas, logrep, casualty)
    "INSERT": (
        (180, 300),
        (40, 90),
        (40, 80),
        (180, 360),
        (360, 720),
        (180, 300),
        (480, 900),
    ),
    "ATTACK": (
        (30, 70),
        (25, 60),
        (25, 55),
        (35, 90),
        (60, 180),
        (180, 360),
        (60, 150),
    ),
    "DEFEND": (
        (50, 120),
        (25, 60),
        (40, 90),
        (40, 90),
        (180, 360),
        (120, 240),
        (120, 300),
    ),
    "EXTRACT": (
        (70, 150),
        (40, 90),
        (45, 90),
        (120, 300),
        (300, 600),
        (180, 360),
        (180, 480),
    ),
}


# Supply point geometry — clustered around BAS DAGGER for a believable BCT trains.
SUPPLY_POINTS = [
    ("SP-I FOOD", "CLASS_I", (-2750, -2350), "Rations & water — Class I"),
    ("SP-III FUEL", "CLASS_III", (-2750, -2250), "Fuel point — Class III"),
    ("SP-V AMMO MAIN", "CLASS_V", (-2700, -2150), "Main ammo dump — Class V"),
    ("SP-V AMMO FWD", "CLASS_V", (-1850, -1750), "Forward ammo at ORP — Class V"),
    ("SP-VIII MED", "CLASS_VIII", (-2800, -2400), "Medical supplies — Class VIII"),
    ("SP-IX REPAIR", "CLASS_IX", (-2700, -2500), "Repair parts — Class IX"),
]


# ── helpers ──────────────────────────────────────────────────────────────────


def _operators_with_tokens(state: HierarchyState):
    return [op for op in state.operators if op.token]


def _seed_positions(
    session: AdminSession,
    state: HierarchyState,
    phase_offset: tuple[float, float],
    spread_m: float = 80.0,
) -> int:
    """Push every operator with a token to a fresh cluster around the anchor.

    Uses each operator's own bearer token (so `POST /tracking/position` writes
    to *their* row, not the admin's), bypassing `AdminSession`'s admin-token
    override by reaching for the underlying `Api` directly.
    """
    cx, cy = META.aor_center
    base = offset_m(cx, cy, *phase_offset)
    teams = list(state.teams.values())
    pushed = 0
    for ti, team in enumerate(teams):
        # Spread teams across an irregular grid centred on the anchor.
        tx = (ti % 7 - 3) * spread_m + random.uniform(-12, 12)
        ty = (ti // 7) * spread_m + random.uniform(-12, 12)
        team_center = offset_m(*base, tx, ty)
        for oi, op in enumerate(team.operators):
            if not op.token:
                continue
            ox = (oi % 4) * 9.0 + random.uniform(-3, 3)
            oy = (oi // 4) * 9.0 + random.uniform(-3, 3)
            lat, lon = offset_m(*team_center, ox, oy)
            try:
                session.api.post(
                    "/tracking/position",
                    op.token,
                    {"latitude": lat, "longitude": lon},
                )
                pushed += 1
            except Exception:
                pass
    return pushed


def _jitter_subset(
    session: AdminSession,
    state: HierarchyState,
    phase_offset: tuple[float, float],
    subset_size: int = 10,
) -> None:
    """Move a random subset of operators by a small step around the phase anchor."""
    cx, cy = META.aor_center
    base = offset_m(cx, cy, *phase_offset)
    candidates = _operators_with_tokens(state)
    if not candidates:
        return
    for op in random.sample(candidates, min(subset_size, len(candidates))):
        lat, lon = offset_m(*base, random.uniform(-280, 280), random.uniform(-280, 280))
        try:
            session.api.post(
                "/tracking/position",
                op.token,
                {"latitude": lat, "longitude": lon},
            )
        except Exception:
            pass


# ── inject ──────────────────────────────────────────────────────────────────


def inject(api: AdminSession, token: str, state: HierarchyState) -> InjectResult:
    result = InjectResult()
    cx, cy = META.aor_center
    items: list[dict] = []

    # ── Friendly POIs and zones
    lz_pt = offset_m(cx, cy, *LZ_OFFSET)
    dz_pt = offset_m(cx, cy, *DZ_OFFSET)
    pz_pt = offset_m(cx, cy, *PZ_OFFSET)
    items.append(lz(*lz_pt, "INSERT"))
    items.append(dz(*dz_pt, "REINFORCE"))
    items.append(pz(*pz_pt, "TALON"))
    items.append(poi(*offset_m(cx, cy, *CP_OFFSET), "CP RAVEN", SIDC["CP"]))
    items.append(poi(*offset_m(cx, cy, *BAS_OFFSET), "BAS DAGGER", SIDC["BAS"]))
    items.append(poi(*offset_m(cx, cy, *CCP_OFFSET), "CCP STORM", SIDC["CCP"]))
    items.append(poi(*offset_m(cx, cy, *ORP_OFFSET), "ORP THUNDER", SIDC["ORP"]))

    # ── Objectives & defence
    obj_pt = offset_m(cx, cy, *OBJ_OFFSET)
    items.append(objective(*obj_pt, "DRAGON", radius_m=350.0))
    items.append(obj_area(*obj_pt, "OBJ DRAGON", radius_m=250.0))
    items.append(def_area(*offset_m(cx, cy, *DEF_OFFSET), "DEF BP-1"))

    # ── Control measures: axis, FLOT, three PLs, AO boundary
    items.append(atk_axis(*offset_m(cx, cy, -800, -800), "AXIS WOLF", rotation_deg=45))
    items.append(
        flot(
            [offset_m(cx, cy, -1500, -2000), offset_m(cx, cy, -1500, 2000)],
            "FLOT BLUE",
        )
    )
    items.append(
        phase_line(
            [offset_m(cx, cy, -1000, -2000), offset_m(cx, cy, -1000, 2000)],
            "PL LOD",
        )
    )
    items.append(
        phase_line(
            [offset_m(cx, cy, 500, -2000), offset_m(cx, cy, 500, 2000)],
            "PL OBJECTIVE",
        )
    )
    items.append(
        phase_line(
            [offset_m(cx, cy, 1500, -2000), offset_m(cx, cy, 1500, 2000)],
            "PL DEFEND",
        )
    )
    items.append(
        boundary(
            [
                offset_m(cx, cy, 3000, -3000),
                offset_m(cx, cy, 3000, 3000),
                offset_m(cx, cy, -3000, 3000),
                offset_m(cx, cy, -3000, -3000),
                offset_m(cx, cy, 3000, -3000),
            ],
            "BDY AO DRAGON",
        )
    )

    # ── Enemy laydown — clusters across the AO
    enemy_clusters: list[tuple[tuple[float, float], int, str, str]] = [
        (offset_m(cx, cy, 400, 300), 4, SIDC["ENEMY_MECH"], "Mech inf"),
        (offset_m(cx, cy, -300, 500), 3, SIDC["ENEMY_INF"], "ATGM tm"),
        (offset_m(cx, cy, 600, -200), 2, SIDC["ENEMY_MORTAR"], "Mortar pit"),
        (offset_m(cx, cy, -500, -400), 3, SIDC["ENEMY_TECH"], "Recon BTR"),
        (offset_m(cx, cy, 0, 700), 2, SIDC["ENEMY_SNIPER"], "Sniper tm"),
        (offset_m(cx, cy, 250, -600), 2, SIDC["ENEMY_ADA"], "SA-7 ADA"),
        (offset_m(cx, cy, 800, 800), 4, SIDC["ENEMY_INF"], "Reserve coy"),
        (offset_m(cx, cy, 1200, -1200), 3, SIDC["ENEMY_ARMOR"], "T-72 plt"),
        (offset_m(cx, cy, -1100, 1200), 3, SIDC["ENEMY_INF"], "Outpost"),
        (offset_m(cx, cy, 1500, 200), 2, SIDC["ENEMY_HQ"], "Bn TAC"),
        (offset_m(cx, cy, -1500, -800), 2, SIDC["ENEMY_INF"], "Flank screen"),
    ]
    for (a_lat, a_lon), count, sidc, label in enemy_clusters:
        for i in range(count):
            jlat, jlon = offset_m(
                a_lat, a_lon, random.uniform(-150, 150), random.uniform(-150, 150)
            )
            items.append(enemy(jlat, jlon, f"{label} #{i + 1}", sidc))

    created = post_overlay(api, token, items, result)
    enemy_records = [r for r in created if r.get("type") == "ENEMY"]

    # ── Register a CAS asset for the scenario.
    try:
        api.post(
            "/cas/assets",
            token,
            {
                "callsign": "GHOSTRIDER-1",
                "aircraft_type": "F-16C",
                "ordnance": "2x GBU-12 LGB, GAU-8",
                "frequency": "VHF 250.100",
                "status": "AVAILABLE",
                "notes": "On-station for dynamic ops scenario",
            },
        )
        result.extra["cas_assets"] = 1
    except Exception:
        pass

    # ── Supply points (per class) clustered around BAS DAGGER.
    for name, point_type, (n_off, e_off), notes in SUPPLY_POINTS:
        lat, lon = offset_m(cx, cy, n_off, e_off)
        post_supply_point(
            api,
            token,
            {
                "name": name,
                "point_type": point_type,
                "lat": lat,
                "lng": lon,
                "notes": notes,
            },
            result,
        )

    # ── Push every operator onto the map at the insertion LZ.
    placed = _seed_positions(api, state, LZ_OFFSET, spread_m=70.0)
    result.extra["friendlies_placed"] = placed

    # Stash for runtime.
    inject._enemy_records = enemy_records  # type: ignore[attr-defined]
    inject._ao_center = (cx, cy)  # type: ignore[attr-defined]
    return result


# ── runtime loop ────────────────────────────────────────────────────────────


def start_runtime(
    api: AdminSession,
    token: str,
    state: HierarchyState,
    stop_event: threading.Event,
    log_cb: LogCallback,
) -> None:
    enemies: list[dict] = getattr(inject, "_enemy_records", [])
    cx, cy = getattr(inject, "_ao_center", META.aor_center)

    activities = ["DIG-IN", "PATROL", "RECON", "RESUPPLY", "WITHDRAW", "RAID", "AMBUSH"]
    drone_types = ["QUAD", "FIXED_WING", "VTOL"]
    behaviors = ["LOITER", "TRANSIT", "HOSTILE", "RECON"]

    phase_idx = 0
    phase_start = time.monotonic()
    casualties_taken: set[int] = set()

    next_event = {
        "tic": 0.0,
        "drone": 0.0,
        "salute": 0.0,
        "fm": 0.0,
        "cas": 0.0,
        "logrep": time.monotonic() + 60.0,
        "casualty": time.monotonic() + 90.0,
        "jitter": 0.0,
        "move": time.monotonic() + 6.0,  # initial small delay
    }

    def _transition(new_idx: int) -> None:
        phase_name = PHASES[new_idx]
        log_cb(f"━ phase → {phase_name}")
        moved = _seed_positions(api, state, PHASE_ANCHOR[phase_name], spread_m=80.0)
        log_cb(f"  re-positioned {moved} operator(s)")

    log_cb(f"phase clock started — {PHASES[0]} for {PHASE_DURATION[PHASES[0]]:.0f}s")

    while not stop_event.is_set():
        now = time.monotonic()
        phase = PHASES[phase_idx]
        (
            tic_rate,
            drone_rate,
            salute_rate,
            fm_rate,
            cas_rate,
            logrep_rate,
            casualty_rate,
        ) = PHASE_EVENT_RATES[phase]

        # ── Phase clock
        if now - phase_start >= PHASE_DURATION[phase]:
            phase_idx = (phase_idx + 1) % len(PHASES)
            phase_start = now
            _transition(phase_idx)
            continue

        # ── Enemy jitter
        if enemies and now >= next_event["jitter"]:
            target = random.choice(enemies)
            new_lat, new_lon = offset_m(
                float(target["latitude"]),
                float(target["longitude"]),
                random.uniform(-150, 150),
                random.uniform(-150, 150),
            )
            try:
                api.patch(
                    f"/tactical-objects/{target['id']}",
                    token,
                    {"latitude": new_lat, "longitude": new_lon},
                )
                target["latitude"] = new_lat
                target["longitude"] = new_lon
            except Exception:
                pass
            next_event["jitter"] = now + random.uniform(5, 12)

        # ── Operator drift (a subset every few seconds, around the phase anchor)
        if now >= next_event["move"]:
            _jitter_subset(api, state, PHASE_ANCHOR[phase], subset_size=8)
            next_event["move"] = now + 6.0

        # ── TIC
        if now >= next_event["tic"]:
            lat, lon = offset_m(
                cx, cy, random.uniform(-1500, 1500), random.uniform(-1500, 1500)
            )
            post_tic(api, token, lat, lon)
            log_cb(f"[{phase}] TIC @ {mgrs(lat, lon)}")
            next_event["tic"] = now + random.uniform(*tic_rate)

        # ── Drone spot
        if now >= next_event["drone"]:
            lat, lon = offset_m(
                cx, cy, random.uniform(-2200, 2200), random.uniform(-2200, 2200)
            )
            post_drone_spot(
                api,
                token,
                {
                    "latitude": lat,
                    "longitude": lon,
                    "drone_type": random.choice(drone_types),
                    "altitude_m": random.uniform(80, 600),
                    "direction_deg": random.uniform(0, 360),
                    "speed_kts": random.uniform(15, 80),
                    "behavior": random.choice(behaviors),
                    "notes": f"phase={phase}",
                },
            )
            log_cb(f"[{phase}] DRONE @ {mgrs(lat, lon)}")
            next_event["drone"] = now + random.uniform(*drone_rate)

        # ── SALUTE / SPOT
        if now >= next_event["salute"]:
            lat, lon = offset_m(
                cx, cy, random.uniform(-1500, 1500), random.uniform(-1500, 1500)
            )
            post_salute(
                api,
                token,
                {
                    "size": random.choice(["FIRE TEAM", "SQUAD", "PLATOON", "COMPANY"]),
                    "activity": random.choice(activities),
                    "location": mgrs(lat, lon),
                    "unit": random.choice(["UNK", "Rgr coy", "Mech inf bn", "SF mtn"]),
                    "time": "NOW",
                    "equipment": random.choice(
                        ["small arms", "BTR-80", "T-72", "DShK", "RPG-7", "ATGM"]
                    ),
                },
            )
            log_cb(f"[{phase}] SPOT @ {mgrs(lat, lon)}")
            next_event["salute"] = now + random.uniform(*salute_rate)

        # ── Fire mission
        if enemies and now >= next_event["fm"]:
            tgt = random.choice(enemies)
            try:
                post_fire_mission(
                    api,
                    token,
                    {
                        "latitude": float(tgt["latitude"]),
                        "longitude": float(tgt["longitude"]),
                        "direction": random.uniform(0, 360),
                        "mission_type": random.choice(
                            ["ADJUST_FIRE", "FIRE_FOR_EFFECT", "SUPPRESSION"]
                        ),
                        "ammunition": random.choice(["HE", "ILLUM", "SMOKE"]),
                        "quantity": random.randint(2, 12),
                        "description": (
                            f"{phase} — TGT {str(tgt.get('notes', ''))[:40]}"
                        ),
                    },
                )
                log_cb(f"[{phase}] FM on {str(tgt.get('notes', ''))[:30]}")
            except Exception:
                pass
            next_event["fm"] = now + random.uniform(*fm_rate)

        # ── CAS request (9-liner)
        if enemies and now >= next_event["cas"]:
            tgt = random.choice(enemies)
            lat, lon = float(tgt["latitude"]), float(tgt["longitude"])
            try:
                api.post(
                    "/cas/requests",
                    token,
                    {
                        "line_1": "GHOSTRIDER-1",
                        "line_2": "INITIAL",
                        "line_3": "RAVEN-6",
                        "line_4": f"{lat:.5f}, {lon:.5f}",
                        "line_5": mgrs(lat, lon),
                        "line_5_mgrs": mgrs(lat, lon),
                        "line_5_lat": lat,
                        "line_5_lon": lon,
                        "line_6": str(tgt.get("notes", "hostile"))[:80],
                        "line_7": "RED SMOKE",
                        "line_8": "FRIENDLIES 600m W",
                        "line_9": "EGRESS EAST",
                        "tic": phase == "ATTACK",
                    },
                )
                log_cb(f"[{phase}] CAS req → {str(tgt.get('notes', ''))[:30]}")
            except Exception:
                pass
            next_event["cas"] = now + random.uniform(*cas_rate)

        # ── LOGREP — periodic per-company logistics report
        if now >= next_event["logrep"]:
            company = random.choice(
                ["ECHO CIE", "FOXTROT CIE", "GOLF CIE", "HOTEL CIE", "BHQ"]
            )
            post_logrep(
                api,
                token,
                {
                    "section_a": {
                        "unit": company,
                        "report_dtg": "NOW",
                        "period": "06H",
                        "phase": phase,
                    },
                    "section_b": {
                        "personnel": {
                            "assigned": 30,
                            "present": 30 - len(casualties_taken),
                            "wia": len(casualties_taken),
                            "kia": 0,
                            "mia": 0,
                        }
                    },
                    "section_c": {
                        "supplies": {
                            "class_I_food_pct": random.randint(60, 95),
                            "class_III_fuel_pct": random.randint(40, 90),
                            "class_V_ammo_pct": random.randint(35, 90),
                            "class_VIII_med_pct": random.randint(50, 95),
                            "water_pct": random.randint(55, 95),
                        }
                    },
                    "section_d": {
                        "equipment_status": random.choice(
                            ["GREEN", "AMBER — 1 vehicle DEAD", "AMBER"]
                        )
                    },
                    "section_e": {
                        "maintenance": random.choice(
                            [
                                "nominal",
                                "M-ATV awaiting recovery",
                                "comms link degraded",
                            ]
                        )
                    },
                    "section_f": {
                        "medical": (
                            f"{len(casualties_taken)} WIA evac'd via MEDEVAC"
                            if casualties_taken
                            else "no casualties"
                        )
                    },
                    "section_g": {
                        "requests": random.sample(
                            [
                                "resupply Class V",
                                "replacement RTO",
                                "Class III topoff",
                                "Class VIII medical",
                                "additional smoke",
                                "BREACHER kit",
                            ],
                            k=2,
                        )
                    },
                },
            )
            log_cb(f"[{phase}] LOGREP — {company}")
            next_event["logrep"] = now + random.uniform(*logrep_rate)

        # ── Casualty + auto-MEDEVAC during contact phases
        if (
            phase in ("ATTACK", "DEFEND")
            and now >= next_event["casualty"]
            and state.operators
        ):
            candidates = [
                op
                for op in state.operators
                if op.token and op.op_id and op.op_id not in casualties_taken
            ]
            if candidates:
                hit = random.choice(candidates)
                outcome = random.choices(
                    ["INOPS", "INOPS", "INOPS", "KIA", "MIA"], k=1
                )[0]
                set_ops_status(api, token, hit.op_id, outcome)
                casualties_taken.add(hit.op_id)
                # Casualty lat/lon: use current AO anchor with jitter
                clat, clon = offset_m(
                    cx,
                    cy,
                    random.uniform(-400, 400),
                    random.uniform(-400, 400),
                )
                log_cb(f"[{phase}] CASUALTY {hit.callsign} → {outcome}")
                # Fire MEDEVAC 9-liner only for survivable casualties.
                if outcome == "INOPS":
                    post_medevac(
                        api,
                        token,
                        {
                            "line_1": f"PICKUP: {mgrs(clat, clon)}",
                            "line_2": "FREQ: VHF 250.100  CS: DUSTOFF-1",
                            "line_3": "A — URGENT  · 1 PATIENT",
                            "line_4": "B — SPECIAL EQUIPMENT: tourniquet kit",
                            "line_5": "L — 1 LITTER, 0 AMBULATORY",
                            "line_6": (
                                "N — NO ENEMY AT PZ"
                                if phase == "DEFEND"
                                else "P — POSSIBLE ENEMY AT PZ"
                            ),
                            "line_7": "C — SMOKE, RED",
                            "line_8": "A — A US/COALITION MILITARY",
                            "line_9": "OPEN FIELD, NO NBC",
                            "patient_callsign": hit.callsign,
                            "patient_status": outcome,
                            "latitude": clat,
                            "longitude": clon,
                        },
                    )
                    log_cb(f"[{phase}] MEDEVAC requested → {hit.callsign}")
            next_event["casualty"] = now + random.uniform(*casualty_rate)

        # Sleep in 100 ms ticks so Stop is responsive.
        for _ in range(10):
            if stop_event.is_set():
                break
            time.sleep(0.1)

    log_cb("phase clock stopped")
