package com.arrow.tactical.layers

import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.LayerImportResult

/**
 * Portable layer export/import — overlays, KML layers, OSINT boards — via the
 * backend `/layers` API. Envelopes are passed around as raw JSON strings so the
 * UI can hand them to the Storage Access Framework (file picker) unchanged.
 */
class LayerRepository(private val api: ApiClient) {

    /** GET the portable export envelope (raw JSON) for a layer. */
    suspend fun exportLayer(kind: String, sourceId: Int): Result<String> = runCatching {
        val seg = SEGMENTS[kind.uppercase()] ?: error("Unknown layer kind $kind")
        val r = api.get("/layers/$seg/$sourceId/export")
        if (!r.ok) error("HTTP ${r.code}: ${r.body.take(120)}")
        r.body
    }

    /** POST an export envelope (raw JSON) to clone it into the active mission. */
    suspend fun importLayer(envelopeJson: String): Result<LayerImportResult> = runCatching {
        val r = api.postJson("/layers/import", envelopeJson)
        if (!r.ok) error("HTTP ${r.code}: ${r.body.take(160)}")
        api.json.decodeFromString<LayerImportResult>(r.body)
    }

    companion object {
        private val SEGMENTS = mapOf(
            "OVERLAY" to "overlays",
            "KML" to "kml",
            "OSINT" to "osint",
        )
    }
}
