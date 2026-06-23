"""Operation RED WINGS — Special Reconnaissance (28 June 2005).

A four-man SEAL recon team is inserted by MH-47 onto Sawtalo Sar to observe
a high-value Taliban commander's village. No friendly assault — the laydown
is reconnaissance: insert LZ, hide site, observation post, exfil PZ, and the
enemy positions the team is sent to confirm.
"""

from __future__ import annotations

from sim_utils import Api

from sim_gui.hierarchy_seeder import HierarchyState
from sim_gui.scenarios.base import (
    InjectResult,
    ScenarioMeta,
    post_overlay,
)
from sim_gui.scenarios.geo import (
    SIDC,
    boundary,
    enemy,
    line_obj,
    lz,
    obj_area,
    objective,
    offset_m,
    phase_line,
    poi,
    pz,
)

META = ScenarioMeta(
    id="red_wings",
    name="Operation RED WINGS",
    mission_type="Special Reconnaissance",
    real_world="Sawtalo Sar, Kunar Province, AF — 28 Jun 2005, SDV-1",
    aor_center=(35.0030, 70.9870),
    map_zoom=14,
    summary=(
        "MH-47 insert, four-man SEAL team moves to OP overlooking Salar Ban / "
        "Chichal villages to confirm Shah's location. PZ at HASTY 7 km NW."
    ),
)

VEHICLE_FLAVOR = "airborne"


def inject(api: Api, token: str, state: HierarchyState) -> InjectResult:
    result = InjectResult()
    cx, cy = META.aor_center
    items: list[dict] = []

    # Insert LZ on the ridgeline, OP overlooking the village
    items.append(lz(*offset_m(cx, cy, 500, 200), "INSERT"))
    items.append(poi(*offset_m(cx, cy, 100, 30), "HIDE SITE — OP REDWING", SIDC["CP"]))
    items.append(objective(cx, cy, "SAWTALO SAR", radius_m=200.0))

    # Two villages — Salar Ban and Chichal
    salar = offset_m(cx, cy, -700, 800)
    chichal = offset_m(cx, cy, -1100, -400)
    items.append(obj_area(*salar, "OBJ SALAR BAN", radius_m=200.0))
    items.append(obj_area(*chichal, "OBJ CHICHAL", radius_m=200.0))

    items.append(pz(*offset_m(cx, cy, 4000, -4000), "HASTY"))

    # Friendly POIs
    items.append(poi(*offset_m(cx, cy, 4200, -4100), "ORP HASTY", SIDC["ORP"]))
    items.append(poi(*offset_m(cx, cy, 4300, -4200), "CCP", SIDC["CCP"]))

    # Enemy laydown
    items.append(enemy(*salar, "Shah's main element", SIDC["ENEMY_INF"], echelon="PL"))
    items.append(enemy(*offset_m(*salar, 100, 50), "DShK position", SIDC["ENEMY_ADA"]))
    items.append(enemy(*chichal, "Outpost (sympathisers)", SIDC["ENEMY_INF"]))
    items.append(
        enemy(
            *offset_m(cx, cy, 200, 200), "Goatherders (not a threat)", SIDC["ENEMY_INF"]
        )
    )

    # Recon route — from LZ INSERT to the OP
    items.append(
        line_obj(
            "ROUTE",
            [offset_m(cx, cy, 500, 200), offset_m(cx, cy, 250, 100), (cx, cy)],
            "ROUTE GAZELLE",
            SIDC["PHASE_LINE"],
        )
    )
    items.append(
        boundary(
            [
                offset_m(cx, cy, 4500, -4500),
                offset_m(cx, cy, 1500, 2000),
                offset_m(cx, cy, -2000, 1500),
                offset_m(cx, cy, -2000, -2000),
                offset_m(cx, cy, 4500, -4500),
            ],
            "BDY AO KUNAR",
        )
    )
    items.append(
        phase_line(
            [offset_m(cx, cy, -1500, -1500), offset_m(cx, cy, 1500, 1500)],
            "PL RAVEN",
        )
    )

    post_overlay(api, token, items, result)
    return result
