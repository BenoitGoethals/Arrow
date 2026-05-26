package com.arrow.tactical.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Offline store for a strike package bundle.
 *
 * The full resolved JSON from /strike-packages/{id}/bundle is kept verbatim
 * in [bundleJson] so the app can parse and render all assets — target, drones,
 * CAS, snipers, EW — without any network calls.
 */
@Entity(tableName = "cached_strike_packages")
data class CachedStrikePackageEntity(
    @PrimaryKey val id: Int,
    val name: String,
    val status: String,
    val missionId: Int?,
    /** Full resolved bundle JSON from /strike-packages/{id}/bundle. */
    val bundleJson: String,
    val downloadedAt: Long = System.currentTimeMillis(),
)
