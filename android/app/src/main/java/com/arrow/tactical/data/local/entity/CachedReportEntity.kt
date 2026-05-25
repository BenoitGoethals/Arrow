package com.arrow.tactical.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "cached_reports")
data class CachedReportEntity(
    /** Negative = local-only. */
    @PrimaryKey val id: Long,
    val reportType: String,
    val payloadJson: String,
    val createdAt: Long = System.currentTimeMillis(),
    /** "local" | "synced" | "pending" */
    val syncStatus: String = "local",
)
