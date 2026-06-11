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
import com.arrow.tactical.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import com.arrow.tactical.network.trustSelfSigned
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

class CameraStreamService : Service() {

    companion object {
        const val CHANNEL_ID      = "arrow.stream"
        const val NOTIFICATION_ID = 3
        const val EXTRA_STREAM_ID  = "stream_id"
        const val EXTRA_SERVER_URL = "server_url"
        const val EXTRA_TOKEN      = "token"
        const val ACTION_STOP      = "STOP"

        private const val TAG       = "CameraStream"
        private const val FRAME_W   = 640
        private const val FRAME_H   = 480
        private const val FPS       = 5                     // target frames per second
        private val FRAME_MS        = 1000L / FPS           // ms between captures
        private const val JPEG_Q    = 40                    // 0–100 compression quality

        val isStreaming = AtomicBoolean(false)
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val camThread = HandlerThread("CamStreamThread").also { it.start() }
    private val camHandler = Handler(camThread.looper)

    private var cameraManager: CameraManager? = null
    private var cameraDevice: CameraDevice? = null
    private var captureSession: CameraCaptureSession? = null
    private var imageReader: ImageReader? = null
    private var captureRequest: CaptureRequest? = null
    private var webSocket: WebSocket? = null
    private var capturing = false

    override fun onCreate() {
        super.onCreate()
        cameraManager = getSystemService(CAMERA_SERVICE) as CameraManager
        isStreaming.set(true)
        startForeground(NOTIFICATION_ID, buildNotification())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        val streamId  = intent?.getStringExtra(EXTRA_STREAM_ID)  ?: return START_NOT_STICKY
        val serverUrl = intent.getStringExtra(EXTRA_SERVER_URL)  ?: return START_NOT_STICKY
        val token     = intent.getStringExtra(EXTRA_TOKEN)        ?: return START_NOT_STICKY

        scope.launch { connect(streamId, serverUrl, token) }
        return START_NOT_STICKY
    }

    // ── Connect WebSocket, then open camera ───────────────────────────────────

    private fun connect(streamId: String, serverUrl: String, token: String) {
        // Production deployments put Caddy in front and only proxy `/api/*` to the
        // FastAPI backend. Dev points at the backend directly on an explicit port.
        // Detect: if the URL has no explicit port (`:NNNN`) and doesn't already
        // contain `/api`, assume Caddy-proxied prod and prepend `/api`.
        val hasPort   = Regex(":[0-9]+(/|$)").containsMatchIn(serverUrl)
        val hasApi    = serverUrl.contains("/api")
        val apiPrefix = if (hasPort || hasApi) "" else "/api"
        val wsUrl = serverUrl.replace(Regex("^http"), "ws") +
                    "$apiPrefix/streams/$streamId/produce?token=${token}"
        Log.i(TAG, "Connecting to $wsUrl")

        val client = OkHttpClient.Builder()
            .pingInterval(15, TimeUnit.SECONDS)
            .connectTimeout(10, TimeUnit.SECONDS)
            .trustSelfSigned()
            .build()

        webSocket = client.newWebSocket(
            Request.Builder().url(wsUrl).build(),
            object : WebSocketListener() {
                override fun onOpen(ws: WebSocket, response: okhttp3.Response) {
                    Log.i(TAG, "WS open — opening camera")
                    camHandler.post { openCamera() }
                }
                override fun onFailure(ws: WebSocket, t: Throwable, r: okhttp3.Response?) {
                    Log.w(TAG, "WS failure: ${t.message}")
                    stopSelf()
                }
                override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                    stopSelf()
                }
            },
        )
    }

    // ── Camera2 setup ─────────────────────────────────────────────────────────

    @SuppressLint("MissingPermission")
    private fun openCamera() {
        val cm = cameraManager ?: return
        val id = cm.cameraIdList.firstOrNull { cid ->
            cm.getCameraCharacteristics(cid)
                .get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK
        } ?: cm.cameraIdList.firstOrNull() ?: run { stopSelf(); return }

        // ImageReader with JPEG format — driven by individual capture() calls
        imageReader = ImageReader.newInstance(FRAME_W, FRAME_H, ImageFormat.JPEG, 2).also { ir ->
            ir.setOnImageAvailableListener({ reader ->
                val img = reader.acquireLatestImage() ?: return@setOnImageAvailableListener
                try {
                    val buf   = img.planes[0].buffer
                    val bytes = ByteArray(buf.remaining())
                    buf.get(bytes)
                    webSocket?.send(bytes.toByteString())
                    Log.v(TAG, "Frame sent: ${bytes.size} bytes")
                } finally {
                    img.close()
                }
                // Schedule next frame
                if (capturing) camHandler.postDelayed({ triggerCapture() }, FRAME_MS)
            }, camHandler)
        }

        cm.openCamera(id, object : CameraDevice.StateCallback() {
            override fun onOpened(camera: CameraDevice) {
                cameraDevice = camera
                startSession(camera)
            }
            override fun onDisconnected(camera: CameraDevice) { camera.close(); stopSelf() }
            override fun onError(camera: CameraDevice, error: Int) {
                Log.e(TAG, "Camera error $error"); camera.close(); stopSelf()
            }
        }, camHandler)
    }

    private fun startSession(camera: CameraDevice) {
        val surface = imageReader!!.surface
        @Suppress("DEPRECATION")
        camera.createCaptureSession(listOf(surface), object : CameraCaptureSession.StateCallback() {
            override fun onConfigured(session: CameraCaptureSession) {
                captureSession = session
                captureRequest = camera.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE)
                    .apply {
                        addTarget(surface)
                        set(CaptureRequest.JPEG_QUALITY,           JPEG_Q.toByte())
                        set(CaptureRequest.CONTROL_MODE,           CameraMetadata.CONTROL_MODE_AUTO)
                        set(CaptureRequest.CONTROL_AF_MODE,        CameraMetadata.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                        set(CaptureRequest.CONTROL_AE_MODE,        CameraMetadata.CONTROL_AE_MODE_ON)
                    }.build()
                capturing = true
                triggerCapture()                       // kick off the first frame
            }
            override fun onConfigureFailed(session: CameraCaptureSession) {
                Log.e(TAG, "Session configure failed"); stopSelf()
            }
        }, camHandler)
    }

    private fun triggerCapture() {
        val session = captureSession ?: return
        val req     = captureRequest  ?: return
        try { session.capture(req, null, camHandler) }
        catch (e: Exception) { Log.w(TAG, "Capture error: ${e.message}") }
    }

    // ── Cleanup ───────────────────────────────────────────────────────────────

    override fun onDestroy() {
        isStreaming.set(false)
        capturing = false
        captureSession?.close()
        cameraDevice?.close()
        imageReader?.close()
        webSocket?.close(1000, "Stream ended")
        camThread.quitSafely()
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    // ── Foreground notification ───────────────────────────────────────────────

    private fun buildNotification(): Notification {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            getSystemService(NotificationManager::class.java)
                .createNotificationChannel(NotificationChannel(
                    CHANNEL_ID, "Video Stream", NotificationManager.IMPORTANCE_LOW))
        }
        val tapPi = PendingIntent.getActivity(this, 0,
            Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stopPi = PendingIntent.getService(this, 0,
            Intent(this, CameraStreamService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("📡 Live Streaming")
            .setContentText("Tactical camera stream active — tap to return")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentIntent(tapPi)
            .addAction(android.R.drawable.ic_delete, "Stop stream", stopPi)
            .setOngoing(true)
            .build()
    }
}
