"""Operation GOTHIC SERPENT — Mogadishu raid (3-4 Oct 1993).

Helo-borne urban Direct Action by TF Ranger to snatch Mohammed Farah Aidid
lieutenants from a building near the Bakara market. The raid that became
"Black Hawk Down".
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
    lz,
    obj_area,
    objective,
    offset_m,
    phase_line,
    poi,
    pz,
)

META = ScenarioMeta(
    id="gothic_serpent",
    name="Operation GOTHIC SERPENT",
    mission_type="Urban Direct Action (Air Assault)",
    real_world="Mogadishu, Somalia, 3 Oct 1993 — TF Ranger / TF160",
    aor_center=(2.0469, 45.3320),
    map_zoom=15,
    summary=(
        "MH-6 lands Delta on TGT roof; Rangers fast-rope four-corner cordon. "
        "Ground convoy extracts. Two Black Hawks down — perimeter holds until "
        "Pakistani/Malaysian armoured QRF arrives."
    ),
)

VEHICLE_FLAVOR = "land"


def inject(api: Api, token: str, state: HierarchyState) -> InjectResult:
    result = InjectResult()
    cx, cy = META.aor_center
    items: list[dict] = []

    # Target building (Olympic Hotel area) + cordon
    items.append(obj_area(cx, cy, "OBJ BAKARA TGT", radius_m=80.0))
    items.append(objective(cx, cy, "BAKARA", radius_m=40.0))

    items.append(lz(*offset_m(cx, cy, 30, 10), "ROOF"))
    items.append(pz(*offset_m(cx, cy, 1800, -800), "STADIUM"))  # New Port / stadium

    # Four-corner Ranger cordon
    items.append(poi(*offset_m(cx, cy, 80, -80), "CHALK 1", SIDC["CP"]))
    items.append(poi(*offset_m(cx, cy, 80, 80), "CHALK 2", SIDC["CP"]))
    items.append(poi(*offset_m(cx, cy, -80, 80), "CHALK 3", SIDC["CP"]))
    items.append(poi(*offset_m(cx, cy, -80, -80), "CHALK 4", SIDC["CP"]))
    items.append(poi(*offset_m(cx, cy, 1500, -600), "CCP", SIDC["CCP"]))
    items.append(poi(*offset_m(cx, cy, 1600, -700), "BAS", SIDC["BAS"]))

    # Two Black Hawk crash sites (Super 61 & Super 64)
    items.append(poi(*offset_m(cx, cy, -150, 200), "CRASH 1 — SUPER 61", SIDC["CP"]))
    items.append(poi(*offset_m(cx, cy, -800, -200), "CRASH 2 — SUPER 64", SIDC["CP"]))

    # Aidid militia laydown — heavy
    items.append(
        enemy(*offset_m(cx, cy, 100, 0), "SNA militia (Hawiye)", SIDC["ENEMY_INF"])
    )
    items.append(enemy(*offset_m(cx, cy, -50, 150), "RPG team N", SIDC["ENEMY_INF"]))
    items.append(
        enemy(*offset_m(cx, cy, -250, 100), "RPG team Crash-1", SIDC["ENEMY_INF"])
    )
    items.append(
        enemy(*offset_m(cx, cy, -900, -300), "RPG team Crash-2", SIDC["ENEMY_INF"])
    )
    items.append(
        enemy(*offset_m(cx, cy, 200, 200), "Technical (DShK)", SIDC["ENEMY_TECH"])
    )
    items.append(
        enemy(*offset_m(cx, cy, -300, -300), "Mortar pit", SIDC["ENEMY_MORTAR"])
    )

    items.append(
        boundary(
            [
                offset_m(cx, cy, 400, -400),
                offset_m(cx, cy, 400, 400),
                offset_m(cx, cy, -1100, 400),
                offset_m(cx, cy, -1100, -400),
                offset_m(cx, cy, 400, -400),
            ],
            "BDY CORDON",
        )
    )
    items.append(
        phase_line(
            [offset_m(cx, cy, -1200, 0), offset_m(cx, cy, 2000, 0)],
            "PL HAWIYE",
        )
    )

    post_overlay(api, token, items, result)
    post_tic(api, token, *offset_m(cx, cy, -150, 200), result)
    post_tic(api, token, *offset_m(cx, cy, -800, -200), result)
    return result
