package com.arrow.tactical.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import com.arrow.tactical.data.local.dao.CachedAlertDao
import com.arrow.tactical.data.local.dao.CachedMessageDao
import com.arrow.tactical.data.local.dao.CachedOperatorDao
import com.arrow.tactical.data.local.dao.CachedReportDao
import com.arrow.tactical.data.local.dao.CachedTacticalObjectDao
import com.arrow.tactical.data.local.dao.PendingActionDao
import com.arrow.tactical.data.local.entity.CachedAlertEntity
import com.arrow.tactical.data.local.entity.CachedMessageEntity
import com.arrow.tactical.data.local.entity.CachedOperatorEntity
import com.arrow.tactical.data.local.entity.CachedReportEntity
import com.arrow.tactical.data.local.entity.CachedTacticalObjectEntity
import com.arrow.tactical.data.local.entity.PendingActionEntity

@Database(
    entities = [
        PendingActionEntity::class,
        CachedOperatorEntity::class,
        CachedMessageEntity::class,
        CachedReportEntity::class,
        CachedAlertEntity::class,
        CachedTacticalObjectEntity::class,
    ],
    version = 2,
    exportSchema = false,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun pendingActionDao(): PendingActionDao
    abstract fun cachedOperatorDao(): CachedOperatorDao
    abstract fun cachedMessageDao(): CachedMessageDao
    abstract fun cachedReportDao(): CachedReportDao
    abstract fun cachedAlertDao(): CachedAlertDao
    abstract fun cachedTacticalObjectDao(): CachedTacticalObjectDao

    companion object {
        @Volatile private var instance: AppDatabase? = null

        fun getInstance(context: Context): AppDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "arrow.db",
                ).fallbackToDestructiveMigration(true).build().also { instance = it }
            }
    }
}
