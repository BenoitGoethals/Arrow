package com.arrow.tactical.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Local copy of a tactical object (enemy marker, POI, etc.).
 *
 * id < 0  → created locally, not yet on the server  (syncStatus = "pending")
 * id >= 0 → server-assigned id                       (syncStatus = "synced")
 *
 * deletePending = true means the user deleted it locally; the DELETE request
 * is queued in pending_actions and the row is removed after the server confirms.
 */
@Entity(tableName = "cached_tactical_objects")
data class CachedTacticalObjectEntity(
    @PrimaryKey val id: Long,
    val type: String,
    val symbolCode: String,
    val latitude: Double,
    val longitude: Double,
    val notes: String,
    val visibility: String,
    val affiliation: String,
    val rotation: Double = 0.0,
    val geometry: String = "",
    val echelon: String = "",
    val createdBy: Int = -1,
    val createdAt: Long = System.currentTimeMillis(),
    /** "pending" | "synced" */
    val syncStatus: String = "pending",
    /** True when the row should be deleted once the server confirms the DELETE. */
    val deletePending: Boolean = false,
)
