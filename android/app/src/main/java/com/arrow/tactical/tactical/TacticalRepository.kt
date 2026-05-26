package com.arrow.tactical.tactical

import com.arrow.tactical.auth.TokenStore
import com.arrow.tactical.data.local.AppDatabase
import com.arrow.tactical.data.local.entity.CachedTacticalObjectEntity
import com.arrow.tactical.data.local.entity.PendingActionEntity
import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.OperatorDto
import com.arrow.tactical.network.TacticalObjectDto
import com.arrow.tactical.network.TacticalObjectIn
import com.arrow.tactical.sync.ConnectivityObserver
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.encodeToString

class TacticalRepository(
    private val api: ApiClient,
    private val db: AppDatabase,
    private val tokenStore: TokenStore,
    private val connectivity: ConnectivityObserver,
) {
    // ── Reactive map feed ─────────────────────────────────────────────────────

    /**
     * Hot Flow of tactical objects from the local DB.
     * Always works — offline, guest, or authenticated.
     * MapScreen observes this so new marks appear instantly without a reload.
     */
    fun observeObjects(): Flow<List<TacticalObjectDto>> =
        db.cachedTacticalObjectDao().observeVisible().map { list -> list.map { it.toDto() } }

    // ── List / refresh ────────────────────────────────────────────────────────

    suspend fun listObjects(): Result<List<TacticalObjectDto>> = runCatching {
        val token = tokenStore.current()
        if (token.isNullOrBlank() || !connectivity.hasActiveConnection()) {
            return@runCatching db.cachedTacticalObjectDao().getVisible().map { it.toDto() }
        }
        val r = api.get("/tactical-objects")
        if (!r.ok) return@runCatching db.cachedTacticalObjectDao().getVisible().map { it.toDto() }
        val objects = api.json.decodeFromString<List<TacticalObjectDto>>(r.body)
        db.cachedTacticalObjectDao().upsertAll(objects.map { it.toEntity() })
        objects
    }

    // ── Create ────────────────────────────────────────────────────────────────

    /**
     * Place a tactical object on the map.
     *
     * - Always writes to the local DB first → map updates instantly.
     * - Guest mode: local only, no server call.
     * - Authenticated + online: sent immediately; local row updated with server id.
     * - Authenticated + offline: queued in pending_actions; SyncManager sends it
     *   on reconnect and updates the local id to the server-assigned one.
     */
    suspend fun mark(payload: TacticalObjectIn): Result<TacticalObjectDto> = runCatching {
        val localId = -System.currentTimeMillis()
        val payloadJson = api.json.encodeToString(payload)

        // Persist locally — the map Flow fires immediately.
        db.cachedTacticalObjectDao().upsert(
            CachedTacticalObjectEntity(
                id          = localId,
                type        = payload.type,
                symbolCode  = payload.symbolCode,
                latitude    = payload.latitude,
                longitude   = payload.longitude,
                notes       = payload.notes,
                visibility  = payload.visibility,
                affiliation = payload.affiliation,
                syncStatus  = "pending",
            )
        )

        val token = tokenStore.current()
        if (token.isNullOrBlank()) {
            return@runCatching localDto(localId, payload)
        }

        if (connectivity.hasActiveConnection()) {
            val r = api.postJson("/tactical-objects", payloadJson)
            if (r.ok) {
                val dto = api.json.decodeFromString<TacticalObjectDto>(r.body)
                db.cachedTacticalObjectDao().markSynced(localId, dto.id.toLong())
                return@runCatching dto
            }
        }

        // Offline — queue and return local DTO.
        db.pendingActionDao().insert(
            PendingActionEntity(
                actionType = "POST_JSON",
                endpoint   = "/tactical-objects",
                payload    = payloadJson,
            )
        )
        localDto(localId, payload)
    }

    // ── Delete ────────────────────────────────────────────────────────────────

    suspend fun delete(id: Int): Result<Unit> = runCatching {
        val longId = id.toLong()
        val token = tokenStore.current()

        if (token.isNullOrBlank() || longId < 0) {
            db.cachedTacticalObjectDao().deleteById(longId)
            return@runCatching
        }

        if (connectivity.hasActiveConnection()) {
            val r = api.delete("/tactical-objects/$id")
            if (r.ok) {
                db.cachedTacticalObjectDao().deleteById(longId)
                return@runCatching
            }
        }

        // Offline — mark as delete-pending; SyncManager sends DELETE on reconnect.
        db.cachedTacticalObjectDao().markDeletePending(longId)
        db.pendingActionDao().insert(
            PendingActionEntity(
                actionType = "DELETE",
                endpoint   = "/tactical-objects/$id",
            )
        )
    }

    /** Clear stale synced objects then fetch fresh data for the current mission. */
    suspend fun clearAndReload(): Result<List<TacticalObjectDto>> {
        db.cachedTacticalObjectDao().clearSynced()
        return listObjects()
    }

    // ── Misc ──────────────────────────────────────────────────────────────────

    suspend fun listOperators(): Result<List<OperatorDto>> = runCatching {
        val r = api.get("/operators")
        require(r.ok) { "HTTP ${r.code}" }
        api.json.decodeFromString<List<OperatorDto>>(r.body)
    }

    suspend fun getHierarchyJson(): Result<String> = runCatching {
        val r = api.get("/hierarchy")
        require(r.ok) { "hierarchy failed: ${r.code}" }
        r.body
    }

    private fun localDto(localId: Long, p: TacticalObjectIn) = TacticalObjectDto(
        id          = localId.toInt(),
        type        = p.type,
        symbolCode  = p.symbolCode,
        latitude    = p.latitude,
        longitude   = p.longitude,
        notes       = p.notes,
        visibility  = p.visibility,
        affiliation = p.affiliation,
        createdBy   = -1,
    )
}

// ── Mappers ───────────────────────────────────────────────────────────────────

private fun CachedTacticalObjectEntity.toDto() = TacticalObjectDto(
    id          = id.toInt(),
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
