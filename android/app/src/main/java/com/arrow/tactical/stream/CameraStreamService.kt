package com.arrow.tactical.stream

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.graphics.ImageFormat
import android.hardware.camera2.*
import android.media.ImageReader
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import com.arrow.tactical.ArrowApp
import com.arrow.tactical.MainActivity
import com.arrow.tactical.R
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

class CameraStreamService : Service() {

    companion object {
        const val CHANNEL_ID     = "arrow.stream"
        const val NOTIFICATION_ID = 3
        const val EXTRA_STREAM_ID = "stream_id"
        const val EXTRA_SERVER_URL = "server_url"
        const val EXTRA_TOKEN      = "token"

        // Compression / rate settings
        private const val FRAME_W   = 640
        private const val FRAME_H   = 480
        private const val TARGET_FPS = 5
        private val FRAME_INTERVAL_MS = 1000L / TARGET_FPS
        private const val JPEG_QUALITY = 40   // 0–100; 40 gives good compression
        private const val TAG = "CameraStream"

        var isStreaming = AtomicBoolean(false)
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private lateinit var cameraManager: CameraManager
    private var cameraDevice: CameraDevice? = null
    private var captureSession: CameraCaptureSession? = null
    private var imageReader: ImageReader? = null
    private var webSocket: WebSocket? = null

    private val cameraThread = HandlerThread("CameraStreamThread").also { it.start() }
    private val cameraHandler = Handler(cameraThread.looper)

    private var lastFrameMs = 0L

    override fun onCreate() {
        super.onCreate()
        cameraManager = getSystemService(CAMERA_SERVICE) as CameraManager
        isStreaming.set(true)
        startForeground(NOTIFICATION_ID, buildNotification())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val streamId  = intent?.getStringExtra(EXTRA_STREAM_ID)  ?: "unknown"
        val serverUrl = intent?.getStringExtra(EXTRA_SERVER_URL) ?: ""
        val token     = intent?.getStringExtra(EXTRA_TOKEN)       ?: ""

        scope.launch {
            connectAndStream(streamId, serverUrl, token)
        }
        return START_NOT_STICKY
    }

    private suspend fun connectAndStream(streamId: String, serverUrl: String, token: String) {
        val wsUrl = serverUrl.replace("http", "ws") + "/streams/$streamId/produce?token=$token"

        val client = OkHttpClient.Builder()
            .pingInterval(20, TimeUnit.SECONDS)
            .build()

        val request = Request.Builder().url(wsUrl).build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: okhttp3.WebSocket, response: okhttp3.Response) {
                Log.i(TAG, "WebSocket connected for stream $streamId")
                openCamera()
            }
            override fun onFailure(ws: okhttp3.WebSocket, t: Throwable, r: okhttp3.Response?) {
                Log.w(TAG, "WebSocket failure: ${t.message}")
                stopSelf()
            }
            override fun onClosed(ws: okhttp3.WebSocket, code: Int, reason: String) {
                stopSelf()
            }
        })
    }

    @SuppressLint("MissingPermission")
    private fun openCamera() {
        val cameraId = backFacingCamera() ?: run { stopSelf(); return }

        imageReader = ImageReader.newInstance(FRAME_W, FRAME_H, ImageFormat.JPEG, 3).also { reader ->
            reader.setOnImageAvailableListener({ r ->
                val now = System.currentTimeMillis()
                val img = r.acquireLatestImage()
                if (img == null || now - lastFrameMs < FRAME_INTERVAL_MS) {
                    img?.close(); return@setOnImageAvailableListener
                }
                lastFrameMs = now
                try {
                    val buf   = img.planes[0].buffer
                    val bytes = ByteArray(buf.remaining())
                    buf.get(bytes)
                    webSocket?.send(bytes.toByteString())
                } finally {
                    img.close()
                }
            }, cameraHandler)
        }

        cameraManager.openCamera(cameraId, object : CameraDevice.StateCallback() {
            override fun onOpened(camera: CameraDevice) {
                cameraDevice = camera
                startCapture(camera)
            }
            override fun onDisconnected(camera: CameraDevice) { camera.close(); stopSelf() }
            override fun onError(camera: CameraDevice, error: Int) { camera.close(); stopSelf() }
        }, cameraHandler)
    }

    private fun startCapture(camera: CameraDevice) {
        val surface = imageReader!!.surface
        camera.createCaptureSession(
            listOf(surface),
            object : CameraCaptureSession.StateCallback() {
                override fun onConfigured(session: CameraCaptureSession) {
                    captureSession = session
                    val req = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                        addTarget(surface)
                        set(CaptureRequest.JPEG_QUALITY, JPEG_QUALITY.toByte())
                        set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE,
                            android.util.Range(TARGET_FPS, TARGET_FPS))
                    }.build()
                    session.setRepeatingRequest(req, null, cameraHandler)
                }
                override fun onConfigureFailed(session: CameraCaptureSession) { stopSelf() }
            },
            cameraHandler,
        )
    }

    private fun backFacingCamera(): String? =
        cameraManager.cameraIdList.firstOrNull { id ->
            cameraManager.getCameraCharacteristics(id)
                .get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK
        }

    override fun onDestroy() {
        isStreaming.set(false)
        captureSession?.close()
        cameraDevice?.close()
        imageReader?.close()
        webSocket?.close(1000, "Stream ended")
        cameraThread.quitSafely()
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun buildNotification(): Notification {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(CHANNEL_ID, "Video Stream",
                NotificationManager.IMPORTANCE_LOW)
            getSystemService(NotificationManager::class.java).createNotificationChannel(ch)
        }
        val tap = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this, 0,
            Intent(this, CameraStreamService::class.java).setAction("STOP"),
            PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("📡 Live Streaming")
            .setContentText("Tactical video stream active")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentIntent(tap)
            .addAction(android.R.drawable.ic_delete, "Stop", stop)
            .setOngoing(true)
            .build()
    }
}
