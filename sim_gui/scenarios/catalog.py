"""The ten scenarios surfaced by the GUI, in display order."""

from __future__ import annotations

from sim_gui.scenarios import (
    op_acid_gambit,
    op_anaconda,
    op_barras,
    op_dynamic,
    op_earnest_will,
    op_gothic_serpent,
    op_neptune_spear,
    op_nimrod,
    op_red_wings,
    op_urgent_fury,
    op_ursel,
)

SCENARIOS = [
    op_neptune_spear,
    op_acid_gambit,
    op_urgent_fury,
    op_earnest_will,
    op_anaconda,
    op_gothic_serpent,
    op_red_wings,
    op_barras,
    op_nimrod,
    op_ursel,
    op_dynamic,
]

BY_ID = {mod.META.id: mod for mod in SCENARIOS}
