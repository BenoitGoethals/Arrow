package com.arrow.tactical.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.arrow.tactical.data.local.entity.CachedReportEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface CachedReportDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(report: CachedReportEntity): Long

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(reports: List<CachedReportEntity>)

    @Query("SELECT * FROM cached_reports ORDER BY createdAt DESC")
    fun observeAll(): Flow<List<CachedReportEntity>>

    @Query("SELECT * FROM cached_reports ORDER BY createdAt DESC LIMIT :limit")
    suspend fun getLatest(limit: Int = 100): List<CachedReportEntity>

    @Query("UPDATE cached_reports SET id = :serverId, syncStatus = 'synced' WHERE id = :localId")
    suspend fun markSynced(localId: Long, serverId: Long)

    @Query("SELECT * FROM cached_reports WHERE syncStatus = 'pending' ORDER BY createdAt ASC")
    suspend fun getPending(): List<CachedReportEntity>
}
