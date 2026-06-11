package com.arrow.tactical.tactical

enum class FriendlyType(val label: String, val sidc: String) {
    INFANTRY    ("Infantry",     "SFGPUCI----E"),
    ARMOR       ("Armor",        "SFGPUCA----E"),
    MECHANIZED  ("Mechanized",   "SFGPUCIZ---E"),
    ARTILLERY   ("Artillery",    "SFGPUCF----E"),
    AIR_DEFENSE ("Air Defense",  "SFGPUCM----E"),
    RECON       ("Recon",        "SFGPUCR----E"),
    COMMAND_POST("Command Post", "SFGPUCC----E"),
    UNKNOWN     ("Unknown",      "SFGPUZ-----E"),
}
