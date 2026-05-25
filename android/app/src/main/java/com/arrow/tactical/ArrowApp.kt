package com.arrow.tactical

import android.app.Application
import com.arrow.tactical.admin.LogRepository
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.sync.SyncWorker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import org.osmdroid.config.Configuration

class ArrowApp : Application() {
    lateinit var container: AppContainer
        private set

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onCreate() {
        super.onCreate()
        LogRepository.installCrashHandler()
        Configuration.getInstance().userAgentValue = packageName
        container = AppContainer(this)

        // Start connectivity-triggered auto-sync (fires whenever link comes back up).
        container.syncManager.startAutoSync()

        appScope.launch {
            container.tokenStore.tokenFlow.collect { token ->
                if (!token.isNullOrBlank()) {
                    // Authenticated: start notifications and schedule periodic background sync.
                    container.chatNotificationManager.start()
                    SyncWorker.schedule(this@ArrowApp)
                    // Trigger an immediate sync in case we missed events while offline.
                    container.syncManager.sync()
                } else {
                    // Logged out: cancel the periodic worker.
                    SyncWorker.cancelAll(this@ArrowApp)
                }
            }
        }
    }
}
