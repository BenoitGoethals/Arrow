package com.arrow.tactical.alerts

import com.arrow.tactical.network.AlertDto
import com.arrow.tactical.network.AlertIn
import com.arrow.tactical.network.ApiClient
import kotlinx.serialization.encodeToString

class AlertRepository(private val api: ApiClient) {

    suspend fun trigger(type: String, lat: Double? = null, lon: Double? = null): Result<AlertDto> = runCatching {
        val r = api.postJson("/alerts", api.json.encodeToString(AlertIn(type, lat, lon)))
        require(r.ok) { "alert failed: ${r.code}" }
        api.json.decodeFromString<AlertDto>(r.body)
    }

    suspend fun list(): Result<List<AlertDto>> = runCatching {
        val r = api.get("/alerts")
        require(r.ok) { "alerts list failed: ${r.code}" }
        api.json.decodeFromString<List<AlertDto>>(r.body)
    }
}
