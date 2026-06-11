package com.arrow.tactical.tracking

import com.arrow.tactical.auth.TokenStore
import com.arrow.tactical.data.local.AppDatabase
import com.arrow.tactical.data.local.entity.CachedOperatorEntity
import com.arrow.tactical.data.local.entity.PendingActionEntity
import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.CotProtocol
import com.arrow.tactical.network.OperatorDto
import com.arrow.tactical.network.PositionPayload
import com.arrow.tactical.sync.ConnectivityObserver
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.encodeToString

class TrackingRepository(
    private val api: ApiClient,
    private val db: AppDatabase,
    private val tokenStore: TokenStore,
    private val connectivity: ConnectivityObserver,
) {
    /** Live operator list from the local cache (always works, even offline/guest). */
    fun observeOperators(): Flow<List<CachedOperatorEntity>> =
        db.cachedOperatorDao().observeAll()

    /**
     * Push a CoT position update.
     *
     * - Guest (no token): position is only recorded in the local DB.
     * - Authenticated + online: send to server; also update local cache.
     * - Authenticated + offline: enqueue for later sync; update local cache.
     */
    suspend fun pushPositionCot(
        callsign: String,
        role: String,
        lat: Double,
        lon: Double,
        hae: Double = 0.0,
        speed: Double = 0.0,
        course: Double = 0.0,
        localOperatorId: Int = -1,
    ): Result<Unit> = runCatching {
        val xml = CotProtocol.buildPositionEvent(
            callsign = callsign, role = role,
            lat = lat, lon = lon, hae = hae, speed = speed, course = course,
        )

        // Always update local cache so the map shows own position instantly.
        db.cachedOperatorDao().upsert(
            CachedOperatorEntity(
                id = localOperatorId, callsign = callsign, role = role,
                lat = lat, lon = lon, altitude = hae, speed = speed, course = course,
                team = null, online = true,
            )
        )

        val token = tokenStore.current()
        if (token.isNullOrBlank()) return@runCatching  // guest — local only

        if (connectivity.hasActiveConnection()) {
            val r = api.postXml("/cot", xml)
            if (!r.ok) {
                // Server error — queue so we don't silently drop the position
                enqueueCot(xml)
            }
        } else {
            enqueueCot(xml)
        }
    }

    /** JSON fallback (called by LocationService when CoT fails). */
    suspend fun pushPosition(lat: Double, lon: Double, alt: Double?): Result<OperatorDto> = runCatching {
        val token = tokenStore.current()
        if (token.isNullOrBlank()) return@runCatching dummyDto(lat, lon, alt)

        if (connectivity.hasActiveConnection()) {
            val r = api.postJson("/tracking/position", api.json.encodeToString(PositionPayload(lat, lon, alt)))
            if (r.ok) return@runCatching api.json.decodeFromString<OperatorDto>(r.body)
        }

        // Offline — queue the position update
        db.pendingActionDao().insert(
            PendingActionEntity(
                actionType = "POST_JSON",
                endpoint = "/tracking/position",
                payload = api.json.encodeToString(PositionPayload(lat, lon, alt)),
            )
        )
        dummyDto(lat, lon, alt)
    }

    suspend fun liveOperators(): Result<List<OperatorDto>> = runCatching {
        val token = tokenStore.current()
        if (token.isNullOrBlank() || !connectivity.hasActiveConnection()) {
            // Return local cache as DTOs
            return@runCatching db.cachedOperatorDao().getAll().map { it.toDto() }
        }
        val r = api.get("/tracking/live")
        if (!r.ok) return@runCatching db.cachedOperatorDao().getAll().map { it.toDto() }
        val live = api.json.decodeFromString<List<OperatorDto>>(r.body)
        db.cachedOperatorDao().upsertAll(live.map { op ->
            CachedOperatorEntity(
                id = op.id, callsign = op.callsign, role = op.role,
                lat = op.latitude, lon = op.longitude, altitude = op.altitude,
                speed = null, course = null, team = op.teamId?.toString(),
                online = op.online,
            )
        })
        live
    }

    private suspend fun enqueueCot(xml: String) {
        db.pendingActionDao().insert(
            PendingActionEntity(actionType = "POST_XML", endpoint = "/cot", payload = xml)
        )
    }

    private fun dummyDto(lat: Double, lon: Double, alt: Double?) = OperatorDto(
        id = -1, callsign = "local", rank = "", status = "ONLINE", role = "OPERATOR",
        latitude = lat, longitude = lon, altitude = alt, online = true,
    )
}

private fun CachedOperatorEntity.toDto() = OperatorDto(
    id = id, callsign = callsign, rank = "", status = if (online) "ONLINE" else "OFFLINE",
    role = role, teamId = team?.toIntOrNull(),
    latitude = lat, longitude = lon, altitude = altitude, online = online,
)
