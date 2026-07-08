package com.arrow.tactical.sync

import android.util.Log
import com.arrow.tactical.auth.TokenStore
import com.arrow.tactical.data.local.AppDatabase
import com.arrow.tactical.data.local.entity.CachedAlertEntity
import com.arrow.tactical.data.local.entity.CachedMessageEntity
import com.arrow.tactical.data.local.entity.CachedOperatorEntity
import com.arrow.tactical.data.local.entity.CachedReportEntity
import com.arrow.tactical.data.local.entity.CachedTacticalObjectEntity
import com.arrow.tactical.network.AlertDto
import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.MessageDto
import com.arrow.tactical.network.OperatorDto
import com.arrow.tactical.network.ReportDto
import com.arrow.tactical.network.TacticalObjectDto
import com.arrow.tactical.strike.StrikePackageRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.launch

private const val TAG = "SyncManager"
private const val MAX_RETRIES = 10

/**
 * Drains the pending-action queue and refreshes local caches.
 *
 * Called:
 *  - On login (immediately after token is stored)
 *  - When connectivity is restored (via ConnectivityObserver)
 *  - By SyncWorker on a 15-minute WorkManager schedule
 */
class SyncManager(
    private val db: AppDatabase,
    private val api: ApiClient,
    private val tokenStore: TokenStore,
    private val connectivity: ConnectivityObserver,
    private val strikePackageRepository: StrikePackageRepository? = null,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** Start watching connectivity; trigger sync whenever we come back online and are authenticated. */
    fun startAutoSync() {
        scope.launch {
            connectivity.isOnline
                .distinctUntilChanged()
                .filter { it }
                .collect {
                    val token = tokenStore.current()
                    if (!token.isNullOrBlank()) sync()
                }
        }
    }

    /** Full sync: push pending queue then pull fresh server data. */
    suspend fun sync() {
        val token = tokenStore.current()
        if (token.isNullOrBlank() || !connectivity.hasActiveConnection()) return

        pushPendingActions()
        pullServerData()
    }

    // ── Push ─────────────────────────────────────────────────────────────────

    private suspend fun pushPendingActions() {
        val pending = db.pendingActionDao().getAllPending()
        if (pending.isEmpty()) return
        Log.i(TAG, "Pushing ${pending.size} pending action(s)")

        for (action in pending) {
            if (action.retryCount >= MAX_RETRIES) {
                db.pendingActionDao().markFailed(action.id)
                Log.w(TAG, "Action ${action.id} (${action.endpoint}) exceeded max retries — marked FAILED")
                continue
            }
            try {
                val r = when (action.actionType) {
                    "POST_JSON"  -> api.postJson(action.endpoint, action.payload)
                    "POST_XML"   -> api.postXml(action.endpoint, action.payload)
                    "PATCH_JSON" -> api.patchJson(action.endpoint, action.payload)
                    "DELETE"     -> api.delete(action.endpoint)
                    else         -> { db.pendingActionDao().markFailed(action.id); continue }
                }
                when {
                    r.ok            -> { db.pendingActionDao().delete(action); Log.d(TAG, "Synced action ${action.id}") }
                    r.code in 400..499 -> { db.pendingActionDao().markFailed(action.id); Log.w(TAG, "Action ${action.id} rejected (${r.code}) — FAILED") }
                    else            -> { db.pendingActionDao().incrementRetry(action.id); Log.w(TAG, "Action ${action.id} server error ${r.code} — will retry") }
                }
            } catch (e: Exception) {
                db.pendingActionDao().incrementRetry(action.id)
                Log.w(TAG, "Action ${action.id} network error — will retry: $e")
            }
        }
    }

    // ── Pull ─────────────────────────────────────────────────────────────────

    private suspend fun pullServerData() {
        pullOperators()
        pullTacticalObjects()
        pullMessages()
        pullReports()
        pullAlerts()
        pullStrikePackages()
    }

    private suspend fun pullStrikePackages() = runCatching {
        strikePackageRepository?.syncAll()
        Log.d(TAG, "Pulled strike packages")
    }

    private suspend fun pullOperators() = runCatching {
        val r = api.get("/tracking/live")
        if (!r.ok) return@runCatching
        val operators = api.json.decodeFromString<List<OperatorDto>>(r.body)
        db.cachedOperatorDao().upsertAll(operators.map { it.toEntity() })
        Log.d(TAG, "Pulled ${operators.size} operators")
    }

    private suspend fun pullMessages() = runCatching {
        val r = api.get("/messages")
        if (!r.ok) return@runCatching
        val messages = api.json.decodeFromString<List<MessageDto>>(r.body)
        db.cachedMessageDao().upsertAll(messages.map { it.toEntity() })
        Log.d(TAG, "Pulled ${messages.size} messages")
    }

    private suspend fun pullReports() = runCatching {
        val r = api.get("/reports")
        if (!r.ok) return@runCatching
        val reports = api.json.decodeFromString<List<ReportDto>>(r.body)
        db.cachedReportDao().upsertAll(reports.map { it.toEntity() })
        Log.d(TAG, "Pulled ${reports.size} reports")
    }

    private suspend fun pullAlerts() = runCatching {
        val r = api.get("/alerts")
        if (!r.ok) return@runCatching
        val alerts = api.json.decodeFromString<List<AlertDto>>(r.body)
        db.cachedAlertDao().upsertAll(alerts.map { it.toEntity() })
        Log.d(TAG, "Pulled ${alerts.size} alerts")
    }

    private suspend fun pullTacticalObjects() = runCatching {
        val r = api.get("/tactical-objects")
        if (!r.ok) return@runCatching
        val objects = api.json.decodeFromString<List<TacticalObjectDto>>(r.body)
        db.cachedTacticalObjectDao().upsertAll(objects.map { it.toEntity() })
        // Remove any delete-pending rows that the server already confirms are gone.
        db.cachedTacticalObjectDao().purgeConfirmedDeletes()
        Log.d(TAG, "Pulled ${objects.size} tactical objects")
    }
}

// ── DTO → Entity mappers ───────────────────────────────────────────────────

private fun OperatorDto.toEntity() = CachedOperatorEntity(
    id = id, callsign = callsign, role = role,
    lat = latitude, lon = longitude, altitude = altitude,
    speed = null, course = null, team = teamId?.toString(),
    online = online,
)

private fun MessageDto.toEntity() = CachedMessageEntity(
    id = id.toLong(),
    content = content,
    senderCallsign = senderId.toString(),
    messageType = messageType,
    receiverId = receiverId,
    groupId = groupId,
    syncStatus = "synced",
    source = source,
)

private fun ReportDto.toEntity() = CachedReportEntity(
    id = id.toLong(),
    reportType = type,
    payloadJson = payload,
    syncStatus = "synced",
)

private fun AlertDto.toEntity() = CachedAlertEntity(
    id = id.toLong(),
    alertType = type,
    callsign = operatorId.toString(),
    lat = latitude, lon = longitude,
    syncStatus = "synced",
)

private fun TacticalObjectDto.toEntity() = CachedTacticalObjectEntity(
    id          = id.toLong(),
    type        = type,
    symbolCode  = symbolCode,
    latitude    = latitude,
    longitude   = longitude,
    notes       = notes,
    visibility  = visibility,
    affiliation = affiliation,
    rotation    = rotation,
    geometry    = geometry,
    echelon     = echelon,
    createdBy   = createdBy,
    syncStatus  = "synced",
)
