package com.arrow.tactical.overlays

import com.arrow.tactical.network.ApiClient
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

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
}
