package com.arrow.tactical.tactical

import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.OperatorDto
import com.arrow.tactical.network.TacticalObjectDto
import com.arrow.tactical.network.TacticalObjectIn
import kotlinx.serialization.encodeToString

class TacticalRepository(private val api: ApiClient) {

    suspend fun listOperators(): Result<List<OperatorDto>> = runCatching {
        val r = api.get("/operators")
        require(r.ok) { "HTTP ${r.code}" }
        api.json.decodeFromString<List<OperatorDto>>(r.body)
    }

    suspend fun listObjects(): Result<List<TacticalObjectDto>> = runCatching {
        val r = api.get("/tactical-objects")
        require(r.ok) { "HTTP ${r.code}" }
        api.json.decodeFromString<List<TacticalObjectDto>>(r.body)
    }

    suspend fun mark(payload: TacticalObjectIn): Result<TacticalObjectDto> = runCatching {
        val r = api.postJson("/tactical-objects", api.json.encodeToString(payload))
        require(r.ok) { "mark failed: ${r.code} ${r.body}" }
        api.json.decodeFromString<TacticalObjectDto>(r.body)
    }

    suspend fun delete(id: Int): Result<Unit> = runCatching {
        val r = api.delete("/tactical-objects/$id")
        require(r.ok) { "delete failed: ${r.code}" }
    }

    suspend fun getHierarchyJson(): Result<String> = runCatching {
        val r = api.get("/hierarchy")
        require(r.ok) { "hierarchy failed: ${r.code}" }
        r.body
    }
}

/** Catalogue of common enemy / object types with their MIL-STD-2525 SIDC code. */
enum class EnemyType(val label: String, val sidc: String, val abbr: String) {
    INFANTRY("Infantry",              "SHGPUCI-----", "INF"),
    ARMOR("Armor",                    "SHGPUCA-----", "ARM"),
    MECHANIZED("Mechanized infantry", "SHGPUCIZ----", "MECH"),
    ARTILLERY("Artillery",            "SHGPUCF-----", "ARTY"),
    AIR_DEFENSE("Air defense",        "SHGPUCD-----", "AD"),
    RECON("Reconnaissance",           "SHGPUCR-----", "RCN"),
    VEHICLE("Vehicle",                "SHGPEV------", "VEH"),
    SNIPER("Sniper",                  "SHGPUCIS----", "SNP"),
    UNKNOWN("Unknown contact",        "SUGPU-------", "?"),
    POI("Point of interest",          "SNGPI-------", "POI"),
    ;

    companion object {
        /**
         * Resolve a tactical object's actual unit type from its DTO. The web /
         * simulator usually sends ``type="ENEMY"`` with the real unit encoded in
         * the SIDC (e.g. ``SHGPUCI-----`` for hostile combat infantry), so the
         * symbol_code is the authoritative source. Falls back to the textual
         * type if no SIDC is present.
         */
        fun resolve(type: String, symbolCode: String?): EnemyType {
            fromSidc(symbolCode)?.let { return it }
            return runCatching { valueOf(type.uppercase()) }.getOrElse { UNKNOWN }
        }

        /**
         * Map a 15-char MIL-STD-2525C SIDC to one of our enum values. Positions
         * 4-9 hold the function modifier; the leading ``U`` (unit) is stripped
         * before matching. Returns null when the SIDC is empty / too short.
         */
        fun fromSidc(sidc: String?): EnemyType? {
            if (sidc.isNullOrBlank() || sidc.length < 5) return null
            // pos 4..9 = function modifier; uppercase to be safe
            val fn = sidc.substring(4, minOf(sidc.length, 10)).uppercase()
            // Order matters — longer prefixes first ("UCIZ", "UCIS" before "UCI").
            return when {
                fn.startsWith("UCIZ") -> MECHANIZED
                fn.startsWith("UCIS") -> SNIPER
                fn.startsWith("UCI")  -> INFANTRY
                fn.startsWith("UCA")  -> ARMOR
                fn.startsWith("UCF")  -> ARTILLERY
                fn.startsWith("UCD")  -> AIR_DEFENSE
                fn.startsWith("UCR")  -> RECON
                fn.startsWith("EV")   -> VEHICLE
                fn.startsWith("I")    -> POI            // infrastructure
                else                   -> null
            }
        }
    }
}
