package com.arrow.tactical.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * One mutation that needs to reach the server.
 * Written locally first; the SyncWorker drains this table when online.
 *
 * Status lifecycle: PENDING → SYNCING → (deleted on success) | FAILED (4xx, won't retry)
 */
@Entity(tableName = "pending_actions")
data class PendingActionEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    /** HTTP verb + body type: "POST_JSON", "POST_XML", "PATCH_JSON", "DELETE" */
    val actionType: String,
    val endpoint: String,
    val payload: String = "",
    val createdAt: Long = System.currentTimeMillis(),
    val retryCount: Int = 0,
    /** "PENDING" | "FAILED" */
    val status: String = "PENDING",
)
