package com.arrow.tactical.tracking

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import com.arrow.tactical.ArrowApp
import com.arrow.tactical.MainActivity
import com.arrow.tactical.R
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Foreground GPS service.
 *
 * Guest mode (no token): position is recorded in the local DB only — the map
 * shows your position but nothing is sent to the server.
 *
 * Authenticated mode: CoT XML → server; falls back to JSON on CoT failure.
 * Both paths queue the update when the link is down.
 */
class LocationService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var trackingRepo: TrackingRepository

    @Volatile private var callsign: String = ""
    @Volatile private var role: String = "OPERATOR"
    @Volatile private var localOperatorId: Int = -1

    private val callback = object : LocationCallback() {
        override fun onLocationResult(result: LocationResult) {
            val loc = result.lastLocation ?: return
            scope.launch {
                if (callsign.isNotBlank()) {
                    trackingRepo.pushPositionCot(
                        callsign = callsign, role = role,
                        lat = loc.latitude, lon = loc.longitude, hae = loc.altitude,
                        localOperatorId = localOperatorId,
                    ).onFailure {
                        trackingRepo.pushPosition(loc.latitude, loc.longitude, loc.altitude)
                    }
                } else {
                    // No identity yet (guest or unresolved) — still record position locally
                    trackingRepo.pushPosition(loc.latitude, loc.longitude, loc.altitude)
                }
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        val container = (application as ArrowApp).container
        trackingRepo = container.trackingRepository
        startForeground(NOTIFICATION_ID, buildNotification())

        // Try to resolve identity — only succeeds when authenticated + online
        scope.launch {
            container.authRepository.me().onSuccess { op ->
                callsign = op.callsign
                role = op.role
                localOperatorId = op.id
            }
            // Fallback: use saved callsign from settings (works in guest/offline)
            if (callsign.isBlank()) {
                callsign = container.settingsRepository.currentCallsign()
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 5_000L)
            .setMinUpdateIntervalMillis(2_000L)
            .build()
        try {
            LocationServices.getFusedLocationProviderClient(this)
                .requestLocationUpdates(request, callback, Looper.getMainLooper())
        } catch (_: SecurityException) {
            stopSelf()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        LocationServices.getFusedLocationProviderClient(this).removeLocationUpdates(callback)
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun buildNotification(): Notification {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID, getString(R.string.tracking_channel), NotificationManager.IMPORTANCE_LOW,
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
        val tap = android.app.PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            android.app.PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.tracking_notification))
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setContentIntent(tap)
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val CHANNEL_ID = "arrow.tracking"
        private const val NOTIFICATION_ID = 1
    }
}
