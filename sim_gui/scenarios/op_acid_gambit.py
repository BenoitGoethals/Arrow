"""Operation ACID GAMBIT — Renacer Prison hostage rescue (20 Dec 1989).

Delta Force MH-6 Little Birds rope onto the roof of Carcel Modelo / Renacer
Prison on Lake Gatun, Panama, to free CIA asset Kurt Muse. Set on the lake
shore near the prison.
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
    dz,
    enemy,
    lz,
    obj_area,
    objective,
    offset_m,
    phase_line,
    poi,
    pz,
)

META = ScenarioMeta(
    id="acid_gambit",
    name="Operation ACID GAMBIT",
    mission_type="Hostage Rescue (Airborne / Heliborne)",
    real_world="Renacer Prison, Panama, 20 Dec 1989 — 1st SFOD-D / TF GREEN",
    aor_center=(9.2289, -79.6519),
    map_zoom=15,
    summary=(
        "Little Birds land an assault team on the roof while a Ranger blocking "
        "force air-drops west to seal the exfil corridor; PC extracted via UH-60."
    ),
)

VEHICLE_FLAVOR = "airborne"


def inject(api: Api, token: str, state: HierarchyState) -> InjectResult:
    result = InjectResult()
    cx, cy = META.aor_center
    items: list[dict] = []

    items.append(obj_area(cx, cy, "OBJ RENACER — prison block", radius_m=70.0))
    items.append(objective(cx, cy, "RENACER", radius_m=40.0))

    items.append(lz(*offset_m(cx, cy, 25, 5), "ROOF"))
    items.append(lz(*offset_m(cx, cy, -180, 0), "ALT"))
    items.append(dz(*offset_m(cx, cy, -120, -350), "WEST"))
    items.append(pz(*offset_m(cx, cy, 250, 320), "EXFIL"))

    items.append(poi(*offset_m(cx, cy, 400, -400), "ORP TROUT", SIDC["ORP"]))
    items.append(poi(*offset_m(cx, cy, 300, 200), "CCP", SIDC["CCP"]))
    items.append(poi(*offset_m(cx, cy, 350, 250), "BAS", SIDC["BAS"]))

    items.append(enemy(*offset_m(cx, cy, 20, 30), "PDF guard force", SIDC["ENEMY_INF"]))
    items.append(
        enemy(*offset_m(cx, cy, -20, -20), "Watchtower N", SIDC["ENEMY_SNIPER"])
    )
    items.append(
        enemy(*offset_m(cx, cy, -10, 50), "Watchtower E", SIDC["ENEMY_SNIPER"])
    )
    items.append(enemy(*offset_m(cx, cy, 150, 100), "QRF barracks", SIDC["ENEMY_INF"]))
    items.append(
        enemy(*offset_m(cx, cy, -200, -150), "Boat dock patrol", SIDC["ENEMY_BOAT"])
    )

    items.append(
        boundary(
            [
                offset_m(cx, cy, 600, -600),
                offset_m(cx, cy, 600, 600),
                offset_m(cx, cy, -600, 600),
                offset_m(cx, cy, -600, -600),
                offset_m(cx, cy, 600, -600),
            ],
            "BDY AO GATUN",
        )
    )
    items.append(
        phase_line(
            [offset_m(cx, cy, -400, -100), offset_m(cx, cy, 400, -100)],
            "PL AMBER",
        )
    )

    post_overlay(api, token, items, result)
    post_tic(api, token, cx, cy, result)
    return result
