package com.arrow.tactical.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "cached_messages")
data class CachedMessageEntity(
    /** Negative = local-only (not yet assigned a server ID). */
    @PrimaryKey val id: Long,
    val content: String,
    val senderCallsign: String,
    val messageType: String,
    val receiverId: Int?,
    val groupId: String?,
    val createdAt: Long = System.currentTimeMillis(),
    /** "local" | "synced" | "pending" */
    val syncStatus: String = "local",
)
