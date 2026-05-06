package com.arrow.tactical.network

import com.arrow.tactical.auth.TokenStore
import com.arrow.tactical.settings.SettingsRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit

class WsClient(
    private val settings: SettingsRepository,
    private val tokenStore: TokenStore,
    private val json: Json,
) {
    private val client = OkHttpClient.Builder()
        .pingInterval(30, TimeUnit.SECONDS)
        .build()

    suspend fun events(): Flow<JsonObject> = callbackFlow {
        val token = withContext(Dispatchers.IO) { tokenStore.current() }
            ?: run { close(); return@callbackFlow }
        val base = withContext(Dispatchers.IO) { settings.currentServerUrl() }
            .replaceFirst("http", "ws")
        val request = Request.Builder().url("$base/ws?token=$token").build()

        val ws = client.newWebSocket(request, object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                runCatching { json.parseToJsonElement(text).let { it as JsonObject } }
                    .onSuccess { trySend(it) }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                close()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                close(t)
            }
        })

        awaitClose { ws.close(1000, "client closed") }
    }
}
