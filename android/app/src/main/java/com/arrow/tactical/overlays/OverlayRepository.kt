package com.arrow.tactical.overlays

import com.arrow.tactical.network.ApiClient
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray

/** Matches the OverlayOut schema from backend/overlays/router.py. */
@Serializable
data class OverlayDto(
    val id: Int,
    val name: String,
    val description: String = "",
    @SerialName("created_by") val createdBy: Int = 0,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
    @SerialName("object_ids") val objectIds: List<Int> = emptyList(),
)

class OverlayRepository(private val api: ApiClient) {

    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }

    suspend fun list(): Result<List<OverlayDto>> = runCatching {
        val r = api.get("/overlays")
        if (!r.ok) error("HTTP ${r.code}")
        json.decodeFromString<List<OverlayDto>>(r.body)
    }

    suspend fun create(name: String, description: String, objectIds: List<Int>): Result<OverlayDto> =
        runCatching {
            val body = buildJsonObject {
                put("name", name)
                put("description", description)
                putJsonArray("object_ids") { objectIds.forEach { add(it) } }
            }
            val r = api.postJson("/overlays", body.toString())
            if (!r.ok) error("HTTP ${r.code}: ${r.body.take(120)}")
            json.decodeFromString<OverlayDto>(r.body)
        }

    suspend fun setObjectIds(id: Int, objectIds: List<Int>): Result<OverlayDto> = runCatching {
        val body = buildJsonObject {
            putJsonArray("object_ids") { objectIds.forEach { add(it) } }
        }
        val r = api.patchJson("/overlays/$id", body.toString())
        if (!r.ok) error("HTTP ${r.code}: ${r.body.take(120)}")
        json.decodeFromString<OverlayDto>(r.body)
    }

    suspend fun delete(id: Int): Result<Unit> = runCatching {
        val r = api.delete("/overlays/$id")
        if (!r.ok) error("HTTP ${r.code}")
    }
}
