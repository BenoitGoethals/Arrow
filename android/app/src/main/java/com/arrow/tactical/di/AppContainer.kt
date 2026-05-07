package com.arrow.tactical.di

import android.content.Context
import com.arrow.tactical.alerts.AlertRepository
import com.arrow.tactical.auth.AuthRepository
import com.arrow.tactical.auth.TokenStore
import com.arrow.tactical.firemission.FireMissionRepository
import com.arrow.tactical.messaging.ChatNotificationManager
import com.arrow.tactical.messaging.MessageRepository
import com.arrow.tactical.photos.PhotoRepository
import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.WsClient
import com.arrow.tactical.reports.ReportRepository
import com.arrow.tactical.settings.SettingsRepository
import com.arrow.tactical.tactical.TacticalRepository
import com.arrow.tactical.tracking.TrackingRepository
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow

/**
 * Composition root. SOLID/pluggable: every screen consumes interfaces/objects exposed here,
 * never instantiating their own HTTP clients or stores.
 */
class AppContainer(private val context: Context) {
    val settingsRepository = SettingsRepository(context)
    val tokenStore = TokenStore(context)
    val apiClient = ApiClient(settingsRepository, tokenStore)
    val wsClient = WsClient(settingsRepository, tokenStore, apiClient.json)

    val authRepository = AuthRepository(apiClient, tokenStore)
    val trackingRepository = TrackingRepository(apiClient)
    val alertRepository = AlertRepository(apiClient)
    val messageRepository = MessageRepository(apiClient)
    val reportRepository = ReportRepository(apiClient)
    val tacticalRepository = TacticalRepository(apiClient)

    val photoRepository       = PhotoRepository(apiClient)
    val fireMissionRepository = FireMissionRepository(apiClient)
    val chatNotificationManager = ChatNotificationManager(context, wsClient, authRepository)

    private val _navigateToChatChannel = Channel<Unit>(Channel.BUFFERED)
    val navigateToChatFlow = _navigateToChatChannel.receiveAsFlow()

    fun signalNavigateToChat() = _navigateToChatChannel.trySend(Unit)
}
