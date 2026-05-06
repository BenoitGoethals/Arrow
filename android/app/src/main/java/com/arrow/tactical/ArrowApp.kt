package com.arrow.tactical

import android.app.Application
import com.arrow.tactical.di.AppContainer
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
        Configuration.getInstance().userAgentValue = packageName
        container = AppContainer(this)
        appScope.launch {
            container.tokenStore.tokenFlow.collect { token ->
                if (!token.isNullOrBlank()) container.chatNotificationManager.start()
            }
        }
    }
}
