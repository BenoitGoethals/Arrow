package com.arrow.tactical.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.arrow.tactical.data.local.entity.CachedMessageEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface CachedMessageDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(message: CachedMessageEntity): Long

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(messages: List<CachedMessageEntity>)

    @Query("SELECT * FROM cached_messages ORDER BY createdAt DESC")
    fun observeAll(): Flow<List<CachedMessageEntity>>

    @Query("SELECT * FROM cached_messages ORDER BY createdAt DESC LIMIT :limit")
    suspend fun getLatest(limit: Int = 100): List<CachedMessageEntity>

    /** Replace a local-only record with its server-assigned ID. */
    @Query("UPDATE cached_messages SET id = :serverId, syncStatus = 'synced' WHERE id = :localId")
    suspend fun markSynced(localId: Long, serverId: Long)

    @Query("SELECT * FROM cached_messages WHERE syncStatus = 'pending' ORDER BY createdAt ASC")
    suspend fun getPending(): List<CachedMessageEntity>

    @Query("DELETE FROM cached_messages WHERE id = :id")
    suspend fun deleteById(id: Long)
}
