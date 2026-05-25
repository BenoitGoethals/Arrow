package com.arrow.tactical.di

import android.content.Context
import coil.ImageLoader
import com.arrow.tactical.admin.LogRepository
import com.arrow.tactical.admin.MapVisibilityRepository
import com.arrow.tactical.alerts.AlertRepository
import com.arrow.tactical.auth.AuthRepository
import com.arrow.tactical.auth.TokenStore
import com.arrow.tactical.data.local.AppDatabase
import com.arrow.tactical.firemission.FireMissionRepository
import com.arrow.tactical.kml.KmlLayerRepository
import com.arrow.tactical.map.MapSourceRepository
import com.arrow.tactical.map.MilsymRenderer
import com.arrow.tactical.messaging.ChatNotificationManager
import com.arrow.tactical.messaging.MessageRepository
import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.WsClient
import com.arrow.tactical.opord.OpordRepository
import com.arrow.tactical.overlays.OverlayRepository
import com.arrow.tactical.photos.PhotoRepository
import com.arrow.tactical.reports.ReportRepository
import com.arrow.tactical.settings.SettingsRepository
import com.arrow.tactical.sync.ConnectivityObserver
import com.arrow.tactical.sync.SyncManager
import com.arrow.tactical.tactical.TacticalRepository
import com.arrow.tactical.tracking.TrackingRepository
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow

/**
 * Composition root. Every screen consumes objects exposed here — nothing
 * instantiates its own HTTP clients, DB references, or stores.
 */
class AppContainer(private val context: Context) {

    // ── Core infrastructure ────────────────────────────────────────────────

    val settingsRepository = SettingsRepository(context)
    val tokenStore = TokenStore(context)
    val apiClient = ApiClient(settingsRepository, tokenStore)
    val wsClient = WsClient(settingsRepository, tokenStore, apiClient.json)

    /** Local Room database — always available, even in guest/offline mode. */
    val db: AppDatabase = AppDatabase.getInstance(context)

    /** Network connectivity monitor. */
    val connectivity = ConnectivityObserver(context)

    /** Auth-aware Coil image loader for photo endpoints. */
    val imageLoader: ImageLoader = ImageLoader.Builder(context)
        .okHttpClient(apiClient.httpClient)
        .build()

    // ── Domain repositories — all offline-first ────────────────────────────

    val authRepository = AuthRepository(apiClient, tokenStore)

    val trackingRepository = TrackingRepository(apiClient, db, tokenStore, connectivity)

    val alertRepository = AlertRepository(apiClient, db, tokenStore, connectivity)

    val messageRepository = MessageRepository(apiClient, db, tokenStore, connectivity)

    val reportRepository = ReportRepository(apiClient, db, tokenStore, connectivity)

    val opordRepository = OpordRepository(apiClient) { settingsRepository.currentServerUrl() }
    val tacticalRepository = TacticalRepository(apiClient)
    val mapSourceRepository = MapSourceRepository(apiClient, context, tokenStore, settingsRepository)
    val kmlLayerRepository = KmlLayerRepository(apiClient)
    val overlayRepository = OverlayRepository(apiClient)
    val mapVisibilityRepository = MapVisibilityRepository(context, apiClient)
    val photoRepository = PhotoRepository(apiClient)
    val fireMissionRepository = FireMissionRepository(apiClient)
    val logRepository = LogRepository()
    val milsymRenderer = MilsymRenderer(context)

    // ── Sync engine ────────────────────────────────────────────────────────

    val syncManager = SyncManager(db, apiClient, tokenStore, connectivity)

    // ── Notifications ──────────────────────────────────────────────────────

    val chatNotificationManager = ChatNotificationManager(
        context, wsClient, authRepository, mapVisibilityRepository,
    )

    private val _navigateToChatChannel = Channel<Unit>(Channel.BUFFERED)
    val navigateToChatFlow = _navigateToChatChannel.receiveAsFlow()

    fun signalNavigateToChat() = _navigateToChatChannel.trySend(Unit)
}
