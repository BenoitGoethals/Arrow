"""Operation EARNEST WILL / PRIME CHANCE — Persian Gulf maritime ops (1987-88).

Riverine / maritime interdiction: SEAL MkV and Mk III SOC boats interdict
Iranian mine-laying vessels and seize oil platforms used as IRGC firebases.
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
    beachhead,
    boundary,
    enemy,
    flot,
    obj_area,
    objective,
    offset_m,
    phase_line,
    poi,
    pz,
)

META = ScenarioMeta(
    id="earnest_will",
    name="Operation EARNEST WILL / PRIME CHANCE",
    mission_type="Riverine / Maritime Interdiction",
    real_world="Persian Gulf, 1987-88 — NSWG-1 / TF 160",
    aor_center=(26.7000, 51.5000),
    map_zoom=10,
    summary=(
        "SEAL Mk V boats interdict Iran Ajr mine-layer and board the Rostam/Sirri "
        "oil platforms used as IRGC firebases."
    ),
)

VEHICLE_FLAVOR = "riverine"


def inject(api: Api, token: str, state: HierarchyState) -> InjectResult:
    result = InjectResult()
    cx, cy = META.aor_center
    items: list[dict] = []

    # Oil platform Rostam (boarded)
    rostam = offset_m(cx, cy, 8000, -12000)
    items.append(beachhead(*rostam, "ROSTAM PLATFORM", radius_m=300.0))
    items.append(objective(*rostam, "ROSTAM", radius_m=120.0))
    items.append(pz(*offset_m(*rostam, 600, 600), "EXFIL"))

    # Iran Ajr mine-layer (intercepted) + escorting patrol boats
    ajr = offset_m(cx, cy, -5000, 9000)
    items.append(enemy(*ajr, "Iran Ajr mine-layer", SIDC["ENEMY_BOAT"]))
    items.append(
        enemy(*offset_m(*ajr, 800, 200), "Boghammar patrol 1", SIDC["ENEMY_BOAT"])
    )
    items.append(
        enemy(*offset_m(*ajr, -600, -400), "Boghammar patrol 2", SIDC["ENEMY_BOAT"])
    )

    # Platform defenders
    items.append(
        enemy(*offset_m(*rostam, 50, 50), "IRGC platform garrison", SIDC["ENEMY_INF"])
    )
    items.append(enemy(*offset_m(*rostam, -80, 100), "23mm AAA", SIDC["ENEMY_ADA"]))

    # Mine field (polygon)
    mines = offset_m(cx, cy, 0, 3000)
    items.append(
        obj_area(
            *mines,
            "MINE FIELD (Iran Ajr drop)",
            radius_m=1500.0,
            sidc=SIDC["OBJECTIVE"],
            affiliation="ENEMY",
        )
    )

    # Friendly POIs — staging on USS Guadalcanal
    cv = offset_m(cx, cy, -15000, -10000)
    items.append(poi(*cv, "USS GUADALCANAL — staging", SIDC["BAS"]))
    items.append(poi(*offset_m(*cv, 400, 400), "CCP", SIDC["CCP"]))

    items.append(
        flot(
            [
                offset_m(cx, cy, 12000, -20000),
                offset_m(cx, cy, 12000, 20000),
            ],
            "FLOT NORTH GULF",
        )
    )
    items.append(
        boundary(
            [
                offset_m(cx, cy, 20000, -25000),
                offset_m(cx, cy, 20000, 25000),
                offset_m(cx, cy, -20000, 25000),
                offset_m(cx, cy, -20000, -25000),
                offset_m(cx, cy, 20000, -25000),
            ],
            "BDY AO MIDDLE GULF",
        )
    )
    items.append(
        phase_line(
            [offset_m(cx, cy, 0, -25000), offset_m(cx, cy, 0, 25000)],
            "PL MERIDIAN",
        )
    )

    post_overlay(api, token, items, result)
    post_tic(api, token, *rostam, result)
    return result
