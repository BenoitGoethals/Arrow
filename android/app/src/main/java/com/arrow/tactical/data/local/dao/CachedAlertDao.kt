package com.arrow.tactical.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.arrow.tactical.data.local.entity.CachedAlertEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface CachedAlertDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(alert: CachedAlertEntity): Long

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(alerts: List<CachedAlertEntity>)

    @Query("SELECT * FROM cached_alerts ORDER BY createdAt DESC")
    fun observeAll(): Flow<List<CachedAlertEntity>>

    @Query("SELECT * FROM cached_alerts WHERE syncStatus = 'pending' ORDER BY createdAt ASC")
    suspend fun getPending(): List<CachedAlertEntity>

    @Query("UPDATE cached_alerts SET syncStatus = 'synced' WHERE id = :id")
    suspend fun markSynced(id: Long)
}
