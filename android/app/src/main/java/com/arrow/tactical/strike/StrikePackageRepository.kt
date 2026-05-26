package com.arrow.tactical.strike

import android.util.Log
import com.arrow.tactical.data.local.AppDatabase
import com.arrow.tactical.data.local.entity.CachedStrikePackageEntity
import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.StrikePackageBundleDto
import com.arrow.tactical.network.StrikePackageListDto
import kotlinx.coroutines.flow.Flow

private const val TAG = "StrikePackageRepo"

/**
 * Manages strike package data: fetches bundles from the server, stores them in
 * Room, and serves them to the map screen. The bundle JSON is stored verbatim
 * so it survives offline and can be re-parsed without network access.
 */
class StrikePackageRepository(
    private val api: ApiClient,
    private val db: AppDatabase,
) {
    /** Reactive stream of active/planning packages — drives map rendering. */
    fun observeActive(): Flow<List<CachedStrikePackageEntity>> =
        db.strikePackageDao().observeActive()

    /** Reactive stream of all locally-cached packages. */
    fun observeAll(): Flow<List<CachedStrikePackageEntity>> =
        db.strikePackageDao().observeAll()

    /** Parse a stored bundle back into the typed DTO for rendering. */
    fun parseBundleJson(json: String): StrikePackageBundleDto? = runCatching {
        api.json.decodeFromString<StrikePackageBundleDto>(json)
    }.getOrNull()

    /**
     * Download the full resolved bundle for [pkgId] and persist it locally.
     * Safe to call while offline — will silently fail and leave the existing
     * cached copy intact.
     */
    suspend fun fetchAndStore(pkgId: Int) {
        val r = api.get("/strike-packages/$pkgId/bundle")
        if (!r.ok) {
            Log.w(TAG, "Bundle fetch for pkg $pkgId failed: ${r.code}")
            return
        }
        runCatching {
            val bundle = api.json.decodeFromString<StrikePackageBundleDto>(r.body)
            db.strikePackageDao().upsert(
                CachedStrikePackageEntity(
                    id          = bundle.id,
                    name        = bundle.name,
                    status      = bundle.status,
                    missionId   = bundle.missionId,
                    bundleJson  = r.body,
                )
            )
            Log.d(TAG, "Cached bundle for pkg ${bundle.id} (${bundle.name})")
        }.onFailure { Log.e(TAG, "Bundle parse error for pkg $pkgId: $it") }
    }

    /**
     * Refresh list from server: download bundles for every non-ended package.
     * Called by SyncManager on reconnect and by the WS "strike-package" event.
     */
    suspend fun syncAll() {
        val r = api.get("/strike-packages")
        if (!r.ok) return
        runCatching {
            val list = api.json.decodeFromString<List<StrikePackageListDto>>(r.body)
            // Download bundles for packages that are still active
            list.filter { it.status in listOf("PLANNING", "ACTIVE") }
                .forEach { fetchAndStore(it.id) }
            // Mark completed/aborted packages locally without deleting the bundle
            list.filter { it.status in listOf("COMPLETE", "ABORTED") }
                .forEach { db.strikePackageDao().updateStatus(it.id, it.status) }
            Log.d(TAG, "Synced ${list.size} strike packages")
        }
    }

    /** React to a WS event for a single package (created/updated/activated/completed/deleted). */
    suspend fun handleWsEvent(pkgId: Int, event: String) {
        when (event) {
            "deleted", "aborted", "completed" -> {
                if (event == "deleted") db.strikePackageDao().deleteById(pkgId)
                else db.strikePackageDao().updateStatus(pkgId, event.uppercase())
            }
            else -> fetchAndStore(pkgId)   // created / updated / activated — refresh bundle
        }
    }
}
