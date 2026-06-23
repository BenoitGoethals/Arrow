"""Operation ANACONDA — Shahi-Kot Valley (2-18 March 2002).

Coalition air assault into the Shahi-Kot valley, eastern Afghanistan, to
destroy al-Qaeda and Taliban forces in the surrounding ridgelines. Multiple
LZs (GINGER, GIDDY, GRACELAND), valley-floor objectives, ridge-top enemy.
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
    atk_axis,
    boundary,
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
    id="anaconda",
    name="Operation ANACONDA",
    mission_type="Air Assault Valley Sweep",
    real_world="Shahi-Kot Valley, Paktia Province, AF — 2 Mar 2002",
    aor_center=(33.3100, 69.3000),
    map_zoom=12,
    summary=(
        "10th Mountain + 101st AAA Black Hawk into three valley LZs; SEAL/Delta "
        "blocking positions on the ridges; CAS engages cave complexes."
    ),
)

VEHICLE_FLAVOR = "airborne"


def inject(api: Api, token: str, state: HierarchyState) -> InjectResult:
    result = InjectResult()
    cx, cy = META.aor_center
    items: list[dict] = []

    # Three LZs spread across the valley floor
    items.append(lz(*offset_m(cx, cy, 2500, -800), "GINGER"))
    items.append(lz(*offset_m(cx, cy, 0, 0), "GIDDY"))
    items.append(lz(*offset_m(cx, cy, -2500, 800), "GRACELAND"))
    items.append(pz(*offset_m(cx, cy, 0, -3500), "FOXTROT"))

    # Three objectives — cave complexes & villages
    items.append(
        obj_area(*offset_m(cx, cy, 1500, 1200), "OBJ REMINGTON", radius_m=300.0)
    )
    items.append(
        obj_area(*offset_m(cx, cy, -1200, -500), "OBJ HARRIMAN", radius_m=300.0)
    )
    items.append(obj_area(*offset_m(cx, cy, 500, 2200), "OBJ MARZAK", radius_m=300.0))

    # Friendly POIs
    items.append(poi(*offset_m(cx, cy, 0, -2500), "TF RAKKASAN HQ", SIDC["CP"]))
    items.append(poi(*offset_m(cx, cy, 200, -1800), "CCP", SIDC["CCP"]))
    items.append(poi(*offset_m(cx, cy, -200, -2000), "BAS", SIDC["BAS"]))

    # Ridge-top enemy — DShK and 82mm mortars
    items.append(
        enemy(
            *offset_m(cx, cy, 1800, 2500), "Takur Ghar ridge — DShK", SIDC["ENEMY_ADA"]
        )
    )
    items.append(
        enemy(
            *offset_m(cx, cy, -1800, 1800), "West ridge — fighters", SIDC["ENEMY_INF"]
        )
    )
    items.append(enemy(*offset_m(cx, cy, 0, 3000), "Mortar pit", SIDC["ENEMY_MORTAR"]))
    items.append(
        enemy(*offset_m(cx, cy, -300, -2500), "Cave 1 — small arms", SIDC["ENEMY_INF"])
    )
    items.append(
        enemy(*offset_m(cx, cy, 2000, 0), "Cave 2 — RPG team", SIDC["ENEMY_INF"])
    )
    items.append(
        enemy(*offset_m(cx, cy, -2200, 2200), "Cave 3 — 12.7mm", SIDC["ENEMY_ADA"])
    )

    items.append(atk_axis(*offset_m(cx, cy, 0, -1500), "AXIS WHALE", rotation_deg=0))
    items.append(
        flot(
            [offset_m(cx, cy, -3000, -4000), offset_m(cx, cy, 3000, -4000)],
            "FLOT BLUE",
        )
    )
    items.append(
        boundary(
            [
                offset_m(cx, cy, 4000, -5000),
                offset_m(cx, cy, 4000, 5000),
                offset_m(cx, cy, -4000, 5000),
                offset_m(cx, cy, -4000, -5000),
                offset_m(cx, cy, 4000, -5000),
            ],
            "BDY AO HEAVY METAL",
        )
    )
    items.append(
        phase_line(
            [offset_m(cx, cy, -4000, -1500), offset_m(cx, cy, 4000, -1500)],
            "PL EMERALD",
        )
    )

    post_overlay(api, token, items, result)
    post_tic(api, token, *offset_m(cx, cy, 1800, 2500), result)
    return result
