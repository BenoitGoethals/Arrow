package com.arrow.tactical.map

import com.arrow.tactical.network.ApiClient
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * Backend-driven catalogue of base map sources. Mirrors `backend.map.router.MapSource`.
 *
 * `urlTemplate` is either:
 *  - an absolute URL (built-in OSM) → used verbatim by Leaflet, ignored on Android
 *    in favour of [BackendTileSource.OSM_DEFAULT]; OR
 *  - a backend path "/map/tiles/{name}/{z}/{x}/{y}.{ext}" → consumed by
 *    [BackendTileSource] using `name` and `format`.
 */
@Serializable
data class MapSourceDto(
    val name: String,
    val title: String,
    val type: String,
    val format: String,
    val min_zoom: Int,
    val max_zoom: Int,
    val bounds: List<Double>? = null,
    val center: List<Double>? = null,
    val attribution: String? = null,
    val url_template: String,
    val is_default: Boolean = false,
)

class MapSourceRepository(private val api: ApiClient) {

    /** Fetch the source list. Returns an empty list on any failure — callers fall back to OSM. */
    suspend fun list(): List<MapSourceDto> = runCatching {
        val resp = api.get("/map/sources")
        if (!resp.ok) return emptyList()
        Json { ignoreUnknownKeys = true; coerceInputValues = true }
            .decodeFromString<List<MapSourceDto>>(resp.body)
    }.getOrDefault(emptyList())
}
