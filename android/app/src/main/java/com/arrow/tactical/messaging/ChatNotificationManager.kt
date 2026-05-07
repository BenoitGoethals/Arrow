package com.arrow.tactical.messaging

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.arrow.tactical.MainActivity
import com.arrow.tactical.auth.AuthRepository
import com.arrow.tactical.network.WsClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

class ChatNotificationManager(
    private val context: Context,
    private val wsClient: WsClient,
    private val authRepository: AuthRepository,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val counter = AtomicInteger(100)
    private val started = AtomicBoolean(false)
    @Volatile private var meId: Int? = null

    fun start() {
        if (!started.compareAndSet(false, true)) return
        scope.launch { authRepository.me().onSuccess { meId = it.id } }
        ensureChannel()
        scope.launch {
            while (true) {
                try {
                    wsClient.events().collect { event ->
                        if (event["channel"]?.jsonPrimitive?.content != "chat") return@collect
                        val data = event["data"]?.jsonObject ?: return@collect
                        val senderId = data["sender_id"]?.jsonPrimitive?.intOrNull ?: return@collect
                        if (senderId == meId) return@collect
                        val from = event["from"]?.jsonPrimitive?.content ?: "Unknown"
                        val content = data["content"]?.jsonPrimitive?.content ?: ""
                        postNotification(from, content)
                    }
                } catch (_: Exception) {
                    // WebSocket disconnected — retry after back-off
                }
                kotlinx.coroutines.delay(3_000)
            }
        }
    }

    fun stop() = scope.cancel()

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = context.getSystemService(NotificationManager::class.java)
            if (nm.getNotificationChannel(CHANNEL_ID) == null) {
                nm.createNotificationChannel(
                    NotificationChannel(CHANNEL_ID, "Chat Messages", NotificationManager.IMPORTANCE_HIGH),
                )
            }
        }
    }

    private fun postNotification(from: String, content: String) {
        val intent = Intent(context, MainActivity::class.java).apply {
            putExtra(EXTRA_NAVIGATE_TO_CHAT, true)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val pi = PendingIntent.getActivity(
            context, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_email)
            .setContentTitle(from)
            .setContentText(content)
            .setStyle(NotificationCompat.BigTextStyle().bigText(content))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()

        context.getSystemService(NotificationManager::class.java).notify(counter.getAndIncrement(), notification)
    }

    companion object {
        const val CHANNEL_ID = "arrow.chat"
        const val EXTRA_NAVIGATE_TO_CHAT = "navigate_to_chat"
    }
}
