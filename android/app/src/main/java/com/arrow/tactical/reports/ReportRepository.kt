package com.arrow.tactical.reports

import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.ReportDto
import com.arrow.tactical.network.ReportIn
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

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

    /**
     * Submit a drone-spot observation. Backend stores a DRONE_SPOT report **and**
     * raises a DRONE_SPOTTED alert so the web/desktop alert subsystems light up
     * automatically.
     */
    suspend fun submitDroneSpot(
        latitude:      Double,
        longitude:     Double,
        droneType:     String,
        altitudeM:     Double?,
        directionDeg:  Double?,
        speedKts:      Double?,
        behavior:      String,
        notes:         String,
    ): Result<ReportDto> = runCatching {
        val body = buildJsonObject {
            put("latitude",      latitude)
            put("longitude",     longitude)
            put("drone_type",    droneType)
            altitudeM?.let     { put("altitude_m",    it) }
            directionDeg?.let  { put("direction_deg", it) }
            speedKts?.let      { put("speed_kts",     it) }
            put("behavior",      behavior)
            put("notes",         notes)
        }
        val r = api.postJson("/reports/drone-spot", api.json.encodeToString(JsonObject.serializer(), body))
        require(r.ok) { "drone-spot failed: ${r.code} ${r.body.take(200)}" }
        api.json.decodeFromString<ReportDto>(r.body)
    }
}
