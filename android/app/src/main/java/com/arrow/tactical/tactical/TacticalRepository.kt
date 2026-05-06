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
}
