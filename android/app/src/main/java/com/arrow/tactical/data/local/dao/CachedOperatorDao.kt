package com.arrow.tactical.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.arrow.tactical.data.local.entity.CachedOperatorEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface CachedOperatorDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(operator: CachedOperatorEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(operators: List<CachedOperatorEntity>)

    @Query("SELECT * FROM cached_operators ORDER BY callsign ASC")
    fun observeAll(): Flow<List<CachedOperatorEntity>>

    @Query("SELECT * FROM cached_operators ORDER BY callsign ASC")
    suspend fun getAll(): List<CachedOperatorEntity>

    @Query("DELETE FROM cached_operators")
    suspend fun clear()
}
