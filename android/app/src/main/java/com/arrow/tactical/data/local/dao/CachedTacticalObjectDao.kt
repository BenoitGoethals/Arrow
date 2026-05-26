package com.arrow.tactical.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.arrow.tactical.data.local.entity.CachedTacticalObjectEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface CachedTacticalObjectDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(obj: CachedTacticalObjectEntity): Long

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(objects: List<CachedTacticalObjectEntity>)

    /** Reactive stream — emits whenever a row changes. Used by MapScreen. */
    @Query("SELECT * FROM cached_tactical_objects WHERE deletePending = 0 ORDER BY createdAt DESC")
    fun observeVisible(): Flow<List<CachedTacticalObjectEntity>>

    @Query("SELECT * FROM cached_tactical_objects WHERE deletePending = 0 ORDER BY createdAt DESC")
    suspend fun getVisible(): List<CachedTacticalObjectEntity>

    /** Replace local negative id with the server-assigned positive id. */
    @Query("UPDATE cached_tactical_objects SET id = :serverId, syncStatus = 'synced' WHERE id = :localId")
    suspend fun markSynced(localId: Long, serverId: Long)

    @Query("SELECT * FROM cached_tactical_objects WHERE syncStatus = 'pending' AND deletePending = 0")
    suspend fun getPendingCreate(): List<CachedTacticalObjectEntity>

    /** Mark as delete-pending; the actual row removal happens after server confirmation. */
    @Query("UPDATE cached_tactical_objects SET deletePending = 1 WHERE id = :id")
    suspend fun markDeletePending(id: Long)

    @Query("DELETE FROM cached_tactical_objects WHERE id = :id")
    suspend fun deleteById(id: Long)

    @Query("SELECT * FROM cached_tactical_objects WHERE deletePending = 1")
    suspend fun getPendingDelete(): List<CachedTacticalObjectEntity>

    @Query("DELETE FROM cached_tactical_objects WHERE deletePending = 1 AND syncStatus = 'synced'")
    suspend fun purgeConfirmedDeletes()

    /** Remove all synced rows — called on mission switch so stale objects don't bleed across missions. */
    @Query("DELETE FROM cached_tactical_objects WHERE syncStatus = 'synced'")
    suspend fun clearSynced()
}
