package com.arrow.tactical.tracking

import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.OperatorDto
import com.arrow.tactical.network.PositionPayload
import kotlinx.serialization.encodeToString

class TrackingRepository(private val api: ApiClient) {

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
