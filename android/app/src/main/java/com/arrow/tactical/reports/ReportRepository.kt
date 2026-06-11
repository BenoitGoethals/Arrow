package com.arrow.tactical.reports

import com.arrow.tactical.auth.TokenStore
import com.arrow.tactical.data.local.AppDatabase
import com.arrow.tactical.data.local.entity.CachedReportEntity
import com.arrow.tactical.data.local.entity.PendingActionEntity
import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.ReportDto
import com.arrow.tactical.network.ReportIn
import com.arrow.tactical.sync.ConnectivityObserver
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

class ReportRepository(
    private val api: ApiClient,
    private val db: AppDatabase,
    private val tokenStore: TokenStore,
    private val connectivity: ConnectivityObserver,
) {
    /** Observe all reports from the local cache — always available. */
    fun observeReports(): Flow<List<ReportDto>> =
        db.cachedReportDao().observeAll().map { list -> list.map { it.toDto() } }

    /**
     * Submit a report.
     *
     * Always saved locally first. Sent to server immediately if online + authenticated;
     * otherwise queued for the next sync.
     */
    suspend fun submit(type: String, payload: JsonObject): Result<ReportDto> = runCatching {
        val localId = -System.currentTimeMillis()
        val payloadJson = api.json.encodeToString(payload)
        val bodyJson = api.json.encodeToString(ReportIn(type, payload))

        db.cachedReportDao().insert(
            CachedReportEntity(id = localId, reportType = type, payloadJson = payloadJson, syncStatus = "pending")
        )

        val token = tokenStore.current()
        if (token.isNullOrBlank()) {
            return@runCatching localReportDto(localId, type, payloadJson)
        }

        if (connectivity.hasActiveConnection()) {
            val r = api.postJson("/reports", bodyJson)
            if (r.ok) {
                val dto = api.json.decodeFromString<ReportDto>(r.body)
                db.cachedReportDao().markSynced(localId, dto.id.toLong())
                return@runCatching dto
            }
        }

        db.pendingActionDao().insert(
            PendingActionEntity(actionType = "POST_JSON", endpoint = "/reports", payload = bodyJson)
        )
        localReportDto(localId, type, payloadJson)
    }

    suspend fun list(): Result<List<ReportDto>> = runCatching {
        val token = tokenStore.current()
        if (token.isNullOrBlank() || !connectivity.hasActiveConnection()) {
            return@runCatching db.cachedReportDao().getLatest().map { it.toDto() }
        }
        val r = api.get("/reports")
        if (!r.ok) return@runCatching db.cachedReportDao().getLatest().map { it.toDto() }
        val reports = api.json.decodeFromString<List<ReportDto>>(r.body)
        db.cachedReportDao().upsertAll(reports.map { it.toEntity() })
        reports
    }

    suspend fun submitDroneSpot(
        latitude: Double, longitude: Double, droneType: String,
        altitudeM: Double?, directionDeg: Double?, speedKts: Double?,
        behavior: String, notes: String,
    ): Result<ReportDto> {
        val body = buildJsonObject {
            put("latitude", latitude); put("longitude", longitude)
            put("drone_type", droneType)
            altitudeM?.let { put("altitude_m", it) }
            directionDeg?.let { put("direction_deg", it) }
            speedKts?.let { put("speed_kts", it) }
            put("behavior", behavior); put("notes", notes)
        }
        val localId = -System.currentTimeMillis()
        val bodyJson = api.json.encodeToString(JsonObject.serializer(), body)

        return runCatching {
            db.cachedReportDao().insert(
                CachedReportEntity(id = localId, reportType = "DRONE_SPOT",
                    payloadJson = bodyJson, syncStatus = "pending")
            )

            val token = tokenStore.current()
            if (token.isNullOrBlank()) return@runCatching localReportDto(localId, "DRONE_SPOT", bodyJson)

            if (connectivity.hasActiveConnection()) {
                val r = api.postJson("/reports/drone-spot", bodyJson)
                if (r.ok) {
                    val dto = api.json.decodeFromString<ReportDto>(r.body)
                    db.cachedReportDao().markSynced(localId, dto.id.toLong())
                    return@runCatching dto
                }
            }
            db.pendingActionDao().insert(
                PendingActionEntity(actionType = "POST_JSON", endpoint = "/reports/drone-spot", payload = bodyJson)
            )
            localReportDto(localId, "DRONE_SPOT", bodyJson)
        }
    }

    private fun localReportDto(localId: Long, type: String, payloadJson: String) = ReportDto(
        id = localId.toInt(), operatorId = -1, type = type, payload = payloadJson,
    )
}

private fun CachedReportEntity.toDto() = ReportDto(
    id = id.toInt(), operatorId = -1, type = reportType, payload = payloadJson,
)

private fun ReportDto.toEntity() = CachedReportEntity(
    id = id.toLong(), reportType = type, payloadJson = payload, syncStatus = "synced",
)
