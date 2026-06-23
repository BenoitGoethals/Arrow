"""Operation URGENT FURY — Grenada invasion (25 Oct 1983).

Joint airborne (75th Rangers HALO onto Point Salines) + amphibious (22nd MEU
secures Pearls airport) seizure of the island. Two areas of operation linked
by a FLOT line, multiple landing zones, multiple objectives.
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
    dz,
    enemy,
    flot,
    lz,
    obj_area,
    offset_m,
    phase_line,
    poi,
    pz,
)

META = ScenarioMeta(
    id="urgent_fury",
    name="Operation URGENT FURY",
    mission_type="Joint Airborne + Amphibious Assault",
    real_world="Grenada, 25 Oct 1983 — 75th Ranger Rgt / 82nd Abn / 22nd MEU",
    aor_center=(12.0480, -61.7400),
    map_zoom=12,
    summary=(
        "Rangers HALO onto Point Salines airfield (south) while Marines storm "
        "Pearls airport beach (NE). Linkup along the central PL AMBER; PC at "
        "Governor-General's residence."
    ),
)

VEHICLE_FLAVOR = "amphib"


def inject(api: Api, token: str, state: HierarchyState) -> InjectResult:
    result = InjectResult()
    cx, cy = META.aor_center
    items: list[dict] = []

    # Point Salines (south) — Ranger drop + airfield seizure
    salines = offset_m(cx, cy, -5500, -2000)
    items.append(dz(*salines, "POINT SALINES"))
    items.append(obj_area(*salines, "OBJ AIRFIELD SALINES", radius_m=800.0))
    items.append(lz(*offset_m(*salines, 500, 200), "GOLD"))
    items.append(poi(*offset_m(*salines, 400, -300), "ORP RANGER", SIDC["ORP"]))

    # Pearls (NE) — Marine amphib
    pearls = offset_m(cx, cy, 4500, 3500)
    items.append(beachhead(*pearls, "PEARLS", radius_m=400.0))
    items.append(lz(*offset_m(*pearls, 300, 200), "RED"))
    items.append(
        obj_area(*offset_m(*pearls, 500, -200), "OBJ PEARLS AIRPORT", radius_m=600.0)
    )

    # Central objective — Governor-General's residence
    govt = offset_m(cx, cy, -1500, 1000)
    items.append(obj_area(*govt, "OBJ GG RESIDENCE", radius_m=200.0))
    items.append(poi(*offset_m(*govt, 100, 0), "BAS", SIDC["BAS"]))
    items.append(poi(*offset_m(*govt, -100, 0), "CCP", SIDC["CCP"]))
    items.append(pz(*offset_m(*govt, 250, 0), "EXFIL"))

    # Enemy laydown — Cuban + PRA positions
    items.append(
        enemy(*offset_m(*salines, 100, 50), "Cuban construction bn", SIDC["ENEMY_MECH"])
    )
    items.append(enemy(*offset_m(*salines, -200, 300), "PRA AAA", SIDC["ENEMY_ADA"]))
    items.append(
        enemy(*offset_m(*pearls, -200, 0), "PRA infantry coy", SIDC["ENEMY_INF"])
    )
    items.append(enemy(*offset_m(*govt, 50, 50), "Govt detail", SIDC["ENEMY_INF"]))
    items.append(enemy(*offset_m(cx, cy, 0, 0), "Calivigny barracks", SIDC["ENEMY_HQ"]))

    # FLOT + boundary + phase line
    items.append(
        flot(
            [
                offset_m(cx, cy, 0, -8000),
                offset_m(cx, cy, 0, -2000),
                offset_m(cx, cy, 1000, 2000),
                offset_m(cx, cy, 2500, 6000),
            ],
            "FLOT D-DAY",
        )
    )
    items.append(
        boundary(
            [
                offset_m(cx, cy, 8000, -8000),
                offset_m(cx, cy, 8000, 8000),
                offset_m(cx, cy, -8000, 8000),
                offset_m(cx, cy, -8000, -8000),
                offset_m(cx, cy, 8000, -8000),
            ],
            "BDY AO CARIB",
        )
    )
    items.append(
        phase_line(
            [offset_m(cx, cy, -2000, -10000), offset_m(cx, cy, -2000, 10000)],
            "PL AMBER",
        )
    )

    post_overlay(api, token, items, result)
    post_tic(api, token, *salines, result)
    post_tic(api, token, *pearls, result)
    return result
