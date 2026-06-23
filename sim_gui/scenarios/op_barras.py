"""Operation BARRAS — Sierra Leone hostage rescue (10 Sep 2000).

SAS / 1 PARA Chinook air assault to free Royal Irish Rangers held by the
West Side Boys gang at Gberi Bana and Magbeni on the Rokel Creek.
"""

from __future__ import annotations

from sim_utils import Api

from sim_gui.hierarchy_seeder import HierarchyState
from sim_gui.scenarios.base import (
    InjectResult,
    ScenarioMeta,
    post_overlay,
    post_tic,
)
from sim_gui.scenarios.geo import (
    SIDC,
    boundary,
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

META = ScenarioMeta(
    id="barras",
    name="Operation BARRAS",
    mission_type="Hostage Rescue (Air Assault)",
    real_world="Gberi Bana / Magbeni, Rokel Creek, SL — 10 Sep 2000",
    aor_center=(8.5400, -12.9300),
    map_zoom=14,
    summary=(
        "Three Chinooks: D Sqn 22 SAS lands at Gberi Bana to free the Royal "
        "Irish; A Coy 1 PARA assaults Magbeni across the creek as fire support."
    ),
)

VEHICLE_FLAVOR = "airborne"


def inject(api: Api, token: str, state: HierarchyState) -> InjectResult:
    result = InjectResult()
    cx, cy = META.aor_center
    items: list[dict] = []

    # Two villages — across the Rokel Creek
    gberi = offset_m(cx, cy, 400, -200)
    magbeni = offset_m(cx, cy, -400, 200)
    items.append(obj_area(*gberi, "OBJ GBERI BANA", radius_m=180.0))
    items.append(obj_area(*magbeni, "OBJ MAGBENI", radius_m=180.0))
    items.append(objective(*gberi, "RESCUE", radius_m=60.0))

    # LZs and PZ
    items.append(lz(*offset_m(*gberi, 100, 0), "SAS NORTH"))
    items.append(lz(*offset_m(*magbeni, -50, 0), "PARA SOUTH"))
    items.append(pz(*offset_m(cx, cy, 800, 600), "EXFIL"))

    # Friendly POIs
    items.append(poi(*offset_m(cx, cy, 700, 700), "ORP CRATE", SIDC["ORP"]))
    items.append(poi(*offset_m(cx, cy, 750, 750), "CCP", SIDC["CCP"]))
    items.append(poi(*offset_m(cx, cy, 800, 800), "BAS", SIDC["BAS"]))

    # West Side Boys
    items.append(
        enemy(
            *offset_m(*gberi, 30, 30),
            "WSB main element",
            SIDC["ENEMY_INF"],
            echelon="PL",
        )
    )
    items.append(enemy(*offset_m(*gberi, 80, -40), "WSB technical", SIDC["ENEMY_TECH"]))
    items.append(
        enemy(*offset_m(*magbeni, 0, 80), "WSB mortar pit", SIDC["ENEMY_MORTAR"])
    )
    items.append(enemy(*offset_m(*magbeni, 40, -40), "WSB ZPU AAA", SIDC["ENEMY_ADA"]))

    items.append(
        flot(
            [offset_m(cx, cy, -100, -500), offset_m(cx, cy, -100, 500)],
            "FLOT ROKEL CREEK",
        )
    )
    items.append(
        boundary(
            [
                offset_m(cx, cy, 1500, -1500),
                offset_m(cx, cy, 1500, 1500),
                offset_m(cx, cy, -1500, 1500),
                offset_m(cx, cy, -1500, -1500),
                offset_m(cx, cy, 1500, -1500),
            ],
            "BDY AO OCCRA",
        )
    )
    items.append(
        phase_line(
            [offset_m(cx, cy, -1500, 0), offset_m(cx, cy, 1500, 0)],
            "PL HAMMER",
        )
    )

    post_overlay(api, token, items, result)
    post_tic(api, token, *gberi, result)
    post_tic(api, token, *magbeni, result)
    return result
