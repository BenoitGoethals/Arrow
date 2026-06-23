"""Operation NIMROD — Iranian Embassy siege (5 May 1980).

22 SAS B Sqn dynamic-entry assault on the Iranian Embassy at 16 Princes Gate,
London. Urban CT: no helo LZ, no DZ — cordon polygon, multiple entry points,
hostages and gunmen inside the OBJ.
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
    obj_area,
    objective,
    offset_m,
    phase_line,
    poi,
)

META = ScenarioMeta(
    id="nimrod",
    name="Operation NIMROD",
    mission_type="Urban Counter-Terrorism",
    real_world="16 Princes Gate, London, 5 May 1980 — 22 SAS B Sqn",
    aor_center=(51.5005, -0.1769),
    map_zoom=18,
    summary=(
        "Red & Blue teams abseil from the roof + breach front; rear assault "
        "via Princes Gardens. MET D11 marksmen on outer cordon."
    ),
)

VEHICLE_FLAVOR = "land"


def inject(api: Api, token: str, state: HierarchyState) -> InjectResult:
    result = InjectResult()
    cx, cy = META.aor_center
    items: list[dict] = []

    items.append(obj_area(cx, cy, "OBJ EMBASSY", radius_m=25.0))
    items.append(objective(cx, cy, "PRINCES GATE", radius_m=15.0))

    # Entry / cordon points
    items.append(poi(*offset_m(cx, cy, 12, 0), "FRONT ENTRY", SIDC["CP"]))
    items.append(poi(*offset_m(cx, cy, -12, 0), "REAR ENTRY", SIDC["CP"]))
    items.append(poi(*offset_m(cx, cy, 0, 12), "ROOF ABSEIL", SIDC["CP"]))
    items.append(poi(*offset_m(cx, cy, 80, -80), "MET CP", SIDC["CP"]))
    items.append(poi(*offset_m(cx, cy, 90, 90), "D11 MARKSMAN POST", SIDC["CP"]))
    items.append(poi(*offset_m(cx, cy, -100, -100), "BAS — staging", SIDC["BAS"]))
    items.append(poi(*offset_m(cx, cy, -110, -90), "CCP", SIDC["CCP"]))
    items.append(poi(*offset_m(cx, cy, 110, 110), "ORP NIMROD", SIDC["ORP"]))

    # Gunmen — 6 known, named "TGT-1..6"
    for i, (n, e) in enumerate(
        [(3, -3), (-3, 3), (0, 5), (5, 0), (-5, -2), (2, 5)], start=1
    ):
        items.append(enemy(*offset_m(cx, cy, n, e), f"TGT-{i}", SIDC["ENEMY_INF"]))

    # Inner cordon polygon (tight, ~120 m)
    items.append(
        obj_area(
            cx,
            cy,
            "INNER CORDON",
            radius_m=120.0,
            sidc=SIDC["BOUNDARY"],
            echelon="PL",
        )
    )
    items.append(
        boundary(
            [
                offset_m(cx, cy, 400, -400),
                offset_m(cx, cy, 400, 400),
                offset_m(cx, cy, -400, 400),
                offset_m(cx, cy, -400, -400),
                offset_m(cx, cy, 400, -400),
            ],
            "OUTER CORDON",
        )
    )
    items.append(
        phase_line(
            [offset_m(cx, cy, 0, -400), offset_m(cx, cy, 0, 400)],
            "PL HYDE",
        )
    )

    post_overlay(api, token, items, result)
    post_tic(api, token, cx, cy, result)
    return result
