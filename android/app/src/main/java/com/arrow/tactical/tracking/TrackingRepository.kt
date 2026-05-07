package com.arrow.tactical.tracking

import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.CotProtocol
import com.arrow.tactical.network.OperatorDto
import com.arrow.tactical.network.PositionPayload
import kotlinx.serialization.encodeToString

class TrackingRepository(private val api: ApiClient) {

    /**
     * Push a CoT-formatted position update to the backend.
     * This is the primary channel for Android → backend position reporting
     * and is MIL-STD-2525C conformant.
     */
    suspend fun pushPositionCot(
        callsign: String,
        role:     String,
        lat:      Double,
        lon:      Double,
        hae:      Double  = 0.0,
        speed:    Double  = 0.0,
        course:   Double  = 0.0,
    ): Result<Unit> = runCatching {
        val xml = CotProtocol.buildPositionEvent(
            callsign = callsign,
            role     = role,
            lat      = lat,
            lon      = lon,
            hae      = hae,
            speed    = speed,
            course   = course,
        )
        val r = api.postXml("/cot", xml)
        require(r.ok) { "CoT position failed: ${r.code}" }
    }

    /** Legacy JSON position push — kept for internal/fallback use. */
    suspend fun pushPosition(lat: Double, lon: Double, alt: Double?): Result<OperatorDto> = runCatching {
        val r = api.postJson("/tracking/position", api.json.encodeToString(PositionPayload(lat, lon, alt)))
        require(r.ok) { "position failed: ${r.code}" }
        api.json.decodeFromString<OperatorDto>(r.body)
    }

    suspend fun liveOperators(): Result<List<OperatorDto>> = runCatching {
        val r = api.get("/tracking/live")
        require(r.ok) { "live failed: ${r.code}" }
        api.json.decodeFromString<List<OperatorDto>>(r.body)
    }
}
