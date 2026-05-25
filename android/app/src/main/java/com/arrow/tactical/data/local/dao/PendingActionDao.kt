package com.arrow.tactical.data.local.dao

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.arrow.tactical.data.local.entity.PendingActionEntity

@Dao
interface PendingActionDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(action: PendingActionEntity): Long

    @Query("SELECT * FROM pending_actions WHERE status = 'PENDING' ORDER BY createdAt ASC")
    suspend fun getAllPending(): List<PendingActionEntity>

    @Delete
    suspend fun delete(action: PendingActionEntity)

    @Query("UPDATE pending_actions SET retryCount = retryCount + 1 WHERE id = :id")
    suspend fun incrementRetry(id: Long)

    @Query("UPDATE pending_actions SET status = 'FAILED' WHERE id = :id")
    suspend fun markFailed(id: Long)

    @Query("SELECT COUNT(*) FROM pending_actions WHERE status = 'PENDING'")
    suspend fun pendingCount(): Int
}
