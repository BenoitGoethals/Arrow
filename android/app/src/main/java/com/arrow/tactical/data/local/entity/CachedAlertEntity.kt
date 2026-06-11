package com.arrow.tactical.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "cached_alerts")
data class CachedAlertEntity(
    @PrimaryKey val id: Long,
    val alertType: String,
    val callsign: String,
    val lat: Double?,
    val lon: Double?,
    val createdAt: Long = System.currentTimeMillis(),
    val syncStatus: String = "local",
)
