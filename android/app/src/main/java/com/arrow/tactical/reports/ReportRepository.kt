package com.arrow.tactical.reports

import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.ReportDto
import com.arrow.tactical.network.ReportIn
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonObject

class ReportRepository(private val api: ApiClient) {

    suspend fun submit(type: String, payload: JsonObject): Result<ReportDto> = runCatching {
        val r = api.postJson("/reports", api.json.encodeToString(ReportIn(type, payload)))
        require(r.ok) { "report failed: ${r.code}" }
        api.json.decodeFromString<ReportDto>(r.body)
    }

    suspend fun list(): Result<List<ReportDto>> = runCatching {
        val r = api.get("/reports")
        require(r.ok) { "list reports failed: ${r.code}" }
        api.json.decodeFromString<List<ReportDto>>(r.body)
    }
}
