"""Operation NEPTUNE SPEAR — Abbottabad raid (2 May 2011), SEAL Team Six.

Two MH-60 Stealth Hawks insert a SEAL assault force onto the Bin Laden
compound; QRF stands off; exfil via CH-47. Real coordinates centred on the
Bilal Town compound in Abbottabad, Pakistan.
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
    lz,
    objective,
    obj_area,
    offset_m,
    phase_line,
    poi,
    pz,
)

META = ScenarioMeta(
    id="neptune_spear",
    name="Operation NEPTUNE SPEAR",
    mission_type="Direct Action (Air Assault)",
    real_world="Abbottabad, 2 May 2011 — SEAL Team Six / DEVGRU",
    aor_center=(34.1693, 73.2424),
    map_zoom=15,
    summary=(
        "Two MH-60 Stealth Hawks fast-rope a SEAL assault force onto a fortified "
        "compound; QRF holds north; exfil via CH-47 to PZ JALALABAD."
    ),
)

VEHICLE_FLAVOR = "airborne"


def inject(api: Api, token: str, state: HierarchyState) -> InjectResult:
    result = InjectResult()
    cx, cy = META.aor_center

    items: list[dict] = []

    items.append(obj_area(cx, cy, "OBJ GERONIMO — TGT compound", radius_m=80.0))
    items.append(objective(cx, cy, "GERONIMO", radius_m=40.0))

    lz1 = offset_m(cx, cy, 60, -20)
    lz2 = offset_m(cx, cy, -50, 70)
    items.append(lz(*lz1, "ICE-1"))
    items.append(lz(*lz2, "ICE-2"))
    items.append(pz(*offset_m(cx, cy, 350, 250), "JALALABAD"))

    orp = offset_m(cx, cy, 500, -350)
    items.append(poi(*orp, "ORP NORTH", SIDC["ORP"]))
    items.append(poi(*offset_m(cx, cy, -120, -120), "CCP", SIDC["CCP"]))

    # ── enemy laydown — bodyguards + lookout positions
    items.append(
        enemy(*offset_m(cx, cy, 20, 0), "TGT inner security", SIDC["ENEMY_INF"])
    )
    items.append(enemy(*offset_m(cx, cy, -25, 30), "Guesthouse OP", SIDC["ENEMY_INF"]))
    items.append(
        enemy(*offset_m(cx, cy, 0, 60), "Rooftop sentry", SIDC["ENEMY_SNIPER"])
    )
    items.append(
        enemy(*offset_m(cx, cy, -90, -90), "Outer wall patrol", SIDC["ENEMY_INF"])
    )

    # ── control measures
    items.append(
        boundary(
            [
                offset_m(cx, cy, 250, -250),
                offset_m(cx, cy, 250, 250),
                offset_m(cx, cy, -250, 250),
                offset_m(cx, cy, -250, -250),
                offset_m(cx, cy, 250, -250),
            ],
            "BDY AO MOUNTAIN",
        )
    )
    items.append(
        phase_line(
            [offset_m(cx, cy, -200, -200), offset_m(cx, cy, -200, 200)],
            "PL GERONIMO",
        )
    )
    items.append(atk_axis(*offset_m(cx, cy, 80, -40), "AXIS RAIDER", rotation_deg=135))

    post_overlay(api, token, items, result)

    # Seed TIC at the compound — assault is hot from minute one.
    post_tic(api, token, cx, cy, result)
    return result
