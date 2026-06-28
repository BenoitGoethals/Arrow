package com.arrow.tactical

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.core.content.ContextCompat
import com.arrow.tactical.messaging.ChatNotificationManager
import com.arrow.tactical.ui.ArrowNavGraph
import com.arrow.tactical.ui.theme.ArrowTheme
import com.arrow.tactical.ui.theme.ThemeMode

class MainActivity : ComponentActivity() {

    private val notificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* no-op */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val container = (application as ArrowApp).container
        requestNotificationPermissionIfNeeded()
        if (intent?.getBooleanExtra(ChatNotificationManager.EXTRA_NAVIGATE_TO_CHAT, false) == true) {
            container.signalNavigateToChat()
        }
        setContent {
            val themeName by container.settingsRepository.themeMode.collectAsState(initial = "SYSTEM")
            val mode = runCatching { ThemeMode.valueOf(themeName) }.getOrDefault(ThemeMode.SYSTEM)
            ArrowTheme(mode = mode) {
                Surface(color = MaterialTheme.colorScheme.background) {
                    ArrowNavGraph(container = container)
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.getBooleanExtra(ChatNotificationManager.EXTRA_NAVIGATE_TO_CHAT, false)) {
            (application as ArrowApp).container.signalNavigateToChat()
        }
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
}
