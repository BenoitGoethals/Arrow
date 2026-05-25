package com.arrow.tactical.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "cached_operators")
data class CachedOperatorEntity(
    @PrimaryKey val id: Int,
    val callsign: String,
    val role: String,
    val lat: Double?,
    val lon: Double?,
    val altitude: Double?,
    val speed: Double?,
    val course: Double?,
    val team: String?,
    val online: Boolean,
    val updatedAt: Long = System.currentTimeMillis(),
)
