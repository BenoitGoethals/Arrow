package com.arrow.tactical.alerts

import com.arrow.tactical.auth.TokenStore
import com.arrow.tactical.data.local.AppDatabase
import com.arrow.tactical.data.local.entity.CachedAlertEntity
import com.arrow.tactical.data.local.entity.PendingActionEntity
import com.arrow.tactical.network.AlertDto
import com.arrow.tactical.network.AlertIn
import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.sync.ConnectivityObserver
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.encodeToString

class AlertRepository(
    private val api: ApiClient,
    private val db: AppDatabase,
    private val tokenStore: TokenStore,
    private val connectivity: ConnectivityObserver,
) {
    /** Live alert stream from local cache — always available, even offline/guest. */
    fun observeAlerts(): Flow<List<AlertDto>> =
        db.cachedAlertDao().observeAll().map { list -> list.map { it.toDto() } }

    suspend fun trigger(type: String, lat: Double? = null, lon: Double? = null): Result<AlertDto> = runCatching {
        val localId = -System.currentTimeMillis()
        val payloadJson = api.json.encodeToString(AlertIn(type, latitude = lat, longitude = lon))

        db.cachedAlertDao().insert(
            CachedAlertEntity(id = localId, alertType = type, callsign = "me",
                lat = lat, lon = lon, syncStatus = "pending")
        )

        val token = tokenStore.current()
        if (token.isNullOrBlank()) return@runCatching localAlertDto(localId, type, lat, lon)

        if (connectivity.hasActiveConnection()) {
            val r = api.postJson("/alerts", payloadJson)
            if (r.ok) {
                val dto = api.json.decodeFromString<AlertDto>(r.body)
                db.cachedAlertDao().markSynced(localId)
                return@runCatching dto
            }
        }

        db.pendingActionDao().insert(
            PendingActionEntity(actionType = "POST_JSON", endpoint = "/alerts", payload = payloadJson)
        )
        localAlertDto(localId, type, lat, lon)
    }

    suspend fun list(): Result<List<AlertDto>> = runCatching {
        val token = tokenStore.current()
        if (token.isNullOrBlank() || !connectivity.hasActiveConnection()) {
            return@runCatching emptyList()
        }
        val r = api.get("/alerts")
        if (!r.ok) return@runCatching emptyList()
        val alerts = api.json.decodeFromString<List<AlertDto>>(r.body)
        db.cachedAlertDao().upsertAll(alerts.map { it.toEntity() })
        alerts
    }

    private fun localAlertDto(localId: Long, type: String, lat: Double?, lon: Double?) = AlertDto(
        id = localId.toInt(), type = type, operatorId = -1, latitude = lat, longitude = lon, status = "LOCAL",
    )
}

private fun CachedAlertEntity.toDto() = AlertDto(
    id = id.toInt(), type = alertType, operatorId = -1,
    latitude = lat, longitude = lon, status = syncStatus,
)

private fun AlertDto.toEntity() = CachedAlertEntity(
    id = id.toLong(), alertType = type, callsign = operatorId.toString(),
    lat = latitude, lon = longitude, syncStatus = "synced",
)
