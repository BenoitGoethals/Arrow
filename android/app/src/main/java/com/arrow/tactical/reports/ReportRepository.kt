package com.arrow.tactical.reports

import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.ReportIn
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonObject

class ReportRepository(private val api: ApiClient) {

    suspend fun submit(type: String, payload: JsonObject): Result<Unit> = runCatching {
        val r = api.postJson("/reports", api.json.encodeToString(ReportIn(type, payload)))
        require(r.ok) { "report failed: ${r.code}" }
    }
}
