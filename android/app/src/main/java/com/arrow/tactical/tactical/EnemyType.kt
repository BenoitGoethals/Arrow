package com.arrow.tactical.tactical

enum class EnemyType(val label: String, val sidc: String) {
    INFANTRY   ("Infantry",    "SHGPUCI----E"),
    ARMOR      ("Armor",       "SHGPUCA----E"),
    MECHANIZED ("Mechanized",  "SHGPUCIZ---E"),
    ARTILLERY  ("Artillery",   "SHGPUCF----E"),
    AIR_DEFENSE("Air Defense", "SHGPUCM----E"),
    RECON      ("Recon",       "SHGPUCR----E"),
    SNIPER     ("Sniper",      "SHGPUCS----E"),
    VEHICLE    ("Vehicle",     "SHGPUCV----E"),
    UNKNOWN    ("Unknown",     "SHGPUZ-----E"),
    POI        ("POI",         "GFGPGPPK---E"),
    ;

    companion object {
        fun resolve(type: String, symbolCode: String): EnemyType {
            entries.firstOrNull { it.name == type }?.let { return it }
            entries.firstOrNull { it.sidc == symbolCode }?.let { return it }
            return UNKNOWN
        }
    }
}
