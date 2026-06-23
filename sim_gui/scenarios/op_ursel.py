"""Operation FLANDERS GATE — airborne seizure of Ursel airfield (EBUL).

Ursel Airfield (ICAO EBUL) is a 2400 m grass / asphalt strip in East Flanders,
Belgium, ~25 km west of Ghent. Originally built by the Luftwaffe in 1941
(Fliegerhorst Ursel), captured intact and operated by the RAF as B.67 Ursel
from September 1944. Today owned by Belgian Defence, used for emergency
diversions and SOF exercises. The runway 07/25 sits in open polderland with
the villages of Knesselare (south), Ursel (north-west), Maldegem (further
west) and Aalter (east) forming the natural threat axes.

This scenario walks the full doctrinal airborne seizure: Pathfinders mark the
DZs, the main body jumps in successive sticks, sub-units regroup at named
rally points, three rifle companies simultaneously assault three objectives
on the airfield (control tower, fuel farm, hangars), then the battalion
transitions to perimeter defence to receive follow-on lift.

Four phases, looped indefinitely until Stop is pressed:

* **JUMP    (~ 60 s)** — battalion descends onto DZ NORTH + DZ SOUTH.
* **REGROUP (~ 90 s)** — sticks converge on RV ALPHA / BRAVO; pathfinders
  link up; first SALUTE goes out.
* **ATTACK  (~180 s)** — ECHO seizes OBJ NEPTUNE (tower), FOXTROT OBJ HERMES
  (fuel), GOLF OBJ JANUS (hangars); heavy TIC / FM / CAS.
* **DEFENCE (~180 s)** — battalion sets perimeter; counter-attack from
  Knesselare QRF and Maldegem armoured reserve; HOTEL mortar plt fires
  preplanned targets; battalion holds for follow-on C-17 lift.
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
    line_obj,
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
    id="ursel_airfield",
    name="OPERATION FLANDERS GATE",
    mission_type="Airborne Airfield Seizure",
    real_world="Ursel Airfield (EBUL), East Flanders, BE — RAF B.67 (1944) successor field",
    aor_center=(51.1444, 3.5267),  # Ursel airfield (EBUL) reference point
    map_zoom=14,
    summary=(
        "3 PARA / SOR night airborne seizure of Ursel airfield. Pathfinders "
        "mark DZ NORTH and DZ SOUTH; main body jumps in three sticks; ECHO "
        "takes the tower, FOXTROT the fuel farm, GOLF the hangars; HOTEL holds "
        "the perimeter while we receive follow-on lift."
    ),
)

VEHICLE_FLAVOR = "airborne"


# ── Geometry: offsets in (north_m, east_m) from EBUL reference ──────────────

# Drop / rally / objective points
DZ_NORTH = (700, -300)  # 700 m N, 300 m W of field centre
DZ_SOUTH = (-700, 350)  # 700 m S of field centre, just S of runway
RV_ALPHA = (0, -1100)  # west runway threshold
RV_BRAVO = (300, 600)  # near tower
OBJ_NEPTUNE = (250, 50)  # control tower
OBJ_HERMES = (-150, 900)  # fuel farm (east apron)
OBJ_JANUS = (350, -500)  # hangars (west apron)
DEF_BP_NORTH = (900, 200)  # northern perimeter BP
DEF_BP_SOUTH = (-900, 200)  # southern perimeter BP
DEF_BP_EAST = (0, 1200)  # eastern BP (Aalter approach)
DEF_BP_WEST = (0, -1300)  # western BP (Maldegem approach)
PZ_TANGO = (-500, 500)  # PZ for hot extraction if compromised
BAS_OFFSET = (200, -650)  # near hangars
CCP_OFFSET = (180, -680)
CP_OFFSET = (260, 60)  # control tower itself
ORP_OFFSET = (-1500, -1500)  # rally before assault

# Phase plan
PHASES = ["JUMP", "REGROUP", "ATTACK", "DEFENCE"]
PHASE_DURATION = {
    "JUMP": 60.0,
    "REGROUP": 90.0,
    "ATTACK": 180.0,
    "DEFENCE": 180.0,
}
PHASE_ANCHOR = {
    # Where to teleport / cluster operators at phase boundary.
    "JUMP": DZ_NORTH,
    "REGROUP": RV_ALPHA,
    "ATTACK": OBJ_NEPTUNE,
    "DEFENCE": DEF_BP_EAST,
}
PHASE_EVENT_RATES = {
    # (tic, drone, salute, fm, cas, logrep, casualty)
    "JUMP": (
        (300, 600),
        (60, 120),
        (40, 70),
        (240, 480),
        (480, 900),
        (240, 360),
        (600, 900),
    ),
    "REGROUP": (
        (90, 180),
        (45, 90),
        (35, 60),
        (180, 360),
        (240, 480),
        (180, 360),
        (240, 480),
    ),
    "ATTACK": (
        (25, 60),
        (25, 60),
        (25, 50),
        (30, 80),
        (50, 150),
        (180, 300),
        (50, 120),
    ),
    "DEFENCE": (
        (40, 90),
        (25, 60),
        (35, 70),
        (35, 90),
        (150, 300),
        (120, 240),
        (90, 240),
    ),
}


SUPPLY_POINTS = [
    ("SP-I FOOD", "CLASS_I", (160, -700), "Rations & water at hangar 4"),
    ("SP-III FUEL", "CLASS_III", (-180, 920), "Captured fuel farm — OBJ HERMES"),
    ("SP-V AMMO MAIN", "CLASS_V", (200, -700), "Main ammo dump at hangar 5"),
    ("SP-V AMMO FWD", "CLASS_V", (300, 100), "Forward ammo at tower"),
    ("SP-VIII MED", "CLASS_VIII", (210, -640), "Medical supplies at BAS"),
    ("SP-IX REPAIR", "CLASS_IX", (240, -680), "Repair parts at hangar 6"),
]


# ── Custom 5-paragraph OPORD specific to FLANDERS GATE ─────────────────────


def build_opord(meta: ScenarioMeta) -> dict:
    return {
        "title": f"OPORD — {meta.name} (URSEL AIRFIELD SEIZURE)",
        "opord_number": "OPS-FLANDERS-001",
        "dtg": "192230ZJUN26",
        "time_zone": "ZULU",
        "classification": "SECRET // REL NATO // FOUO",
        "references": (
            "(a) Map: NGI Belgium 1:25,000 sheet 13/2 KNESSELARE\n"
            "(b) Airfield diagram: EBUL aerodrome chart, AIP Belgium\n"
            "(c) Historical: RAF B.67 Ursel operations log, Sep 1944 – Apr 1945\n"
            "(d) BN INTSUM 26-117 (Ursel garrison ORBAT)\n"
            "(e) BN WARNORD 16 dtd 180100ZJUN26\n"
            "(f) ROE Card: COMBINED-JOINT ROE-04 (BELGIUM AOR)\n"
            "(g) Special Instructions: Belgian Defence deconfliction matrix"
        ),
        "task_organization": (
            "3 PARA / SOR — TASK FORCE FLANDERS\n"
            "  BHQ — Battalion HQ, Signals, Aid Station, Log Plt, Recon Plt\n"
            "    Attached: PATHFINDER DET (3x teams of 4, HALO insert H-2:00)\n"
            "  ECHO CIE — Main effort, OBJ NEPTUNE (control tower)\n"
            "  FOXTROT CIE — OBJ HERMES (fuel farm)\n"
            "  GOLF CIE — OBJ JANUS (hangars)\n"
            "  HOTEL CIE (Support) — Sniper Plt, Mortar Plt (81 mm × 4),\n"
            "                       Pioneer Plt (breach/EOD), AT Plt (Spike)\n"
            "  Attached air: GHOSTRIDER-1 (F-16C AGM-65/GBU-12),\n"
            "               GHOSTRIDER-2 (F-16C as 30 min relief),\n"
            "               DUSTOFF-1 (NH-90 MEDEVAC, on-call from Koksijde)\n"
            "  Attached aviation lift: 5x C-130J / A400M (BAF 15 Wing)"
        ),
        "situation": {
            "enemy": (
                "Estimated enemy: reinforced Regional Defence Brigade (RDB) with:\n"
                "  • Airfield garrison — 2 reduced rifle coys (~120 pax) with "
                "23 mm AAA at hangar 6 and ATGM (Konkurs) on tower roof.\n"
                "  • Knesselare QRF — mech coy (4× BTR-80) at fire station, "
                "10 min reaction time.\n"
                "  • Maldegem reserve — armoured plt (3× T-72M) in revetments "
                "W of village, 25 min reaction time.\n"
                "  • Aalter screen — recon plt with snipers in the woods E of "
                "the field.\n"
                "  • Counter-airborne helo (Mi-24) on strip alert at "
                "Wevelgem, 12 min flight time."
            ),
            "friendly": (
                "3 PARA / SOR is main effort. SOR HQ approves all CAS / fires.\n"
                "Adjacent: 1 PARA holds Brugge corridor; SF AIRBORNE COY "
                "secures Maldegem road; SACEUR diplomatic cover authorising "
                "Belgian airspace use."
            ),
            "civilian": (
                "Knesselare town: 8,500 pop, deconfliction-listed; warning "
                "broadcast 30 min prior. Aalter: 20,000 pop. Civilians cleared "
                "from airfield perimeter under cover of NOTAM exercise notice."
            ),
            "weather": (
                "Night insertion, illumination 0.42 (waning crescent), BMNT "
                "04:42 UTC. Wind 250/14 kts, gusting 18 — within DZ limits "
                "(<= 18 kts surface). Cloud SCT 3000 ft. Drop altitude "
                "800 ft AGL."
            ),
            "terrain": (
                "OCOKA at EBUL:\n"
                "  Observation/Fields of fire — control tower (60 ft) "
                "dominates the entire field; OBJ NEPTUNE.\n"
                "  Cover/Concealment — limited on field; hangars and fuel "
                "berms provide cover.\n"
                "  Obstacles — perimeter fence (cyclone, 2.4 m), runway "
                "lighting trenches.\n"
                "  Key terrain — control tower, fuel farm, runway 07 threshold.\n"
                "  Avenues of approach — eastern road from Aalter (paved), "
                "southern from Knesselare, both restricted by polder ditches."
            ),
        },
        "mission": (
            "NLT H-Hour (220300ZJUN26) 3 PARA / SOR conducts a battalion-"
            "scale airborne seizure of Ursel Airfield (EBUL) IOT secure the "
            "runway intact, deny enemy use of the field for counter-air "
            "operations, and enable follow-on coalition lift within H+04:00."
        ),
        "execution": {
            "commanders_intent": (
                "PURPOSE: seize EBUL intact and hold it through the dawn "
                "window, enabling the coalition to land follow-on forces and "
                "establish a forward operating base 25 km W of Ghent.\n"
                "KEY TASKS: pathfinder DZ marking complete by H-30; battalion "
                "drop NLT H+5; rally points secured by H+20; control tower "
                "seized by H+60; fuel farm and hangars by H+90; perimeter "
                "defence established by H+120; runway certified runway-"
                "operational by H+180.\n"
                "END STATE: airfield secure, enemy garrison destroyed or "
                "withdrawn, counter-attack defeated W of PL DEFEND, runway "
                "clear and lit for follow-on C-17 lift, zero personnel left "
                "behind."
            ),
            "concept_of_operations": (
                "Four-phase scheme of manoeuvre:\n"
                "  Phase 1 JUMP (H-Hour, ~60 s) — Pathfinder DET marks DZ "
                "NORTH (700 m N of centreline) and DZ SOUTH (700 m S) with "
                "IR strobes. Five C-130J/A400M overfly NW-SE at 800 ft AGL "
                "delivering three sticks each. ECHO + 1/3 BHQ on DZ NORTH; "
                "FOXTROT + GOLF + 2/3 BHQ on DZ SOUTH; HOTEL splits.\n"
                "  Phase 2 REGROUP (H+5 to H+25) — sticks converge on RV "
                "ALPHA (runway threshold W) and RV BRAVO (E of tower). "
                "Sub-unit accountability; first SALUTE; CAS check-in.\n"
                "  Phase 3 ATTACK (H+25 to H+90) — three simultaneous "
                "objectives:\n"
                "    • ECHO seizes OBJ NEPTUNE (tower) along AXIS HAWK from "
                "RV ALPHA, supported by HOTEL sniper overwatch from PL "
                "OBJECTIVE.\n"
                "    • FOXTROT seizes OBJ HERMES (fuel farm) along AXIS "
                "EAGLE from RV BRAVO.\n"
                "    • GOLF seizes OBJ JANUS (hangars) along AXIS RAVEN from "
                "RV ALPHA / west apron.\n"
                "  Phase 4 DEFENCE (H+90 onward) — battalion establishes "
                "perimeter at BP NORTH/SOUTH/EAST/WEST; HOTEL mortars hold "
                "preplanned targets on Knesselare QRF axis; runway swept; "
                "follow-on lift inbound from coast at H+200."
            ),
            "tasks_to_subordinate_units": {
                "PATHFINDER DET": (
                    "H-2:00 HALO insert. Mark DZ NORTH + DZ SOUTH with IR "
                    "strobes (alpha pattern). Establish DZSO; clear DZ of "
                    "vehicles/livestock; report DZ STATUS GO to BN main."
                ),
                "ECHO CIE": (
                    "Main effort. Drop on DZ NORTH. Rally RV ALPHA. Seize "
                    "OBJ NEPTUNE (control tower) NLT H+60 along AXIS HAWK. "
                    "Establish BP NORTH thereafter. BPT relief in place of "
                    "FOXTROT on order."
                ),
                "FOXTROT CIE": (
                    "Drop on DZ SOUTH. Rally RV BRAVO. Seize OBJ HERMES "
                    "(fuel farm) NLT H+90 along AXIS EAGLE. Preserve fuel "
                    "stocks for follow-on. Establish BP EAST thereafter."
                ),
                "GOLF CIE": (
                    "Drop on DZ SOUTH. Rally RV ALPHA. Seize OBJ JANUS "
                    "(hangars) NLT H+90 along AXIS RAVEN. Clear and secure "
                    "hangars 1-6; recover serviceable airframes if present. "
                    "Establish BP WEST thereafter."
                ),
                "HOTEL CIE (Support)": (
                    "Sniper Plt: overwatch tower + fuel farm from PL "
                    "OBJECTIVE. Mortar Plt: 4 tubes vic SP-V FWD, fire "
                    "preplanned targets PT-101 (Knesselare crossroads) and "
                    "PT-102 (Maldegem armour). AT Plt: 2 Spike teams covering "
                    "BP EAST and BP SOUTH against BTR/T-72. Pioneer Plt: "
                    "breach perimeter fence, clear runway of obstacles."
                ),
                "BHQ": (
                    "C2 from CP TOWER (post-seizure of OBJ NEPTUNE). "
                    "BAS receives at hangar 4. Log Plt operates SP-I/III/V/"
                    "VIII/IX as listed. Signals plt establishes BN main and "
                    "JTAC link via CoT to coalition AOC."
                ),
            },
            "coordinating_instructions": [
                "H-Hour: 220300ZJUN26. Adjustable +/- 15 min based on weather.",
                "ROE: COMBINED-JOINT ROE-04. Hostile intent = hostile act on "
                "the airfield perimeter.",
                "TIC: immediate FM authorised; CAS request via JTAC on VHF "
                "250.100. CAS check-in NLT H+5.",
                "MEDEVAC: pickup at hangar 4 BAS or PZ TANGO. DUSTOFF-1 "
                "primary, civilian NH-90 backup at Koksijde.",
                "Pyrotechnics: GREEN STAR = phase complete; RED STAR = TIC; "
                "WHITE STAR = friendly identification; YELLOW SMOKE = LZ for "
                "follow-on.",
                "PIRs: enemy armour movement Maldegem, helo activity Wevelgem, "
                "civilian breach of perimeter.",
                "Airspace: ROZ 5 NM radius EBUL, surface to FL150. JTAC " "controls.",
                "Loss of comms — fallback to PRC-152 VHF 250.150, then HF "
                "8.250 USB.",
            ],
        },
        "sustainment": {
            "supply": (
                "JUMP load: 72 h IFAK + 3x basic load ammo + 2L water per "
                "operator. On seizure of fuel farm OBJ HERMES, captured fuel "
                "becomes SP-III FUEL. Class V resupply via follow-on lift. "
                "Class I/VIII at BAS DAGGER (hangar 4)."
            ),
            "medical": (
                "BAS DAGGER established at hangar 4 on field seizure. CCP "
                "STORM forward. MEDEVAC via DUSTOFF-1 (NH-90) primary, ETA "
                "12 min from Koksijde; civilian Brugge AZ St-Jan as final "
                "MTF. All operators IFAK + tourniquet + Quikclot."
            ),
            "personnel": (
                "120+ operators in initial drop. Replacement sticks held at "
                "Koksijde, on call after airfield certified secure (H+180 "
                "planning factor). KIA holding at hangar 4 pending repatriation."
            ),
        },
        "command_signal": {
            "command": (
                "BN CDR drops with ECHO CIE, takes CP at OBJ NEPTUNE post-"
                "seizure. XO drops with FOXTROT CIE, runs BN main from RV "
                "BRAVO until tower handover. S3 with HOTEL CIE. Succession: "
                "CDR → XO → S3 → SR Coy CDR present."
            ),
            "signal": (
                "Primary: VHF 250.100 (BN cmd). Alt: VHF 250.150. CAS: "
                "TAD-FUSCO 36 (JTAC). Contingency: HF 8.250 USB. Pyro per SOP. "
                "CoT TCP to BN TOC at Koksijde via SATCOM. Belgian Defence "
                "deconfliction net VHF 243.000 (guard). Challenge/password and "
                "running password per CEOI Annex H."
            ),
        },
    }


# ── helpers ─────────────────────────────────────────────────────────────────


def _operators_with_tokens(state: HierarchyState):
    return [op for op in state.operators if op.token]


def _seed_positions(
    session: AdminSession,
    state: HierarchyState,
    phase_offset: tuple[float, float],
    spread_m: float = 80.0,
) -> int:
    """Push every operator-with-token to a cluster around an anchor."""
    cx, cy = META.aor_center
    base = offset_m(cx, cy, *phase_offset)
    teams = list(state.teams.values())
    pushed = 0
    for ti, team in enumerate(teams):
        tx = (ti % 7 - 3) * spread_m + random.uniform(-12, 12)
        ty = (ti // 7) * spread_m + random.uniform(-12, 12)
        team_center = offset_m(*base, tx, ty)
        for oi, op in enumerate(team.operators):
            if not op.token:
                continue
            ox = (oi % 4) * 8.0 + random.uniform(-2, 2)
            oy = (oi // 4) * 8.0 + random.uniform(-2, 2)
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


def _scatter_drop(
    session: AdminSession,
    state: HierarchyState,
    dz_n: tuple[float, float],
    dz_s: tuple[float, float],
) -> int:
    """Split the battalion across two DZs to mimic real airborne planning.

    Roughly half the teams go to DZ NORTH (ECHO + BHQ slice), half to DZ
    SOUTH (FOXTROT + GOLF + HOTEL).
    """
    cx, cy = META.aor_center
    base_n = offset_m(cx, cy, *dz_n)
    base_s = offset_m(cx, cy, *dz_s)
    teams = list(state.teams.values())
    pushed = 0
    for ti, team in enumerate(teams):
        base = base_n if ti % 2 == 0 else base_s
        tx = (ti % 6 - 3) * 90.0 + random.uniform(-25, 25)
        ty = (ti // 6) * 90.0 + random.uniform(-25, 25)
        team_center = offset_m(*base, tx, ty)
        for oi, op in enumerate(team.operators):
            if not op.token:
                continue
            # Bigger spread on drop to look like scattered sticks landing.
            ox = (oi % 4) * 16.0 + random.uniform(-8, 8)
            oy = (oi // 4) * 16.0 + random.uniform(-8, 8)
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


# ── inject ─────────────────────────────────────────────────────────────────


def inject(api: AdminSession, token: str, state: HierarchyState) -> InjectResult:
    result = InjectResult()
    cx, cy = META.aor_center
    items: list[dict] = []

    # ── Drop zones (north + south of runway)
    items.append(dz(*offset_m(cx, cy, *DZ_NORTH), "NORTH"))
    items.append(dz(*offset_m(cx, cy, *DZ_SOUTH), "SOUTH"))

    # ── Rally points (markers at runway threshold + near tower)
    items.append(poi(*offset_m(cx, cy, *RV_ALPHA), "RV ALPHA", SIDC["ORP"]))
    items.append(poi(*offset_m(cx, cy, *RV_BRAVO), "RV BRAVO", SIDC["ORP"]))
    items.append(poi(*offset_m(cx, cy, *ORP_OFFSET), "ORP HALO", SIDC["ORP"]))

    # ── Three objectives on the airfield
    items.append(
        objective(*offset_m(cx, cy, *OBJ_NEPTUNE), "NEPTUNE — Tower", radius_m=80.0)
    )
    items.append(
        obj_area(
            *offset_m(cx, cy, *OBJ_NEPTUNE),
            "OBJ NEPTUNE — Control Tower",
            radius_m=120.0,
        )
    )

    items.append(
        objective(*offset_m(cx, cy, *OBJ_HERMES), "HERMES — Fuel", radius_m=120.0)
    )
    items.append(
        obj_area(
            *offset_m(cx, cy, *OBJ_HERMES), "OBJ HERMES — Fuel Farm", radius_m=160.0
        )
    )

    items.append(
        objective(*offset_m(cx, cy, *OBJ_JANUS), "JANUS — Hangars", radius_m=180.0)
    )
    items.append(
        obj_area(
            *offset_m(cx, cy, *OBJ_JANUS), "OBJ JANUS — Hangars 1-6", radius_m=220.0
        )
    )

    # ── Defence box (four BPs around the airfield)
    items.append(def_area(*offset_m(cx, cy, *DEF_BP_NORTH), "BP NORTH"))
    items.append(def_area(*offset_m(cx, cy, *DEF_BP_SOUTH), "BP SOUTH"))
    items.append(def_area(*offset_m(cx, cy, *DEF_BP_EAST), "BP EAST (Aalter)"))
    items.append(def_area(*offset_m(cx, cy, *DEF_BP_WEST), "BP WEST (Maldegem)"))

    # ── PZ for hot extraction
    items.append(pz(*offset_m(cx, cy, *PZ_TANGO), "TANGO"))

    # ── Friendly POIs
    items.append(
        poi(*offset_m(cx, cy, *CP_OFFSET), "CP TOWER (post-NEPTUNE)", SIDC["CP"])
    )
    items.append(
        poi(*offset_m(cx, cy, *BAS_OFFSET), "BAS DAGGER (hangar 4)", SIDC["BAS"])
    )
    items.append(poi(*offset_m(cx, cy, *CCP_OFFSET), "CCP STORM", SIDC["CCP"]))

    # ── Axes of advance
    items.append(
        atk_axis(*offset_m(cx, cy, 100, -550), "AXIS HAWK → NEPTUNE", rotation_deg=70)
    )
    items.append(
        atk_axis(*offset_m(cx, cy, 150, 700), "AXIS EAGLE → HERMES", rotation_deg=100)
    )
    items.append(
        atk_axis(*offset_m(cx, cy, 350, -300), "AXIS RAVEN → JANUS", rotation_deg=85)
    )

    # ── Phase lines
    items.append(
        phase_line(
            [
                offset_m(cx, cy, -1500, -1300),
                offset_m(cx, cy, 1500, -1300),
            ],
            "PL LOD (runway 07 thresh)",
        )
    )
    items.append(
        phase_line(
            [
                offset_m(cx, cy, -1500, 0),
                offset_m(cx, cy, 1500, 0),
            ],
            "PL OBJECTIVE (mid-field)",
        )
    )
    items.append(
        phase_line(
            [
                offset_m(cx, cy, -1500, 1300),
                offset_m(cx, cy, 1500, 1300),
            ],
            "PL DEFEND (runway 25 thresh)",
        )
    )

    # ── AO boundary (covers the field + approaches)
    items.append(
        boundary(
            [
                offset_m(cx, cy, 2200, -2500),
                offset_m(cx, cy, 2200, 2500),
                offset_m(cx, cy, -2200, 2500),
                offset_m(cx, cy, -2200, -2500),
                offset_m(cx, cy, 2200, -2500),
            ],
            "BDY AO FLANDERS",
        )
    )

    # ── Runway centreline (line graphic so it shows up)
    items.append(
        line_obj(
            "ROUTE",
            [
                offset_m(cx, cy, 0, -1200),
                offset_m(cx, cy, 0, 1200),
            ],
            "RWY 07/25 — 2400 m",
            SIDC["BOUNDARY"],
        )
    )

    # ── FLOT — enemy line N-S east of the field
    items.append(
        flot(
            [
                offset_m(cx, cy, -1800, 1500),
                offset_m(cx, cy, 1800, 1500),
            ],
            "FLOT — Aalter screen",
        )
    )

    # ── Enemy laydown
    enemy_clusters: list[tuple[tuple[float, float], int, str, str]] = [
        # On-field garrison
        (offset_m(cx, cy, 280, 80), 3, SIDC["ENEMY_INF"], "Tower garrison"),
        (offset_m(cx, cy, 220, 70), 1, SIDC["ENEMY_ADA"], "Konkurs ATGM tower roof"),
        (offset_m(cx, cy, -200, 950), 3, SIDC["ENEMY_INF"], "Fuel farm guard"),
        (offset_m(cx, cy, 320, -550), 2, SIDC["ENEMY_INF"], "Hangar guards"),
        (offset_m(cx, cy, 400, -650), 1, SIDC["ENEMY_ADA"], "23mm AAA hangar 6"),
        (offset_m(cx, cy, 50, -100), 2, SIDC["ENEMY_SNIPER"], "Tower sniper team"),
        # Knesselare QRF (south)
        (
            offset_m(cx, cy, -1800, 200),
            4,
            SIDC["ENEMY_MECH"],
            "Knesselare BTR-80 mech coy",
        ),
        (offset_m(cx, cy, -1900, 100), 1, SIDC["ENEMY_HQ"], "Knesselare CP"),
        # Maldegem armour (west)
        (offset_m(cx, cy, -300, -3500), 3, SIDC["ENEMY_ARMOR"], "Maldegem T-72M plt"),
        (offset_m(cx, cy, -400, -3400), 2, SIDC["ENEMY_INF"], "Maldegem mech inf"),
        # Aalter screen (east)
        (offset_m(cx, cy, -200, 2500), 3, SIDC["ENEMY_INF"], "Aalter recon plt"),
        (offset_m(cx, cy, 200, 2400), 2, SIDC["ENEMY_SNIPER"], "Aalter snipers"),
        # Mortar pit on northern perimeter
        (offset_m(cx, cy, 1400, 600), 2, SIDC["ENEMY_MORTAR"], "Mortar pit N"),
    ]
    for (a_lat, a_lon), count, sidc, label in enemy_clusters:
        for i in range(count):
            jlat, jlon = offset_m(
                a_lat,
                a_lon,
                random.uniform(-100, 100),
                random.uniform(-100, 100),
            )
            items.append(enemy(jlat, jlon, f"{label} #{i + 1}", sidc))

    created = post_overlay(api, token, items, result)
    enemy_records = [r for r in created if r.get("type") == "ENEMY"]

    # ── Register two CAS assets — GHOSTRIDER-1 and -2.
    for callsign, ordnance, notes in [
        (
            "GHOSTRIDER-1",
            "2x GBU-12 LGB, AGM-65, GAU-8",
            "On-station for FLANDERS GATE H-Hour to H+02:00",
        ),
        (
            "GHOSTRIDER-2",
            "2x GBU-12 LGB, GAU-8",
            "Relief on station H+01:30 to H+04:00",
        ),
    ]:
        try:
            api.post(
                "/cas/assets",
                token,
                {
                    "callsign": callsign,
                    "aircraft_type": "F-16C",
                    "ordnance": ordnance,
                    "frequency": "VHF 250.100",
                    "status": "AVAILABLE",
                    "notes": notes,
                },
            )
            result.extra["cas_assets"] = result.extra.get("cas_assets", 0) + 1
        except Exception:
            pass

    # ── Supply points
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

    # ── Initial drop: scatter the battalion across both DZs.
    placed = _scatter_drop(api, state, DZ_NORTH, DZ_SOUTH)
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

    activities = [
        "DIG-IN",
        "PATROL",
        "RECON",
        "RESUPPLY",
        "WITHDRAW",
        "COUNTER-ATTACK",
        "AMBUSH",
        "OBSERVE",
    ]
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
        "move": time.monotonic() + 8.0,
    }

    def _transition(new_idx: int) -> None:
        phase_name = PHASES[new_idx]
        log_cb(f"━ phase → {phase_name}")
        if phase_name == "JUMP":
            # Loop start: re-drop the battalion onto both DZs.
            moved = _scatter_drop(api, state, DZ_NORTH, DZ_SOUTH)
            log_cb(f"  battalion JUMP: {moved} parachutes deployed")
        else:
            moved = _seed_positions(
                api,
                state,
                PHASE_ANCHOR[phase_name],
                spread_m=80.0 if phase_name != "REGROUP" else 50.0,
            )
            log_cb(f"  re-positioned {moved} operator(s) → {phase_name}")

    log_cb(
        f"FLANDERS GATE phase clock started — JUMP for "
        f"{PHASE_DURATION['JUMP']:.0f}s"
    )

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
                random.uniform(-120, 120),
                random.uniform(-120, 120),
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

        # ── Operator drift around the phase anchor
        if now >= next_event["move"]:
            _jitter_subset(api, state, PHASE_ANCHOR[phase], subset_size=8)
            next_event["move"] = now + 6.0

        # ── TIC
        if now >= next_event["tic"]:
            lat, lon = offset_m(
                cx,
                cy,
                random.uniform(-1800, 1800),
                random.uniform(-2000, 2000),
            )
            post_tic(api, token, lat, lon)
            log_cb(f"[{phase}] TIC @ {mgrs(lat, lon)}")
            next_event["tic"] = now + random.uniform(*tic_rate)

        # ── Drone spot
        if now >= next_event["drone"]:
            lat, lon = offset_m(
                cx,
                cy,
                random.uniform(-2500, 2500),
                random.uniform(-2500, 2500),
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
                    "notes": f"FLANDERS GATE / phase={phase}",
                },
            )
            log_cb(f"[{phase}] DRONE @ {mgrs(lat, lon)}")
            next_event["drone"] = now + random.uniform(*drone_rate)

        # ── SALUTE / SPOT
        if now >= next_event["salute"]:
            lat, lon = offset_m(
                cx,
                cy,
                random.uniform(-2000, 2000),
                random.uniform(-2200, 2200),
            )
            post_salute(
                api,
                token,
                {
                    "size": random.choice(["FIRE TEAM", "SQUAD", "PLATOON", "COMPANY"]),
                    "activity": random.choice(activities),
                    "location": mgrs(lat, lon),
                    "unit": random.choice(
                        [
                            "RDB garrison",
                            "Knesselare QRF",
                            "Maldegem armour",
                            "Aalter recon",
                            "civilian breach",
                            "UNK",
                        ]
                    ),
                    "time": "NOW",
                    "equipment": random.choice(
                        [
                            "small arms",
                            "BTR-80",
                            "T-72M",
                            "Konkurs ATGM",
                            "23mm AAA",
                            "Mi-24 helo",
                            "snipers",
                        ]
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
                            [
                                "ADJUST_FIRE",
                                "FIRE_FOR_EFFECT",
                                "SUPPRESSION",
                            ]
                        ),
                        "ammunition": random.choice(["HE", "ILLUM", "SMOKE"]),
                        "quantity": random.randint(2, 12),
                        "description": (
                            f"FLANDERS GATE {phase} — "
                            f"TGT {str(tgt.get('notes', ''))[:40]}"
                        ),
                    },
                )
                log_cb(f"[{phase}] FM on {str(tgt.get('notes', ''))[:30]}")
            except Exception:
                pass
            next_event["fm"] = now + random.uniform(*fm_rate)

        # ── CAS 9-liner
        if enemies and now >= next_event["cas"]:
            tgt = random.choice(enemies)
            lat, lon = float(tgt["latitude"]), float(tgt["longitude"])
            asset = random.choice(["GHOSTRIDER-1", "GHOSTRIDER-2"])
            try:
                api.post(
                    "/cas/requests",
                    token,
                    {
                        "line_1": asset,
                        "line_2": "INITIAL",
                        "line_3": "DAGGER-6",
                        "line_4": f"{lat:.5f}, {lon:.5f}",
                        "line_5": mgrs(lat, lon),
                        "line_5_mgrs": mgrs(lat, lon),
                        "line_5_lat": lat,
                        "line_5_lon": lon,
                        "line_6": str(tgt.get("notes", "hostile"))[:80],
                        "line_7": "MARKER: IR strobe + RED smoke",
                        "line_8": "FRIENDLIES 400m W on runway",
                        "line_9": "EGRESS NW over polders",
                        "tic": phase == "ATTACK",
                    },
                )
                log_cb(
                    f"[{phase}] CAS ({asset}) → " f"{str(tgt.get('notes', ''))[:30]}"
                )
            except Exception:
                pass
            next_event["cas"] = now + random.uniform(*cas_rate)

        # ── LOGREP
        if now >= next_event["logrep"]:
            company = random.choice(
                [
                    "ECHO CIE",
                    "FOXTROT CIE",
                    "GOLF CIE",
                    "HOTEL CIE",
                    "BHQ",
                    "PATHFINDER DET",
                ]
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
                        "operation": "FLANDERS GATE",
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
                            ["GREEN", "AMBER — radio degraded", "AMBER"]
                        )
                    },
                    "section_e": {
                        "maintenance": random.choice(
                            [
                                "nominal",
                                "PRC-152 down — using backup",
                                "ATGM launcher needs alignment",
                            ]
                        )
                    },
                    "section_f": {
                        "medical": (
                            f"{len(casualties_taken)} WIA evac'd via DUSTOFF-1"
                            if casualties_taken
                            else "no casualties"
                        )
                    },
                    "section_g": {
                        "requests": random.sample(
                            [
                                "resupply Class V",
                                "additional Spike rounds",
                                "Class III topoff from HERMES",
                                "Class VIII medical",
                                "additional pyrotechnics",
                                "BREACHER kit",
                                "follow-on lift expedite",
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
            phase in ("ATTACK", "DEFENCE")
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
                clat, clon = offset_m(
                    cx,
                    cy,
                    random.uniform(-600, 600),
                    random.uniform(-600, 600),
                )
                log_cb(f"[{phase}] CASUALTY {hit.callsign} → {outcome}")
                if outcome == "INOPS":
                    post_medevac(
                        api,
                        token,
                        {
                            "line_1": f"PICKUP: {mgrs(clat, clon)}",
                            "line_2": "FREQ: VHF 250.100  CS: DUSTOFF-1",
                            "line_3": "A — URGENT  · 1 PATIENT",
                            "line_4": ("B — SPECIAL: tourniquet, IV, airway kit"),
                            "line_5": "L — 1 LITTER, 0 AMBULATORY",
                            "line_6": (
                                "N — NO ENEMY AT PZ"
                                if phase == "DEFENCE"
                                else "P — POSSIBLE ENEMY AT PZ"
                            ),
                            "line_7": "C — IR STROBE + RED SMOKE",
                            "line_8": "A — A NATO MILITARY",
                            "line_9": ("EBUL hangar 4 BAS DAGGER, or PZ TANGO if hot"),
                            "patient_callsign": hit.callsign,
                            "patient_status": outcome,
                            "latitude": clat,
                            "longitude": clon,
                        },
                    )
                    log_cb(f"[{phase}] MEDEVAC → {hit.callsign}")
            next_event["casualty"] = now + random.uniform(*casualty_rate)

        # Sleep in 100 ms ticks so Stop is responsive.
        for _ in range(10):
            if stop_event.is_set():
                break
            time.sleep(0.1)

    log_cb("FLANDERS GATE phase clock stopped")
