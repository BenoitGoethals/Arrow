package com.arrow.tactical.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.arrow.tactical.data.local.entity.CachedStrikePackageEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface StrikePackageDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(pkg: CachedStrikePackageEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(pkgs: List<CachedStrikePackageEntity>)

    /** Reactive stream of all locally-stored packages. */
    @Query("SELECT * FROM cached_strike_packages ORDER BY downloadedAt DESC")
    fun observeAll(): Flow<List<CachedStrikePackageEntity>>

    /** Reactive stream of PLANNING + ACTIVE packages — rendered on the map. */
    @Query("SELECT * FROM cached_strike_packages WHERE status IN ('PLANNING','ACTIVE') ORDER BY downloadedAt DESC")
    fun observeActive(): Flow<List<CachedStrikePackageEntity>>

    @Query("SELECT * FROM cached_strike_packages WHERE id = :id")
    suspend fun getById(id: Int): CachedStrikePackageEntity?

    @Query("UPDATE cached_strike_packages SET status = :status WHERE id = :id")
    suspend fun updateStatus(id: Int, status: String)

    @Query("DELETE FROM cached_strike_packages WHERE id = :id")
    suspend fun deleteById(id: Int)

    @Query("DELETE FROM cached_strike_packages")
    suspend fun clearAll()
}
