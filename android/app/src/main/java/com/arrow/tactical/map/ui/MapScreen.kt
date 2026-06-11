package com.arrow.tactical.map.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.GpsFixed
import androidx.compose.material.icons.filled.Layers
import androidx.compose.material.icons.filled.MyLocation
import androidx.compose.material.icons.filled.Videocam
import androidx.compose.material.icons.filled.VideocamOff
import androidx.compose.material.icons.filled.Warning
import androidx.compose.ui.layout.ContentScale
import coil.compose.AsyncImage
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.Canvas
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Path
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.core.graphics.toColorInt
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.kml.KmlFeature
import com.arrow.tactical.kml.KmlLayerDto
import com.arrow.tactical.kml.buildKmlOverlays
import com.arrow.tactical.map.BackendTileSource
import com.arrow.tactical.overlays.OverlayDto
import com.arrow.tactical.map.MapSourceDto
import com.arrow.tactical.map.MilSymbolRenderer
import com.arrow.tactical.network.OperatorDto
import com.arrow.tactical.network.TacticalObjectDto
import com.arrow.tactical.network.TacticalObjectIn
import com.arrow.tactical.tactical.EnemyType
import com.arrow.tactical.tactical.FriendlyType
import com.arrow.tactical.tracking.LocationService
import androidx.compose.ui.graphics.toArgb
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import com.arrow.tactical.network.MgrsConverter
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.osmdroid.events.MapEventsReceiver
import org.osmdroid.tileprovider.MapTileProviderArray
import org.osmdroid.tileprovider.MapTileProviderBase
import org.osmdroid.tileprovider.MapTileProviderBasic
import org.osmdroid.tileprovider.modules.MBTilesFileArchive
import org.osmdroid.tileprovider.modules.MapTileFileArchiveProvider
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.tileprovider.tilesource.XYTileSource
import org.osmdroid.tileprovider.util.SimpleRegisterReceiver
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.MapEventsOverlay
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.TilesOverlay

// CATEGORY is gone — replaced by RadialMenu; ENEMY_TYPE and NOTES are direct bottom sheets
private enum class MenuStep { ENEMY_TYPE, NOTES, FRIENDLY_TYPE, FRIENDLY_NOTES, DRONE_SPOT, CAS_NINE_LINER }
private enum class OverlayMode { ALL, NONE, ENEMIES, OWN_PLATOON }

// Drone types + behaviours the operator can pick from in the radial bottom sheet.
private val DRONE_TYPES = listOf(
    "UNKNOWN", "QUADCOPTER", "FIXED_WING", "FPV", "LOITERING_MUNITION",
    "ISR", "SHAHED-136", "BAYRAKTAR_TB2", "ORLAN-10", "MAVIC",
)
private val DRONE_BEHAVIOURS = listOf(
    "UNKNOWN", "HOVERING", "TRANSITING", "ATTACK_RUN",
    "RECONNAISSANCE", "LOITERING", "EVADING",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MapScreen(
    container:    AppContainer,
    onCallFire:   (lat: Double, lon: Double) -> Unit = { _, _ -> },
    onReport:     (lat: Double, lon: Double) -> Unit = { _, _ -> },
    onOpenMortar: (lat: Double, lon: Double) -> Unit = { _, _ -> },
    onOpenDrawer: () -> Unit = {},
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var operators    by remember { mutableStateOf<List<OperatorDto>>(emptyList()) }
    // Enemies are collected from the local DB — updates instantly on offline mark + on sync.
    val enemies by container.tacticalRepository.observeObjects().collectAsState(initial = emptyList())
    val strikePkgEntities by container.strikePackageRepository.observeActive()
        .collectAsState(initial = emptyList())
    var fireMissions by remember { mutableStateOf<List<com.arrow.tactical.network.FireMissionDto>>(emptyList()) }
    var selectedObjective by remember { mutableStateOf<TacticalObjectDto?>(null) }
    var meId by remember { mutableStateOf<Int?>(null) }
    var hasAutocentered by remember { mutableStateOf(value = false) }
    var serverUrl by remember { mutableStateOf("") }
    // null = checking, true = online, false = offline.
    // Seeded from ConnectivityObserver so the indicator is instant even before
    // the first server poll completes; server polling then overrides it.
    val connOnline by container.connectivity.isOnline.collectAsState(initial = false)
    var serverOnline by remember { mutableStateOf<Boolean?>(null) }
    LaunchedEffect(connOnline) { if (serverOnline == null) serverOnline = connOnline }
    var overlayMode by remember { mutableStateOf(OverlayMode.ALL) }
    // Independent layer for tactical control graphics — gates lines, polygons
    // and oriented-point graphics regardless of overlayMode.
    var tgVisible    by remember { mutableStateOf(true) }
    var cbrnVisible  by remember { mutableStateOf(true) }
    var cbrnReports  by remember { mutableStateOf<List<Pair<Int, com.arrow.tactical.cbrn.CbrnPayload>>>(emptyList()) }
    var myPlatoonIds by remember { mutableStateOf<Set<Int>>(emptySet()) }
    // Base-layer switcher — fetched from /map/sources; null means "fall back
    // to OSMdroid's built-in MAPNIK", which the AndroidView factory sets up
    // synchronously so the map renders something while the list is loading.
    var mapSources    by remember { mutableStateOf<List<MapSourceDto>>(emptyList()) }
    var selectedMap   by remember { mutableStateOf<MapSourceDto?>(null) }
    var layerMenuOpen by remember { mutableStateOf(false) }
    // KML layers — fetched from /kml-layers. ``kmlFeatures`` caches the heavy
    // feature lists so toggling a layer's visibility doesn't re-hit the server.
    // ``kmlOverlays`` maps layer-id → the osmdroid Overlays currently on the
    // map, so we can remove them cleanly on hide / WS deletion.
    var kmlLayers       by remember { mutableStateOf<List<KmlLayerDto>>(emptyList()) }
    val kmlFeatures = remember { mutableStateMapOf<Int, List<KmlFeature>>() }
    val kmlOverlays = remember { mutableStateMapOf<Int, List<org.osmdroid.views.overlay.Overlay>>() }
    // Per-device "locally hidden" set. The server's ``visible`` flag is shared
    // across every client and only ADMIN/BC can change it; this lets every
    // operator hide a layer on their own screen without needing the role to
    // PATCH the server. A layer renders only when (visible && !locallyHidden).
    // Held as an immutable Set in a single MutableState (Compose 1.7 lacks
    // mutableStateSetOf — added in 1.8) so the render LaunchedEffect can key
    // off it directly without copying.
    var kmlLocallyHidden by remember { mutableStateOf<Set<Int>>(emptySet()) }
    // Trigger bumped by the shared WS handler when a kml-layer event arrives;
    // a LaunchedEffect below reloads the layer list whenever it changes.
    val kmlReloadTrigger = remember { mutableIntStateOf(0) }
    // Floating panel listing the imported KML layers; opens from the KML chip.
    var kmlPanelOpen by remember { mutableStateOf(false) }
    // Lets the operator collapse the entire SitaWare chrome off to the left
    // when they need a clean view. A small handle at top-left brings it back.
    var topBarCollapsed by remember { mutableStateOf(false) }
    var zoomLevel by remember { mutableFloatStateOf(8f) }

    // ── Saved overlays — per-device active set, mirrors web localStorage.
    // Named ``savedOverlays`` (not ``overlays``) so it never shadows the
    // ``MapView.overlays`` member when this lambda is captured into the
    // AndroidView factory block.
    var savedOverlays  by remember { mutableStateOf<List<OverlayDto>>(emptyList()) }
    var activeOverlays by remember { mutableStateOf<Set<Int>>(emptySet()) }
    val overlayReloadTrigger = remember { mutableIntStateOf(0) }
    var overlayPanelOpen by remember { mutableStateOf(false) }

    // ── Admin map+notification visibility — global filter ──────────────────
    // The repository holds a StateFlow; we collect it here so every render
    // path that gates on a flag re-runs the moment the admin toggles it.
    val visibility by container.mapVisibilityRepository.flow.collectAsState()
    LaunchedEffect(Unit) { container.mapVisibilityRepository.refresh() }

    // ── Alert markers — built when an "alert/triggered" WS event arrives, the
    // map auto-pans to the contact and a snackbar shows the MGRS so the BC
    // can read it on the radio. Cleared when the alert is acknowledged.
    val alertMarkers = remember {
        mutableStateMapOf<Int, org.osmdroid.views.overlay.Marker>()
    }
    val snackbarHostState = remember { SnackbarHostState() }

    // mapRef lets LaunchedEffect imperatively update overlays outside AndroidView.update,
    // which avoids Compose's state-tracking limitations for non-composable lambdas.
    // Declared early so the WS handler below can capture it for alert markers.
    val mapRef = remember { mutableStateOf<MapView?>(null) }
    // Holds the currently-painted MBTiles overlay so we can remove it on
    // basemap switch without disturbing other map overlays (markers, events).
    val mbtilesOverlay = remember { mutableStateOf<TilesOverlay?>(null) }
    var isStreaming  by remember {
        mutableStateOf(com.arrow.tactical.stream.CameraStreamService.isStreaming.get())
    }
    // Map rotation state — mapOrientation mirrors osmdroid's MapView.mapOrientation
    // so the compass arrow can render the current heading. `northLocked` forces the
    // map to stay north-up and disables the rotation-gesture overlay.
    var mapOrientation by remember { mutableFloatStateOf(0f) }
    var northLocked    by remember { mutableStateOf(true) }
    var goToOpen       by remember { mutableStateOf(false) }
    // Temporary "Go To" pin — shown after the user navigates to a location.
    val goToMarker = remember { mutableStateOf<Marker?>(null) }

    // ── Weather overlay state ──────────────────────────────────────────────
    var wxPanelOpen     by remember { mutableStateOf(false) }
    var wxRadarActive   by remember { mutableStateOf(false) }
    var wxRadarOpacity  by remember { mutableFloatStateOf(0.7f) }
    var wxSatActive     by remember { mutableStateOf(false) }
    var wxSatOpacity    by remember { mutableFloatStateOf(0.5f) }
    var wxPlaying       by remember { mutableStateOf(false) }
    var wxFrames        by remember { mutableStateOf<List<com.arrow.tactical.map.RainViewerFrame>>(emptyList()) }
    var wxNowcastStart  by remember { mutableIntStateOf(0) }
    var wxSatFrame      by remember { mutableStateOf<com.arrow.tactical.map.RainViewerFrame?>(null) }
    var wxFrameIndex    by remember { mutableIntStateOf(0) }
    // Live references to the active OSMdroid tile overlays (null when not active).
    val wxRadarOverlay = remember { mutableStateOf<com.arrow.tactical.map.WeatherTilesOverlay?>(null) }
    val wxSatOverlay   = remember { mutableStateOf<com.arrow.tactical.map.WeatherTilesOverlay?>(null) }

    // Suspend function to launch the stream service, called after permission grant.
    // Each early-return path emits a logcat E line + a Toast so the failure mode is
    // never silent (visible in the Admin log viewer too).
    val startStream: suspend () -> Unit = start@{
        val tag    = "StreamStart"
        val token  = container.tokenStore.current()
        if (token.isNullOrBlank()) {
            android.util.Log.e(tag, "abort: no token — user must re-login")
            android.widget.Toast.makeText(context, "Stream aborted: not logged in",
                android.widget.Toast.LENGTH_SHORT).show()
            return@start
        }
        val server = container.settingsRepository.currentServerUrl()
        if (server.isBlank()) {
            android.util.Log.e(tag, "abort: no server URL configured")
            android.widget.Toast.makeText(context, "Stream aborted: server URL not set",
                android.widget.Toast.LENGTH_SHORT).show()
            return@start
        }
        val meRes = container.authRepository.me()
        val me = meRes.getOrElse { err ->
            android.util.Log.e(tag, "abort: /auth/me failed: ${err.message}", err)
            android.widget.Toast.makeText(context, "Stream aborted: ${err.message ?: "auth check failed"}",
                android.widget.Toast.LENGTH_LONG).show()
            return@start
        }
        val sid = "stream-${me.callsign}-${System.currentTimeMillis() / 1000}"
        android.util.Log.i(tag, "starting stream id=$sid server=$server")
                val intent = Intent(
            context, com.arrow.tactical.stream.CameraStreamService::class.java
        ).apply {
            putExtra(com.arrow.tactical.stream.CameraStreamService.EXTRA_STREAM_ID,  sid)
            putExtra(com.arrow.tactical.stream.CameraStreamService.EXTRA_SERVER_URL, server)
            putExtra(com.arrow.tactical.stream.CameraStreamService.EXTRA_TOKEN,      token)
        }
        try {
            androidx.core.content.ContextCompat.startForegroundService(context, intent)
            isStreaming = true
        } catch (e: Exception) {
            android.util.Log.e(tag, "startForegroundService failed: ${e.message}", e)
            android.widget.Toast.makeText(context, "Stream service refused: ${e.message}",
                android.widget.Toast.LENGTH_LONG).show()
        }
    }

    // Camera permission launcher — requests permission then starts stream
    val cameraPermLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) scope.launch { startStream() }
    }

    LaunchedEffect(Unit) {
        serverUrl = container.settingsRepository.currentServerUrl()
    }

    // Keep the toggle in sync if the service self-terminates (network drop, etc.)
    LaunchedEffect(Unit) {
        while (true) {
            val live = com.arrow.tactical.stream.CameraStreamService.isStreaming.get()
            if (live != isStreaming) isStreaming = live
            kotlinx.coroutines.delay(1_000)
        }
    }

    // Resolve own-platoon membership from hierarchy whenever meId becomes available
    LaunchedEffect(meId) {
        val id = meId ?: return@LaunchedEffect
        container.tacticalRepository.getHierarchyJson()
            .onSuccess { json ->
                myPlatoonIds = parsePlatoonIds(json, id)
            }
    }

    // Reload all map data and fly to center whenever the active mission changes
    val activeMission by container.missionRepository.activeMission.collectAsState()
    LaunchedEffect(activeMission) {
        // Clear stale cached objects then re-fetch scoped to the new (or cleared) mission.
        // API client injects X-Mission-ID on every request automatically.
        container.tacticalRepository.clearAndReload()
        container.trackingRepository.liveOperators()
            .onSuccess { ops -> operators = ops }
        container.fireMissionRepository.list()
            .onSuccess { fireMissions = it }
        // Fly to mission center if set
        val m = activeMission ?: return@LaunchedEffect
        if (m.mapCenterLat == null || m.mapCenterLng == null) return@LaunchedEffect
        val map = mapRef.value ?: return@LaunchedEffect
        map.controller.setZoom(m.mapZoom.toDouble())
        map.controller.animateTo(GeoPoint(m.mapCenterLat, m.mapCenterLng))
    }

    // Tap state — written from the OSMdroid tap callback
    val pendingPointState     = remember { mutableStateOf<GeoPoint?>(null) }
    val pendingScreenPosState = remember { mutableStateOf<Offset?>(null) }
    var pendingPoint     by pendingPointState
    var pendingScreenPos by pendingScreenPosState

    // ── Measure tool state — when measureMode is on, taps drop points instead of
    //    opening the radial menu. Two points = distance + azimuth shown in a panel.
    val measureModeState   = remember { mutableStateOf(false) }
    val measureFirstState  = remember { mutableStateOf<GeoPoint?>(null) }
    val measureSecondState = remember { mutableStateOf<GeoPoint?>(null) }
    var measureMode   by measureModeState
    var measureFirst  by measureFirstState
    var measureSecond by measureSecondState
    val measurePolylineRef = remember { mutableStateOf<org.osmdroid.views.overlay.Polyline?>(null) }
    val measureMarkersRef  = remember { mutableStateOf<List<Marker>>(emptyList()) }
    // null screenPos = bottom-sheet showing; non-null = radial menu showing
    var menuStep     by remember { mutableStateOf(MenuStep.ENEMY_TYPE) }
    var selectedType         by remember { mutableStateOf(EnemyType.INFANTRY) }
    var selectedFriendlyType by remember { mutableStateOf(FriendlyType.INFANTRY) }
    var notes         by remember { mutableStateOf("") }
    var friendlyNotes by remember { mutableStateOf("") }
    var submitting by remember { mutableStateOf(false) }
    var submitError by remember { mutableStateOf<String?>(null) }
    var pendingPhotoId  by remember { mutableStateOf<Int?>(null) }
    var pendingPhotoUri by remember { mutableStateOf<android.net.Uri?>(null) }
    var uploadingPhoto  by remember { mutableStateOf(false) }

    // ── Drone-spot form state (used by both radial-menu and top-bar buttons) ──
    var droneType      by remember { mutableStateOf("UNKNOWN") }
    var droneAltitude  by remember { mutableStateOf("") }
    var droneDirection by remember { mutableStateOf("") }
    var droneSpeed     by remember { mutableStateOf("") }
    var droneBehavior  by remember { mutableStateOf("UNKNOWN") }
    var droneNotes     by remember { mutableStateOf("") }

    // ── Tactical object action radial (tap marker → Delete / Move) ──────────
    var selectedTacticalObj       by remember { mutableStateOf<TacticalObjectDto?>(null) }
    var selectedTacticalObjScreen by remember { mutableStateOf<Offset?>(null) }
    val movingTacticalObjState = remember { mutableStateOf<TacticalObjectDto?>(null) }
    var movingTacticalObj by movingTacticalObjState
    val role by container.tokenStore.roleFlow.collectAsState(initial = null)
    val canEditTactical = role == "ADMIN" || role == "BATTLE_CAPTAIN"

    // ── CAS 9-liner form state ─────────────────────────────────────────────
    var casLine1   by remember { mutableStateOf("") }  // IP
    var casLine2   by remember { mutableStateOf("") }  // Heading/Distance
    var casLine3   by remember { mutableStateOf("") }  // Target elevation
    var casLine4   by remember { mutableStateOf("") }  // Target description
    var casLine5Lat by remember { mutableStateOf("") } // Target lat (from map tap)
    var casLine5Lon by remember { mutableStateOf("") } // Target lon (from map tap)
    var casLine6   by remember { mutableStateOf("Laser") } // Type of mark
    var casLine7   by remember { mutableStateOf("") }  // Friendly location
    var casLine8   by remember { mutableStateOf("") }  // Egress
    var casLine9   by remember { mutableStateOf("") }  // Remarks/threats
    var casTic     by remember { mutableStateOf(false) }
    var casFoId    by remember { mutableStateOf<Int?>(null) }
    var casAssetId by remember { mutableStateOf<Int?>(null) }
    var casAssets  by remember { mutableStateOf<List<com.arrow.tactical.network.CasAssetDto>>(emptyList()) }

    // Fetch CAS assets when the composable enters composition
    LaunchedEffect(Unit) {
        container.casRepository.listAssets()
            .onSuccess { casAssets = it }
    }

    val galleryLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        pendingPhotoUri = uri
        scope.launch {
            uploadingPhoto = true
            container.photoRepository.upload(context, uri)
                .onSuccess  { pendingPhotoId = it }
                .onFailure  { pendingPhotoId = null; pendingPhotoUri = null }
            uploadingPhoto = false
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestMultiplePermissions(),
    ) { results ->
        if (results.values.all { it }) {
            ContextCompat.startForegroundService(context, Intent(context, LocationService::class.java))
        }
    }

    LaunchedEffect(Unit) {
        val perms = arrayOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION,
        )
        val missing = perms.any { ContextCompat.checkSelfPermission(context, it) != PackageManager.PERMISSION_GRANTED }
        if (missing) permissionLauncher.launch(perms)
        else ContextCompat.startForegroundService(context, Intent(context, LocationService::class.java))
    }

    LaunchedEffect(Unit) {
        container.authRepository.me().onSuccess { meId = it.id }
    }

    // Resilient polling — two-stage: health ping (no auth) then authenticated fetch.
    // This separates "server unreachable" from "token / auth problem" in the error text.
    LaunchedEffect(Unit) {
        while (true) {
            try {
                val health = container.apiClient.get("/health")
                if (!health.ok) {
                    serverOnline = false
                } else {
                    container.tacticalRepository.listOperators()
                        .onSuccess { ops ->
                            operators    = ops
                            serverOnline = true
                        }
                        .onFailure {
                            serverOnline = false
                        }
                    container.fireMissionRepository.list()
                        .onSuccess { fireMissions = it }
                    container.reportRepository.list()
                        .onSuccess { reps ->
                            cbrnReports = com.arrow.tactical.cbrn.cbrnReportsFrom(reps)
                        }
                }
            } catch (_: Exception) {
                serverOnline = false
            }
            delay(15_000)
        }
    }

    // Resilient WebSocket — reconnects automatically after any failure
    LaunchedEffect(Unit) {
        while (true) {
            try {
                container.wsClient.events().collect { evt: JsonObject ->
                    when (evt["channel"]?.toString()?.trim('"')) {
                        "tracking"        -> container.trackingRepository.liveOperators()
                            .onSuccess { ops -> operators = ops; serverOnline = true }
                        "tactical-object" -> container.tacticalRepository.listObjects() // refreshes local cache
                        "fire-mission"    -> container.fireMissionRepository.list()
                            .onSuccess { fireMissions = it }
                        "report"          -> container.reportRepository.list()
                            .onSuccess { reps ->
                                cbrnReports = com.arrow.tactical.cbrn.cbrnReportsFrom(reps)
                            }
                        "kml-layer"       -> kmlReloadTrigger.intValue++
                        "overlay"         -> overlayReloadTrigger.value++
                        "map-visibility"  -> container.mapVisibilityRepository.applyServerEvent(evt)
                        "alert"           -> com.arrow.tactical.alerts.handleAlertWsEvent(
                            evt,
                            map = mapRef.value,
                            ops = operators,
                            alertMarkers = alertMarkers,
                            snackbarHostState = snackbarHostState,
                            context = context,
                            visibility = container.mapVisibilityRepository.current,
                        )
                        "strike-package"  -> {
                            val event = evt["event"]?.toString()?.trim('"') ?: ""
                            val pkgId = evt["data"]?.jsonObject?.get("id")?.jsonPrimitive?.int ?: -1
                            if (pkgId > 0) container.strikePackageRepository.handleWsEvent(pkgId, event)
                        }
                        "mission"         -> {
                            val event = evt["event"]?.toString()?.trim('"')
                            if (event == "reset") {
                                // Server wiped all map objects for this mission — clear local view
                                container.tacticalRepository.listObjects()
                                container.fireMissionRepository.list()
                                    .onSuccess { fireMissions = it }
                                container.reportRepository.list()
                                    .onSuccess { reps ->
                                        cbrnReports = com.arrow.tactical.cbrn.cbrnReportsFrom(reps)
                                    }
                                snackbarHostState.showSnackbar("Mission map reset by admin")
                            }
                        }
                        else -> {}
                    }
                }
            } catch (_: Exception) {
                // WebSocket disconnected — back-off then reconnect
            }
            delay(3_000)
        }
    }

    // ── KML — fetch the layer list on entry and on every kml-layer WS event ──
    LaunchedEffect(kmlReloadTrigger.intValue) {
        container.kmlLayerRepository.list()
            .onSuccess { kmlLayers = it }
    }

    // ── Overlays — same WS-triggered reload pattern ──
    LaunchedEffect(overlayReloadTrigger.value) {
        container.overlayRepository.list().onSuccess { fresh ->
            savedOverlays = fresh
            // Drop active ids whose overlay no longer exists on the server.
            val freshIds = fresh.map { it.id }.toSet()
            if (activeOverlays.any { it !in freshIds }) {
                activeOverlays = activeOverlays.intersect(freshIds)
            }
        }
    }

    // Materialise visible layers onto the map. Re-runs whenever the catalogue
    // changes OR the local-hide set changes; feature payloads are fetched
    // lazily and cached in kmlFeatures so a hide/show flip is instant.
    LaunchedEffect(mapRef.value, kmlLayers, kmlLocallyHidden, visibility.kmlLayers) {
        val map = mapRef.value ?: return@LaunchedEffect
        // Admin global KML toggle — when off, no layer is rendered regardless
        // of the per-layer ``visible`` flag and the local-hide set.
        val visibleIds = if (!visibility.kmlLayers) emptySet() else kmlLayers
            .filter { it.visible && it.id !in kmlLocallyHidden }
            .map { it.id }
            .toSet()

        // Drop overlays for layers that disappeared or were hidden.
        val toRemove = kmlOverlays.keys.filterNot { it in visibleIds }
        for (id in toRemove) {
            kmlOverlays.remove(id)?.forEach { map.overlays.remove(it) }
        }

        // Skip the add-pass entirely when the admin has hidden KML globally.
        if (!visibility.kmlLayers) {
            map.invalidate()
            return@LaunchedEffect
        }
        // Add overlays for newly-visible layers, fetching features on demand.
        for (layer in kmlLayers) {
            if (!layer.visible || layer.id in kmlLocallyHidden) continue
            if (kmlOverlays.containsKey(layer.id)) continue
            val features = kmlFeatures.getOrPut(layer.id) {
                container.kmlLayerRepository.features(layer.id).getOrDefault(emptyList())
            }
            if (features.isEmpty()) continue
            val overlays = buildKmlOverlays(map, features)
            // Insert just above the base tile / mbtiles overlay (index 1) so
            // tactical markers added later still sit on top.
            val insertAt = (kmlOverlays.values.sumOf { it.size }).coerceAtMost(map.overlays.size)
            for ((i, o) in overlays.withIndex()) {
                map.overlays.add((insertAt + i + 1).coerceAtMost(map.overlays.size), o)
            }
            kmlOverlays[layer.id] = overlays
        }
        map.invalidate()
    }

    // Sync the north-lock toggle with osmdroid: when locked we snap mapOrientation
    // to 0 and strip the rotation-gesture overlay; when unlocked we install it so
    // the user can rotate the map with a two-finger twist.
    LaunchedEffect(mapRef.value, northLocked) {
        val map = mapRef.value ?: return@LaunchedEffect
        val rotCls = org.osmdroid.views.overlay.gestures.RotationGestureOverlay::class.java
        if (northLocked) {
            map.mapOrientation = 0f
            map.overlays.removeAll { rotCls.isInstance(it) }
            mapOrientation = 0f
        } else if (map.overlays.none { rotCls.isInstance(it) }) {
            val rot = org.osmdroid.views.overlay.gestures.RotationGestureOverlay(map)
            rot.isEnabled = true
            map.overlays.add(rot)
        }
        map.postInvalidate()
    }

    // Poll the live map orientation into Compose state so the compass needle
    // tracks two-finger rotation gestures. Cheap (one float read) and stops as
    // soon as the composition leaves.
    LaunchedEffect(mapRef.value) {
        val map = mapRef.value ?: return@LaunchedEffect
        while (true) {
            val cur = map.mapOrientation
            if (cur != mapOrientation) mapOrientation = cur
            delay(100)
        }
    }

    // ── Weather — RainViewer data fetch, auto-refreshed every 10 minutes ──
    LaunchedEffect(Unit) {
        while (true) {
            container.weatherRepository.fetchFrames().onSuccess { frames ->
                wxFrames       = frames.radarFrames
                wxNowcastStart = frames.nowcastStartIndex
                wxSatFrame     = frames.satFrame
                // Keep index in range; jump to latest observed frame on first load.
                if (wxFrameIndex !in frames.radarFrames.indices) {
                    wxFrameIndex = (frames.radarFrames.size - 1).coerceAtLeast(0)
                }
            }
            delay(10 * 60 * 1000L)
        }
    }

    // Advance animation frame every 500 ms while playing.
    LaunchedEffect(wxPlaying) {
        if (!wxPlaying) return@LaunchedEffect
        while (true) {
            delay(500)
            if (wxFrames.isNotEmpty()) wxFrameIndex = (wxFrameIndex + 1) % wxFrames.size
        }
    }

    // Radar tile overlay — rebuilds whenever the active frame or toggle changes.
    LaunchedEffect(mapRef.value, wxRadarActive, wxFrameIndex, wxFrames) {
        val map = mapRef.value ?: return@LaunchedEffect
        // Remove previous radar overlay.
        wxRadarOverlay.value?.let { map.overlays.remove(it) }
        wxRadarOverlay.value = null

        if (wxRadarActive && wxFrameIndex in wxFrames.indices) {
            val src      = com.arrow.tactical.map.RainViewerTileSource(wxFrames[wxFrameIndex].path)
            val provider = MapTileProviderBasic(context, src)
            val overlay  = com.arrow.tactical.map.WeatherTilesOverlay(provider, context, wxRadarOpacity).apply {
                loadingBackgroundColor = android.graphics.Color.TRANSPARENT
                loadingLineColor       = android.graphics.Color.TRANSPARENT
            }
            // Insert just above the MBTiles overlay (or at 0 when no MBTiles),
            // below satellite and all marker overlays.
            val satIdx = wxSatOverlay.value?.let { map.overlays.indexOf(it) } ?: -1
            val mbtIdx = mbtilesOverlay.value?.let { map.overlays.indexOf(it) } ?: -1
            val insertAt = when {
                satIdx >= 0 -> satIdx + 1
                mbtIdx >= 0 -> mbtIdx + 1
                else        -> 0
            }.coerceAtMost(map.overlays.size)
            map.overlays.add(insertAt, overlay)
            wxRadarOverlay.value = overlay
        }
        map.postInvalidate()
    }

    // Satellite tile overlay — rebuilds on toggle or new frame data.
    LaunchedEffect(mapRef.value, wxSatActive, wxSatFrame) {
        val map = mapRef.value ?: return@LaunchedEffect
        wxSatOverlay.value?.let { map.overlays.remove(it) }
        wxSatOverlay.value = null

        val frame = wxSatFrame
        if (wxSatActive && frame != null) {
            val src      = com.arrow.tactical.map.RainViewerTileSource(frame.path, isSatellite = true)
            val provider = MapTileProviderBasic(context, src)
            val overlay  = com.arrow.tactical.map.WeatherTilesOverlay(provider, context, wxSatOpacity).apply {
                loadingBackgroundColor = android.graphics.Color.TRANSPARENT
                loadingLineColor       = android.graphics.Color.TRANSPARENT
            }
            val mbtIdx   = mbtilesOverlay.value?.let { map.overlays.indexOf(it) } ?: -1
            val insertAt = (if (mbtIdx >= 0) mbtIdx + 1 else 0).coerceAtMost(map.overlays.size)
            map.overlays.add(insertAt, overlay)
            wxSatOverlay.value = overlay
        }
        map.postInvalidate()
    }

    // Opacity — update existing overlays without rebuilding tile sources.
    LaunchedEffect(wxRadarOpacity) {
        wxRadarOverlay.value?.overlayAlpha = wxRadarOpacity
        mapRef.value?.postInvalidate()
    }
    LaunchedEffect(wxSatOpacity) {
        wxSatOverlay.value?.overlayAlpha = wxSatOpacity
        mapRef.value?.postInvalidate()
    }

    // Load the list of base-map sources once. The selected one is remembered
    // across app launches via SettingsRepository; backend default ("osm" or the
    // first MBTiles) is used otherwise.
    LaunchedEffect(Unit) {
        val list  = container.mapSourceRepository.list()
        val saved = container.settingsRepository.currentBasemap()
        mapSources = list
        selectedMap = list.firstOrNull { it.name == saved }
                   ?: list.firstOrNull { it.is_default }
                   ?: list.firstOrNull()
    }

    // OSM is the permanent base layer. Any non-OSM selection is painted as a
    // TilesOverlay on top — where the MBTiles has a tile we see it, where it
    // doesn't (deduped empties, redacted areas, outside coverage / zoom range)
    // the transparent loading fill lets MAPNIK show through.
    LaunchedEffect(mapRef.value, selectedMap) {
        val map = mapRef.value ?: return@LaunchedEffect

        // 1. Reset the primary tile source/provider to OSM. Cheap to re-set on
        //    every change — OSMdroid no-ops if the source/provider is already
        //    correct after the first paint.
        map.setTileSource(BackendTileSource.OSM_DEFAULT)
        map.tileProvider = MapTileProviderBasic(context, BackendTileSource.OSM_DEFAULT)
        map.setMinZoomLevel(0.0)
        map.setMaxZoomLevel(19.0)

        // 2. Drop the previous MBTiles overlay if any.
        mbtilesOverlay.value?.let { old ->
            map.overlays.remove(old)
            runCatching { old.onDetach(map) }
        }
        mbtilesOverlay.value = null

        // 3. Build a new overlay for the selected MBTiles, if any.
        //    Local-file path → OSMdroid archive provider (fully offline).
        //    Otherwise the backend tile provider (online, JWT in URL).
        val src = selectedMap
        if (src != null && !src.url_template.startsWith("http")) {
            val localFile = container.mapSourceRepository.localFile(src.name)
            val ext = if (src.format.equals("jpeg", true)) "jpg" else src.format.lowercase()
            val overlayProvider: MapTileProviderBase = if (localFile != null) {
                val offlineSource = XYTileSource(
                    src.name, src.min_zoom, src.max_zoom, 256, ".$ext", arrayOf<String>(),
                )
                val archive = MBTilesFileArchive.getDatabaseFileArchive(localFile)
                val archiveProvider = MapTileFileArchiveProvider(
                    SimpleRegisterReceiver(context), offlineSource, arrayOf(archive),
                )
                MapTileProviderArray(
                    offlineSource, SimpleRegisterReceiver(context), arrayOf(archiveProvider),
                )
            } else {
                val token = container.tokenStore.current().orEmpty()
                val base  = container.settingsRepository.currentServerUrl()
                val backendSource = BackendTileSource(
                    sourceName = src.name,
                    title      = src.title,
                    minZoom    = src.min_zoom,
                    maxZoom    = src.max_zoom,
                    format     = src.format,
                    baseUrl    = base,
                    token      = token,
                )
                MapTileProviderBasic(context, backendSource)
            }
            val overlay = TilesOverlay(overlayProvider, context).apply {
                loadingBackgroundColor = android.graphics.Color.TRANSPARENT
                loadingLineColor       = android.graphics.Color.TRANSPARENT
            }
            // Index 0 → painted first among overlays, but still on top of the
            // base tile pane. Markers added later by other LaunchedEffects sit
            // above it.
            map.overlays.add(0, overlay)
            mbtilesOverlay.value = overlay
        }

        map.invalidate()
    }

    // Auto-center on own position the first time both meId and a position are available.
    // Key on meId too — operators often loads before authRepository.me() returns.
    LaunchedEffect(operators, meId) {
        if (hasAutocentered) return@LaunchedEffect
        val id = meId ?: return@LaunchedEffect
        val me = operators.find { it.id == id } ?: return@LaunchedEffect
        if (me.latitude == null || me.longitude == null) return@LaunchedEffect
        mapRef.value?.controller?.animateTo(GeoPoint(me.latitude, me.longitude), 15.0, null)
        hasAutocentered = true
    }

    LaunchedEffect(operators, enemies, fireMissions, cbrnReports, cbrnVisible, meId, overlayMode, tgVisible, myPlatoonIds, savedOverlays, activeOverlays, visibility, zoomLevel, strikePkgEntities) {
        val map = mapRef.value ?: return@LaunchedEffect
        val res = map.resources
        val currentMeId = meId

        // Wipe ALL transient overlays we own (markers + tactical graphic
        // polylines/polygons) before rebuilding.
        map.overlays.removeAll {
            !com.arrow.tactical.kml.isKmlOverlay(it) &&
            !com.arrow.tactical.alerts.AlertMarker.isAlertMarker(it) && (
                it is Marker || it is org.osmdroid.views.overlay.Polyline ||
                it is org.osmdroid.views.overlay.Polygon
            )
        }

        // Admin-axis filter
        val visibleOps = if (!visibility.operators) emptyList() else when (overlayMode) {
            OverlayMode.ALL         -> operators
            OverlayMode.NONE        -> emptyList()
            OverlayMode.ENEMIES     -> emptyList()
            OverlayMode.OWN_PLATOON -> operators.filter { it.id in myPlatoonIds || it.id == currentMeId }
        }
        val showLegacyHostiles = visibility.tacticalObjects &&
            (overlayMode == OverlayMode.ALL || overlayMode == OverlayMode.ENEMIES)

        val overlayAllowed: Set<Int>? = when {
            !visibility.overlays      -> null
            activeOverlays.isEmpty()  -> null
            else -> savedOverlays.asSequence()
                .filter { it.id in activeOverlays }
                .flatMap { it.objectIds.asSequence() }
                .toSet()
        }
        fun passesOverlay(id: Int): Boolean =
            overlayAllowed == null || id in overlayAllowed

        val visibleEnemies = if (showLegacyHostiles)
            enemies.filter {
                !MilSymbolRenderer.isTacticalGraphic(it.type) &&
                !MilSymbolRenderer.isTacticalLineOrPolygon(it.type) &&
                passesOverlay(it.id)
            }
        else emptyList()

        // ── Clustering logic ────────────────────────────────────────────────
        val clusterThreshold = 13f
        val clusteredOps = if (zoomLevel < clusterThreshold) {
            clusterItems(visibleOps, zoomLevel, { it.latitude }, { it.longitude })
        } else {
            visibleOps.map { listOf(it) }
        }
        val clusteredEnemies = if (zoomLevel < clusterThreshold) {
            clusterItems(visibleEnemies, zoomLevel, { it.latitude }, { it.longitude })
        } else {
            visibleEnemies.map { listOf(it) }
        }

        for (cluster in clusteredOps) {
            if (cluster.isEmpty()) continue
            val first = cluster[0]
            val lat = first.latitude ?: continue
            val lon = first.longitude ?: continue

            if (cluster.size > 1) {
                // Render a cluster marker for friendlies
                Marker(map).apply {
                    position = GeoPoint(lat, lon)
                    icon = MilSymbolRenderer.cluster(res, cluster.size, Color(0xFF3B82F6).toArgb())
                    title = "${cluster.size} Friendlies"
                    setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                    map.overlays.add(this)
                }
            } else {
                val isMe = first.id == currentMeId
                val marker = Marker(map).apply {
                    position = GeoPoint(lat, lon)
                    title    = if (isMe) "📍 You — ${first.callsign}" else "${first.callsign}  ·  ${first.rank}"
                    snippet  = "${first.role}${if (first.online) " · online" else " · offline"}" +
                               if (first.positionSource == "ATAK") "  ·  📡 ATAK device" else ""
                    icon     = MilSymbolRenderer.friendly(res, first, isMe)
                    if (isMe) setAnchor(Marker.ANCHOR_CENTER, 0.39f)
                    else      setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                    map.overlays.add(this)
                }
                if (!isMe) {
                    val sidc = if (first.role.equals("BATTLE_CAPTAIN", true)) "SFGPUCI----E"
                               else                                       "SFGPUCI-----"
                    scope.launch {
                        container.milsymRenderer.symbol(sidc, mapOf("size" to 28, "uniqueDesignation" to first.callsign))?.let { r ->
                            marker.icon = r.drawable
                            marker.setAnchor(r.anchorX, r.anchorY)
                            map.invalidate()
                        }
                    }
                }
            }
        }

        for (cluster in clusteredEnemies) {
            if (cluster.isEmpty()) continue
            val first = cluster[0]
            val lat = first.latitude
            val lon = first.longitude

            if (cluster.size > 1) {
                // Render a cluster marker for hostiles
                Marker(map).apply {
                    position = GeoPoint(lat, lon)
                    icon = MilSymbolRenderer.cluster(res, cluster.size, Color(0xFFEF4444).toArgb())
                    title = "${cluster.size} Hostiles"
                    setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                    map.overlays.add(this)
                }
            } else {
                if (first.type == "OBJECTIVE") {
                    val notes  = first.notes
                    val nl     = notes.indexOf('\n')
                    val titleS = if (nl >= 0) notes.substring(0, nl) else notes
                    val rest   = if (nl >= 0) notes.substring(nl + 1) else ""
                    val descS  = rest.lineSequence().filterNot { it.startsWith("MGRS:") }
                                      .joinToString("\n").trim()
                    Marker(map).apply {
                        position = GeoPoint(lat, lon)
                        title    = "🚩 ${titleS.ifBlank { "Objective" }}"
                        snippet  = descS.ifBlank { "(no description)" }
                        icon     = MilSymbolRenderer.objective(res)
                        setAnchor(Marker.ANCHOR_BOTTOM, Marker.ANCHOR_BOTTOM)
                        setOnMarkerClickListener { m, _ ->
                            selectedObjective = first
                            m.showInfoWindow()
                            true
                        }
                        map.overlays.add(this)
                    }
                } else {
                    val type = EnemyType.resolve(first.type, first.symbolCode)
                    val marker = Marker(map).apply {
                        position = GeoPoint(lat, lon)
                        title    = type.label
                        snippet  = first.notes.ifBlank { "SIDC: ${first.symbolCode}" }
                        icon     = if (type == EnemyType.POI) MilSymbolRenderer.poi(res)
                                   else MilSymbolRenderer.hostile(res, type)
                        setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                        setOnMarkerClickListener { m, _ ->
                            // During move-mode let the tap fall through to singleTapConfirmedHelper
                            if (movingTacticalObjState.value != null) return@setOnMarkerClickListener false
                            val screenPt = android.graphics.Point()
                            map.projection?.toPixels(m.position, screenPt)
                            selectedTacticalObj = first
                            selectedTacticalObjScreen = Offset(
                                screenPt.x.toFloat().takeIf { it != 0f } ?: (map.width / 2f),
                                screenPt.y.toFloat().takeIf { it != 0f } ?: (map.height / 2f),
                            )
                            true
                        }
                        map.overlays.add(this)
                    }
                    if (type != EnemyType.POI) {
                        val sidc = if (first.symbolCode.length >= 10) first.symbolCode else type.sidc
                        scope.launch {
                            container.milsymRenderer.symbol(sidc, mapOf("size" to 30))?.let { r ->
                                marker.icon = r.drawable
                                marker.setAnchor(r.anchorX, r.anchorY)
                                map.invalidate()
                            }
                        }
                    }
                }
            }
        }

        val visibleGraphics = if (tgVisible && visibility.tacticalObjects)
            enemies.filter {
                (MilSymbolRenderer.isTacticalGraphic(it.type) ||
                 MilSymbolRenderer.isTacticalLineOrPolygon(it.type)) &&
                passesOverlay(it.id)
            }
        else emptyList()

        for (g in visibleGraphics) {
            renderTacticalGraphic(map, res, g)
        }

        if (overlayMode != OverlayMode.NONE && visibility.fireMissions) {
            for (fm in fireMissions.filter { it.status != "CANCELLED" }) {
                val mgrsStr = runCatching {
                    com.arrow.tactical.network.MgrsConverter.encode(fm.latitude, fm.longitude)
                }.getOrDefault("%.4f, %.4f".format(fm.latitude, fm.longitude))
                Marker(map).apply {
                    position = GeoPoint(fm.latitude, fm.longitude)
                    title    = "🎯 ${fm.missionType.replace('_', ' ')} — ${fm.status}"
                    snippet  = "$mgrsStr · ${fm.ammunition} · ${fm.quantity} rnd"
                    icon     = MilSymbolRenderer.fireMission(res, fm.missionType, fm.status)
                    setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                    map.overlays.add(this)
                }
            }
        }

        if (cbrnVisible && visibility.reports) {
            for ((_, payload) in cbrnReports) {
                for (ov in com.arrow.tactical.cbrn.buildCbrnOverlays(map, res, payload)) {
                    map.overlays.add(ov)
                }
            }
        }

        // ── Strike Package map layer ──────────────────────────────────────────
        for (entity in strikePkgEntities) {
            val bundle = container.strikePackageRepository.parseBundleJson(entity.bundleJson)
                ?: continue
            val pkgLabel = bundle.name.take(12)
            val assets   = bundle.assets

            // Primary target
            if (bundle.targetLat != null && bundle.targetLon != null) {
                Marker(map).apply {
                    position = GeoPoint(bundle.targetLat, bundle.targetLon)
                    title    = "TARGET — ${bundle.name}"
                    snippet  = bundle.targetDescription.ifBlank { "Strike package target" }
                    icon     = MilSymbolRenderer.strikeTarget(res, "TGT")
                    setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                    map.overlays.add(this)
                }
            }

            // Drone loiter areas
            for (drone in assets.drones) {
                val lat = drone.loiterLat ?: continue
                val lon = drone.loiterLon ?: continue
                Marker(map).apply {
                    position = GeoPoint(lat, lon)
                    title    = "UAS — ${drone.callsign.ifBlank { drone.platform }}"
                    snippet  = "Loiter area · $pkgLabel${if (drone.feedUrl.isNotEmpty()) " · feed available" else ""}"
                    icon     = MilSymbolRenderer.drone(res, drone.callsign)
                    setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                    map.overlays.add(this)
                }
            }

            // CAS / air support (placed at target; offset slightly per aircraft)
            val targetLat = bundle.targetLat
            val targetLon = bundle.targetLon
            if (targetLat != null && targetLon != null) {
                for ((i, cas) in assets.airSupport.withIndex()) {
                    val latOff = targetLat + i * 0.0004
                    Marker(map).apply {
                        position = GeoPoint(latOff, targetLon)
                        title    = "CAS — ${cas.callsign.ifBlank { cas.aircraft }}"
                        snippet  = "${cas.ordnance} · ${cas.stationTimeMin} min on station · $pkgLabel"
                        icon     = MilSymbolRenderer.cas(res, cas.callsign)
                        setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                        map.overlays.add(this)
                    }
                }

                // EW assets (placed at target; offset slightly per asset)
                for ((i, ew) in assets.electronicWarfare.withIndex()) {
                    val lonOff = targetLon + i * 0.0004
                    Marker(map).apply {
                        position = GeoPoint(targetLat, lonOff)
                        title    = "EW — ${ew.callsign.ifBlank { ew.system }}"
                        snippet  = "${ew.objective} · ${ew.frequencyBands} · $pkgLabel"
                        icon     = MilSymbolRenderer.ewAsset(res, ew.callsign)
                        setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                        map.overlays.add(this)
                    }
                }
            }

            // Sniper hides
            for (sn in assets.sniperOverwatch) {
                val lat = sn.positionLat ?: continue
                val lon = sn.positionLon ?: continue
                Marker(map).apply {
                    position = GeoPoint(lat, lon)
                    title    = "SNIPER — ${sn.callsign}"
                    snippet  = "Sector: ${sn.sectorOfFire} · ${sn.engagementCriteria} · $pkgLabel"
                    icon     = MilSymbolRenderer.sniperHide(res, sn.callsign)
                    setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                    map.overlays.add(this)
                }
            }

            // Assigned operators (highlight with role/callsign if they have a position)
            for (op in bundle.operators) {
                val lat = op.latitude ?: continue
                val lon = op.longitude ?: continue
                val fakeDto = com.arrow.tactical.network.OperatorDto(
                    id = op.id, callsign = op.callsign, rank = op.rank,
                    status = op.status, role = op.role, online = op.status == "ONLINE",
                    latitude = lat, longitude = lon,
                )
                Marker(map).apply {
                    position = GeoPoint(lat, lon)
                    title    = "${op.callsign} · ${op.rank}"
                    snippet  = "Strike package: $pkgLabel · ${op.role}"
                    icon     = MilSymbolRenderer.friendly(res, fakeDto)
                    setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                    map.overlays.add(this)
                }
            }
        }

        map.invalidate()
    }

    val isLoggedIn = meId != null

    // AndroidView (OSMdroid) must come FIRST so it renders at the Android-View layer.
    // All Compose content placed after it in the Box renders on the Compose canvas
    // layer which always sits on top of embedded Android Views.
    Box(modifier = Modifier.fillMaxSize()) {

        // ── Map — full screen, Android View layer ─────────────────────────
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { ctx ->
                MapView(ctx).apply {
                    layoutParams = android.view.ViewGroup.LayoutParams(
                        android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                        android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                    )
                    setTileSource(TileSourceFactory.MAPNIK)
                    setMultiTouchControls(true)
                    val mission = container.missionRepository.activeMission.value
                    if (mission?.mapCenterLat != null && mission.mapCenterLng != null) {
                        controller.setZoom(mission.mapZoom.toDouble())
                        controller.setCenter(GeoPoint(mission.mapCenterLat, mission.mapCenterLng))
                    } else {
                        controller.setZoom(8.0)
                        controller.setCenter(GeoPoint(50.85, 4.35))
                    }

                    val events = MapEventsOverlay(object : MapEventsReceiver {
                        override fun singleTapConfirmedHelper(p: GeoPoint?): Boolean {
                            p ?: return false
                            // Move mode: relocate the selected tactical object to the tapped point.
                            val moving = movingTacticalObjState.value
                            if (moving != null) {
                                movingTacticalObjState.value = null
                                scope.launch {
                                    container.tacticalRepository.updatePosition(moving.id, p.latitude, p.longitude)
                                }
                                return true
                            }
                            // In measure mode, taps populate point 1 / point 2 instead of opening the radial menu.
                            if (measureModeState.value) {
                                when {
                                    measureFirstState.value == null  -> measureFirstState.value = p
                                    measureSecondState.value == null -> measureSecondState.value = p
                                    else -> { // both set — start a fresh measurement from this tap
                                        measureFirstState.value  = p
                                        measureSecondState.value = null
                                    }
                                }
                                return true
                            }
                            // Capture both geo point and screen pixel position
                            val px = projection?.toPixels(p, android.graphics.Point())
                            pendingPointState.value     = p
                            pendingScreenPosState.value = if (px != null)
                                Offset(px.x.toFloat(), px.y.toFloat()) else null
                            // Reset form state
                            notes           = ""
                            selectedType    = EnemyType.INFANTRY
                            submitError     = null
                            pendingPhotoId  = null
                            pendingPhotoUri = null
                            return true
                        }
                        override fun longPressHelper(p: GeoPoint?): Boolean = false
                    })
                    // Explicit ``this.`` so any future outer-scope variable
                    // named ``overlays`` can't shadow MapView's member list.
                    this.overlays.add(0, events)
                    addMapListener(object : org.osmdroid.events.MapListener {
                        override fun onScroll(event: org.osmdroid.events.ScrollEvent?): Boolean = false
                        override fun onZoom(event: org.osmdroid.events.ZoomEvent?): Boolean {
                            zoomLevel = event?.zoomLevel?.toFloat() ?: zoomLevel
                            return false
                        }
                    })
                }.also { mapRef.value = it }
            },
            update = { /* markers managed by LaunchedEffect above */ },
        )

        // ── Old status + overlay bar — kept for stream toggle, locate-me and
        // overlay-mode chips, but rendered as a compact strip below the
        // SitaWare chrome. Set `showLegacyControls = false` to hide entirely.
        val showLegacyControls = false   // merged into the SitaWare top bar
        val online = operators.count { it.online }
        val dotColor = when (serverOnline) {
            true  -> Color(0xFF22C55E)
            false -> MaterialTheme.colorScheme.error
            null  -> Color(0xFFFBBF24)
        }
        if (showLegacyControls) Row(
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.TopStart)
                .offset(y = 92.dp)               // clear the SitaWare chrome above
                .background(Color(0xE50D1117))   // 90 % opaque dark
                .padding(horizontal = 8.dp, vertical = 3.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Canvas(Modifier.size(9.dp)) { drawCircle(dotColor) }

            Text(
                text  = if (serverOnline == false) "OFFLINE"
                        else "$online / ${operators.size} online",
                style = MaterialTheme.typography.labelMedium.copy(
                    fontWeight    = FontWeight.Bold,
                    letterSpacing = 0.5.sp,
                ),
                color = if (serverOnline == false) MaterialTheme.colorScheme.error
                        else Color(0xFFE2E8F0),
            )

            Spacer(Modifier.weight(1f))

            listOf(
                OverlayMode.ALL         to "All",
                OverlayMode.NONE        to "None",
                OverlayMode.ENEMIES     to "Enemy",
                OverlayMode.OWN_PLATOON to "Own Plt",
            ).forEach { (mode, label) ->
                val active = overlayMode == mode
                Box(
                    modifier = Modifier
                        .clickable { overlayMode = mode }
                        .background(
                            if (active) Color(0xFF1E3A2F) else Color(0xFF1A2233),
                            RoundedCornerShape(3.dp),
                        )
                        .then(
                            if (active) Modifier.border(0.5.dp, Color(0xFF34D399), RoundedCornerShape(3.dp))
                            else        Modifier.border(0.5.dp, Color(0xFF2A3142), RoundedCornerShape(3.dp))
                        )
                        .padding(horizontal = 6.dp, vertical = 2.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text  = label,
                        style = MaterialTheme.typography.labelSmall.copy(fontSize = 11.sp),
                        color = if (active) Color(0xFF34D399) else Color(0xFFCBD5E1),
                    )
                }
            }
            // Independent Tactical Graphics layer — orange when on, dim when off.
            Box(
                modifier = Modifier
                    .clickable { tgVisible = !tgVisible }
                    .background(
                        if (tgVisible) Color(0xFF3F2A14) else Color(0xFF1A2233),
                        RoundedCornerShape(3.dp),
                    )
                    .then(
                        if (tgVisible) Modifier.border(0.5.dp, Color(0xFFF59E0B), RoundedCornerShape(3.dp))
                        else           Modifier.border(0.5.dp, Color(0xFF2A3142), RoundedCornerShape(3.dp))
                    )
                    .padding(horizontal = 6.dp, vertical = 2.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text  = "📐 Gfx",
                    style = MaterialTheme.typography.labelSmall.copy(fontSize = 11.sp),
                    color = if (tgVisible) Color(0xFFFBBF24) else Color(0xFFCBD5E1),
                )
            }

            // 📡 Stream toggle — Material3 IconToggleButton so checked/unchecked
            // state is visually distinct (red filled background while live).
            FilledIconToggleButton(
                checked = isStreaming,
                onCheckedChange = { wantOn ->
                    android.util.Log.i("StreamButton",
                        "toggle wantOn=$wantOn serviceFlag=" +
                        "${com.arrow.tactical.stream.CameraStreamService.isStreaming.get()}")
                    if (!wantOn) {
                        // Going OFF: stop the service
                        context.startService(
                            android.content.Intent(context,
                                com.arrow.tactical.stream.CameraStreamService::class.java)
                                .setAction(com.arrow.tactical.stream.CameraStreamService.ACTION_STOP)
                        )
                        isStreaming = false
                    } else {
                        // Going ON: re-sync against the live service flag, then start
                        isStreaming = false
                        val hasPerm = androidx.core.content.ContextCompat.checkSelfPermission(
                            context, android.Manifest.permission.CAMERA
                        ) == android.content.pm.PackageManager.PERMISSION_GRANTED
                        if (hasPerm) scope.launch { startStream() }
                        else         cameraPermLauncher.launch(android.Manifest.permission.CAMERA)
                    }
                },
                modifier = Modifier.size(32.dp),
                colors = IconButtonDefaults.filledIconToggleButtonColors(
                    containerColor        = Color(0xFF1A2233),
                    contentColor          = Color(0xFFCBD5E1),
                    checkedContainerColor = Color(0xFFEF4444),
                    checkedContentColor   = Color.White,
                ),
            ) {
                Icon(
                    if (isStreaming) Icons.Filled.VideocamOff else Icons.Filled.Videocam,
                    contentDescription = if (isStreaming) "Stop stream" else "Start stream",
                    modifier = Modifier.size(18.dp),
                )
            }

            IconButton(
                onClick = {
                    val id = meId ?: return@IconButton
                    val me = operators.find { it.id == id } ?: return@IconButton
                    if (me.latitude != null && me.longitude != null) {
                        mapRef.value?.controller?.animateTo(
                            GeoPoint(me.latitude, me.longitude), 15.0, null
                        )
                    }
                },
                modifier = Modifier.size(24.dp),
            ) {
                Icon(Icons.Filled.MyLocation, contentDescription = "Locate me",
                     modifier = Modifier.size(18.dp), tint = Color(0xFFCBD5E1))
            }
        }

        // ── SitaWare-Edge style chrome overlay ────────────────────────────
        val me = meId?.let { id -> operators.find { it.id == id } }
        val mgrs = if (me?.latitude != null && me.longitude != null)
            com.arrow.tactical.network.MgrsConverter.encode(me.latitude, me.longitude, 5)
        else "—"
        val alertsList = remember { mutableStateOf<List<com.arrow.tactical.network.AlertDto>>(emptyList()) }
        LaunchedEffect(Unit) {
            while (true) {
                container.alertRepository.list().onSuccess { alertsList.value = it }
                delay(15_000)
            }
        }
        val activeAlerts = alertsList.value.count { it.status == "ACTIVE" }
        val notif = NotificationCounts(
            critical = activeAlerts,
            warning  = enemies.count { it.type in setOf("ENEMY","ATK_AXIS","AMBUSH","FLET") && (it.affiliation == "ENEMY" || it.type == "ENEMY") }.coerceAtMost(99),
            info     = fireMissions.count { it.status == "PENDING" || it.status == "IN_PROGRESS" },
            routine  = (operators.size - operators.count { it.online }).coerceAtLeast(0),
        )
        // Banner visibility — simple boolean. Re-appears whenever notif.total
        // changes; clicking the ✓ in the banner hides it immediately; a
        // LaunchedEffect auto-hides it after 5 s.
        var bannerVisible by remember { mutableStateOf(notif.total > 0) }
        LaunchedEffect(notif.total) {
            if (notif.total > 0) {
                bannerVisible = true
                delay(5_000)
                bannerVisible = false
            } else {
                bannerVisible = false
            }
        }
        val showBanner = bannerVisible && notif.total > 0
        androidx.compose.animation.AnimatedVisibility(
            visible = !topBarCollapsed,
            modifier = Modifier.fillMaxWidth().align(Alignment.TopStart),
            enter = androidx.compose.animation.slideInHorizontally(initialOffsetX = { -it }) +
                    androidx.compose.animation.fadeIn(),
            exit  = androidx.compose.animation.slideOutHorizontally(targetOffsetX = { -it }) +
                    androidx.compose.animation.fadeOut(),
        ) {
        Column(modifier = Modifier.fillMaxWidth()) {
            SitawareTopBar(
                brand   = "ARROW",
                mgrs    = mgrs,
                online  = serverOnline == true,
                alertCount = activeAlerts,
                chatCount  = 0,
                onMenu       = onOpenDrawer,
                onAlerts     = { /* TODO: open alerts tab */ },
                onChat       = { container.signalNavigateToChat() },
                onStatus     = { /* TODO: status panel */ },
                onOverflow   = { /* TODO: overflow menu */ },
                overlayChips = listOf(
                    OverlayChip("ALL",         "All",     overlayMode == OverlayMode.ALL),
                    OverlayChip("NONE",        "None",    overlayMode == OverlayMode.NONE),
                    OverlayChip("ENEMIES",     "Enemy",   overlayMode == OverlayMode.ENEMIES),
                    OverlayChip("OWN_PLATOON", "Own Plt", overlayMode == OverlayMode.OWN_PLATOON),
                ),
                onOverlayChip = { key ->
                    overlayMode = when (key) {
                        "ALL"         -> OverlayMode.ALL
                        "NONE"        -> OverlayMode.NONE
                        "ENEMIES"     -> OverlayMode.ENEMIES
                        "OWN_PLATOON" -> OverlayMode.OWN_PLATOON
                        else          -> overlayMode
                    }
                },
                gfxOn           = tgVisible,
                onToggleGfx     = { tgVisible = !tgVisible },
                cbrnOn          = cbrnVisible,
                onToggleCbrn    = { cbrnVisible = !cbrnVisible },
                kmlActiveCount  = kmlLayers.count { it.visible && it.id !in kmlLocallyHidden },
                onToggleKml     = {
                    kmlPanelOpen = !kmlPanelOpen
                    if (kmlPanelOpen) overlayPanelOpen = false
                },
                overlayActiveCount = activeOverlays.size,
                onToggleOverlays   = {
                    overlayPanelOpen = !overlayPanelOpen
                    if (overlayPanelOpen) { kmlPanelOpen = false; wxPanelOpen = false }
                },
                weatherOpen     = wxPanelOpen,
                onToggleWeather = {
                    wxPanelOpen = !wxPanelOpen
                    if (wxPanelOpen) {
                        kmlPanelOpen = false; overlayPanelOpen = false
                        if (wxFrames.isNotEmpty()) {
                            // Frames already loaded — enable radar immediately.
                            if (!wxRadarActive) wxRadarActive = true
                        } else {
                            // Frames not yet loaded (first open before fetch finished) —
                            // trigger an immediate fetch then auto-enable.
                            scope.launch {
                                container.weatherRepository.fetchFrames().onSuccess { frames ->
                                    wxFrames       = frames.radarFrames
                                    wxNowcastStart = frames.nowcastStartIndex
                                    wxSatFrame     = frames.satFrame
                                    wxFrameIndex   = (frames.radarFrames.size - 1).coerceAtLeast(0)
                                    if (!wxRadarActive) wxRadarActive = true
                                }
                            }
                        }
                    }
                },
                onCollapseBar   = { topBarCollapsed = true },
                isStreaming     = isStreaming,
                onToggleStream  = {
                    val wantOn = !isStreaming
                    if (!wantOn) {
                        context.startService(
                            android.content.Intent(context,
                                com.arrow.tactical.stream.CameraStreamService::class.java)
                                .setAction(com.arrow.tactical.stream.CameraStreamService.ACTION_STOP)
                        )
                        isStreaming = false
                    } else {
                        isStreaming = false
                        val hasPerm = androidx.core.content.ContextCompat.checkSelfPermission(
                            context, android.Manifest.permission.CAMERA
                        ) == android.content.pm.PackageManager.PERMISSION_GRANTED
                        if (hasPerm) scope.launch { startStream() }
                        else         cameraPermLauncher.launch(android.Manifest.permission.CAMERA)
                    }
                },
                onLocateMe = {
                    val opMe = meId?.let { id -> operators.find { it.id == id } }
                    if (opMe?.latitude != null && opMe.longitude != null) {
                        mapRef.value?.controller?.animateTo(
                            GeoPoint(opMe.latitude, opMe.longitude), 16.0, null
                        )
                    }
                },
            )
            if (showBanner) {
                SitawareNotificationBanner(
                    counts    = notif,
                    onDismiss = { bannerVisible = false },
                )
            }
        }
        }   // AnimatedVisibility(!topBarCollapsed)

        // Small floating handle shown when the bar is collapsed — taps restore it.
        androidx.compose.animation.AnimatedVisibility(
            visible = topBarCollapsed,
            modifier = Modifier.align(Alignment.TopStart),
            enter = androidx.compose.animation.slideInHorizontally(initialOffsetX = { -it }) +
                    androidx.compose.animation.fadeIn(),
            exit  = androidx.compose.animation.slideOutHorizontally(targetOffsetX = { -it }) +
                    androidx.compose.animation.fadeOut(),
        ) {
            SitawareCollapsedHandle(onExpand = { topBarCollapsed = false })
        }

        // ── KML layer panel — slides in from the right under the top bar.
        //    Top offset clears both the SitaWare chrome and the base-layer
        //    chip when those are present, so the chip stays tappable.
        val kmlPanelTop = when {
            topBarCollapsed       -> 12.dp
            mapSources.size > 1   -> 136.dp   // 92 (bar) + 36 (chip) + 8 (gap)
            else                  -> 92.dp
        }
        androidx.compose.animation.AnimatedVisibility(
            visible = kmlPanelOpen,
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(top = kmlPanelTop, end = 12.dp),
            enter = androidx.compose.animation.slideInHorizontally(initialOffsetX = { it }) +
                    androidx.compose.animation.fadeIn(),
            exit  = androidx.compose.animation.slideOutHorizontally(targetOffsetX = { it }) +
                    androidx.compose.animation.fadeOut(),
        ) {
            com.arrow.tactical.kml.ui.KmlMapPanel(
                // Apply the local-hide set to the panel's view so the Switch
                // reflects what the operator actually sees on the map.
                layers   = kmlLayers.map { l ->
                    if (l.id in kmlLocallyHidden) l.copy(visible = false) else l
                },
                onClose  = { kmlPanelOpen = false },
                onToggle = { id, wantOn ->
                    // Local-only hide: no server call, so every role can do it
                    // and the toggle is instant. The server's ``visible`` flag
                    // stays untouched and remains the source of truth for the
                    // "shared" default.
                    kmlLocallyHidden = if (wantOn) kmlLocallyHidden - id
                                       else        kmlLocallyHidden + id
                    Result.success(Unit)
                },
            )
        }

        // ── Overlay panel — saved bundles of tactical objects (right side).
        //    Stacked above the KML panel so the two never overlap; we shift
        //    the KML panel down only when the overlay panel is also showing.
        androidx.compose.animation.AnimatedVisibility(
            visible = overlayPanelOpen,
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(top = kmlPanelTop, end = 12.dp),
            enter = androidx.compose.animation.slideInHorizontally(initialOffsetX = { it }) +
                    androidx.compose.animation.fadeIn(),
            exit  = androidx.compose.animation.slideOutHorizontally(targetOffsetX = { it }) +
                    androidx.compose.animation.fadeOut(),
        ) {
            com.arrow.tactical.overlays.ui.OverlayMapPanel(
                overlays  = savedOverlays,
                activeIds = activeOverlays,
                onToggle  = { id, on ->
                    activeOverlays = if (on) activeOverlays + id else activeOverlays - id
                },
                onClose   = { overlayPanelOpen = false },
            )
        }

        // ── Weather panel — slides in from the right, stacks alongside KML/Overlay panels.
        androidx.compose.animation.AnimatedVisibility(
            visible = wxPanelOpen,
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(top = kmlPanelTop, end = 12.dp),
            enter = androidx.compose.animation.slideInHorizontally(initialOffsetX = { it }) +
                    androidx.compose.animation.fadeIn(),
            exit  = androidx.compose.animation.slideOutHorizontally(targetOffsetX = { it }) +
                    androidx.compose.animation.fadeOut(),
        ) {
            WeatherPanel(
                radarFrames       = wxFrames,
                nowcastStartIndex = wxNowcastStart,
                currentFrameIndex = wxFrameIndex,
                radarActive       = wxRadarActive,
                radarOpacity      = wxRadarOpacity,
                playing           = wxPlaying,
                satActive         = wxSatActive,
                satOpacity        = wxSatOpacity,
                hasSat            = wxSatFrame != null,
                onClose           = { wxPanelOpen = false },
                onToggleRadar     = { wxRadarActive = it },
                onRadarOpacity    = { wxRadarOpacity = it },
                onTogglePlay      = { wxPlaying = !wxPlaying },
                onPrev            = {
                    wxPlaying = false
                    if (wxFrames.isNotEmpty()) wxFrameIndex = (wxFrameIndex - 1 + wxFrames.size) % wxFrames.size
                },
                onNext            = {
                    wxPlaying = false
                    if (wxFrames.isNotEmpty()) wxFrameIndex = (wxFrameIndex + 1) % wxFrames.size
                },
                onSeek            = { idx ->
                    wxPlaying = false
                    wxFrameIndex = idx.coerceIn(0, (wxFrames.size - 1).coerceAtLeast(0))
                },
                onToggleSat       = { wxSatActive = it },
                onSatOpacity      = { wxSatOpacity = it },
                onRefresh         = {
                    scope.launch {
                        container.weatherRepository.fetchFrames().onSuccess { frames ->
                            wxFrames       = frames.radarFrames
                            wxNowcastStart = frames.nowcastStartIndex
                            wxSatFrame     = frames.satFrame
                            wxFrameIndex   = (frames.radarFrames.size - 1).coerceAtLeast(0)
                        }
                    }
                },
            )
        }

        // ── Base-layer switcher — small chip + dropdown anchored top-right
        // below the SitaWare top bar. Hidden when only one source is known.
        if (mapSources.size > 1) {
            Box(
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(top = 92.dp, end = 12.dp),
            ) {
                FilledIconButton(
                    onClick = { layerMenuOpen = true },
                    modifier = Modifier.size(36.dp),
                    colors = IconButtonDefaults.filledIconButtonColors(
                        containerColor = Color(0xE50F2540),
                        contentColor   = Color(0xFFE2E8F0),
                    ),
                ) {
                    Icon(Icons.Filled.Layers, contentDescription = "Map layer",
                         modifier = Modifier.size(18.dp))
                }
                DropdownMenu(
                    expanded = layerMenuOpen,
                    onDismissRequest = { layerMenuOpen = false },
                ) {
                    for (src in mapSources) {
                        val active = src.name == selectedMap?.name
                        DropdownMenuItem(
                            text = {
                                Text(
                                    text = (if (active) "● " else "  ") + src.title,
                                    color = if (active) Color(0xFF34D399) else Color.Unspecified,
                                )
                            },
                            onClick = {
                                layerMenuOpen = false
                                if (!active) {
                                    selectedMap = src
                                    scope.launch { container.settingsRepository.setBasemap(src.name) }
                                }
                            },
                        )
                    }
                }
            }
        }

        // ── Compass + north-lock — top-left, below the SitaWare chrome ───
        // The needle always points to true North on the ground: its rendering
        // is rotated by -mapOrientation so it cancels out the map rotation.
        Column(
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(start = 12.dp, top = 92.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(
                modifier = Modifier
                    .size(48.dp)
                    .clip(CircleShape)
                    .background(Color(0xE50F2540))
                    .border(1.dp, Color(0xFF334155), CircleShape)
                    .clickable {
                        mapRef.value?.let {
                            it.mapOrientation = 0f
                            it.postInvalidate()
                        }
                        mapOrientation = 0f
                    },
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    modifier = Modifier
                        .size(44.dp)
                        .rotate(-mapOrientation),
                    contentAlignment = Alignment.Center,
                ) {
                    Canvas(modifier = Modifier.size(40.dp)) {
                        val w = size.width
                        val h = size.height
                        val north = Path().apply {
                            moveTo(w / 2f, h * 0.08f)
                            lineTo(w * 0.62f, h * 0.50f)
                            lineTo(w / 2f, h * 0.42f)
                            lineTo(w * 0.38f, h * 0.50f)
                            close()
                        }
                        drawPath(north, Color(0xFFEF4444))
                        val south = Path().apply {
                            moveTo(w / 2f, h * 0.92f)
                            lineTo(w * 0.62f, h * 0.50f)
                            lineTo(w / 2f, h * 0.58f)
                            lineTo(w * 0.38f, h * 0.50f)
                            close()
                        }
                        drawPath(south, Color(0xFFCBD5E1))
                    }
                    Text(
                        text = "N",
                        color = Color.White,
                        fontSize = 9.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.align(Alignment.TopCenter),
                    )
                }
            }
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape)
                    .background(if (northLocked) Color(0xFF1E3A2F) else Color(0xE50F2540))
                    .border(
                        1.dp,
                        if (northLocked) Color(0xFF34D399) else Color(0xFF334155),
                        CircleShape,
                    )
                    .clickable { northLocked = !northLocked },
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = "N⇧",
                    color = if (northLocked) Color(0xFF34D399) else Color(0xFFCBD5E1),
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
            // Go To — navigate to MGRS / lat-lon / address
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape)
                    .background(Color(0xE50F2540))
                    .border(1.dp, Color(0xFF334155), CircleShape)
                    .clickable { goToOpen = true },
                contentAlignment = Alignment.Center,
            ) {
                Text("🔍", fontSize = 16.sp)
            }
        }

        // ── Go To dialog ──────────────────────────────────────────────────
        if (goToOpen) {
            GoToDialog(
                onDismiss = { goToOpen = false },
                onNavigate = { point, label ->
                    goToOpen = false
                    val map = mapRef.value ?: return@GoToDialog
                    // Remove previous Go To pin if any
                    goToMarker.value?.let { map.overlays.remove(it) }
                    map.controller.animateTo(point, 16.0, null)
                    // Place a temporary pin at the destination
                    val pin = Marker(map).apply {
                        position = point
                        title    = label
                        icon     = MilSymbolRenderer.poi(context.resources)
                        setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                        setOnMarkerClickListener { m, _ -> m.showInfoWindow(); true }
                        map.overlays.add(this)
                    }
                    goToMarker.value = pin
                    map.invalidate()
                },
            )
        }

        // ── Call for Fire button — icon-only, compact ────────────────────
        SmallFloatingActionButton(
            onClick        = {
                if (!isLoggedIn) scope.launch { snackbarHostState.showSnackbar("Please log in first") }
                else onCallFire(Double.NaN, Double.NaN)
            },
            containerColor = Color(0xFFB91C1C),
            contentColor   = Color.White,
            modifier       = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 12.dp, bottom = 60.dp)
                .size(40.dp)
                .alpha(if (isLoggedIn) 1f else 0.4f),
        ) {
            Icon(Icons.Filled.GpsFixed, contentDescription = "Call for Fire",
                 modifier = Modifier.size(20.dp))
        }

        // ── TIC FAB — icon-only, compact ─────────────────────────────────
        SmallFloatingActionButton(
            onClick        = {
                if (!isLoggedIn) scope.launch { snackbarHostState.showSnackbar("Please log in first") }
                else scope.launch { container.alertRepository.trigger("TIC") }
            },
            containerColor = MaterialTheme.colorScheme.error,
            contentColor   = Color.White,
            modifier       = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 12.dp, bottom = 12.dp)
                .size(40.dp)
                .alpha(if (isLoggedIn) 1f else 0.4f),
        ) {
            Icon(Icons.Filled.Warning, contentDescription = "TIC",
                 modifier = Modifier.size(20.dp))
        }

        // ── Drone Spot FAB — opens the drone-spot sheet anchored on the
        //    current map centre (operator's view). One-tap reporting when
        //    a drone appears overhead — no need to first tap the map.
        SmallFloatingActionButton(
            onClick        = {
                if (!isLoggedIn) { scope.launch { snackbarHostState.showSnackbar("Please log in first") }; return@SmallFloatingActionButton }
                val map = mapRef.value
                val centre = map?.mapCenter as? GeoPoint
                    ?: GeoPoint(50.85, 4.35)  // fallback if map not ready
                pendingPoint     = centre
                pendingScreenPos = null   // skip radial, go straight to the sheet
                droneType      = "UNKNOWN"
                droneAltitude  = ""
                droneDirection = ""
                droneSpeed     = ""
                droneBehavior  = "UNKNOWN"
                droneNotes     = ""
                submitError    = null
                menuStep       = MenuStep.DRONE_SPOT
            },
            containerColor = Color(0xFF9333EA),
            contentColor   = Color.White,
            modifier       = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 12.dp, bottom = 108.dp)
                .size(40.dp)
                .alpha(if (isLoggedIn) 1f else 0.4f),
        ) {
            Text("🛸", fontSize = 18.sp)
        }

        // ── CAS FAB — opens CAS 9-liner form anchored on current map centre ──
        SmallFloatingActionButton(
            onClick        = {
                if (!isLoggedIn) { scope.launch { snackbarHostState.showSnackbar("Please log in first") }; return@SmallFloatingActionButton }
                val map    = mapRef.value
                val centre = map?.mapCenter as? GeoPoint ?: GeoPoint(50.85, 4.35)
                pendingPoint     = centre
                pendingScreenPos = null
                // Pre-fill lat/lon from map centre
                casLine5Lat = "%.6f".format(centre.latitude)
                casLine5Lon = "%.6f".format(centre.longitude)
                casLine1 = ""; casLine2 = ""; casLine3 = ""; casLine4 = ""
                casLine6 = "Laser"; casLine7 = ""; casLine8 = ""; casLine9 = ""
                casTic = false; casFoId = null; casAssetId = null
                submitError = null
                menuStep = MenuStep.CAS_NINE_LINER
                // Refresh CAS assets
                scope.launch {
                    container.casRepository.listAssets()
                        .onSuccess { casAssets = it }
                }
            },
            containerColor = Color(0xFFB45309),   // amber-700 — distinct from TIC red
            contentColor   = Color.White,
            modifier       = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 12.dp, bottom = 156.dp)
                .size(40.dp)
                .alpha(if (isLoggedIn) 1f else 0.4f),
        ) {
            Text("✈", fontSize = 18.sp)
        }

        // ── Measure result panel — compact bottom-left chip; uses outer Box for align ──
        if (measureMode) {
            val cardMaxWidth = com.arrow.tactical.ui.byWindowDp(
                compact  = 320.dp,
                medium   = 380.dp,
                expanded = 460.dp,
            )
            Card(
                modifier = Modifier
                    .align(Alignment.BottomStart)
                    .padding(start = 12.dp, bottom = 12.dp, end = 12.dp)
                    .widthIn(max = cardMaxWidth),
                colors = CardDefaults.cardColors(containerColor = Color(0xCC101626)),
            ) {
                Column(Modifier.padding(horizontal = 10.dp, vertical = 8.dp)) {
                    val first = measureFirst
                    val second = measureSecond
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = when {
                                first == null  -> "📏  Tap for P1"
                                second == null -> "📏  Tap for P2"
                                else -> {
                                    val dist = com.arrow.tactical.map.GeoMath.distanceMeters(first, second)
                                    val az   = com.arrow.tactical.map.GeoMath.bearingDegrees(first, second)
                                    val mils = com.arrow.tactical.map.GeoMath.degreesToMils(az)
                                    "📏  ${com.arrow.tactical.map.GeoMath.formatDistance(dist)}  ·  ${"%.0f".format(az)}° / ${"%.0f".format(mils)} mil"
                                }
                            },
                            color = Color(0xFFFBBF24),
                            fontWeight = FontWeight.SemiBold,
                            fontSize = 13.sp,
                            modifier = Modifier.weight(1f),
                        )
                        if (first != null && second != null) {
                            TextButton(
                                onClick = { measureFirst = null; measureSecond = null },
                                contentPadding = PaddingValues(horizontal = 6.dp, vertical = 0.dp),
                            ) { Text("Reset", fontSize = 12.sp) }
                        }
                        TextButton(
                            onClick = {
                                measureMode = false
                                measureFirst = null
                                measureSecond = null
                            },
                            contentPadding = PaddingValues(horizontal = 6.dp, vertical = 0.dp),
                        ) { Text("Done", fontSize = 12.sp) }
                    }
                }
            }
        }

        // ── Alert snackbar — sits at the bottom so it doesn't cover the
        // chrome. Triggered from handleAlertWsEvent on WS "alert/triggered".
        SnackbarHost(
            hostState = snackbarHostState,
            modifier  = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = 16.dp),
        )

    } // Box

    // ── Radial menu — shown immediately on tap (pendingScreenPos != null) ────
    if (pendingPoint != null && pendingScreenPos != null) {
        val point = pendingPoint!!
        RadialMenu(
            tapOffset = pendingScreenPos!!,
            items = listOf(
                RadialItem("⚠", "Enemy",    Color(if (isLoggedIn) 0xFFDC2626 else 0xFF666666)) {
                    if (!isLoggedIn) { scope.launch { snackbarHostState.showSnackbar("Please log in first") }; return@RadialItem }
                    pendingScreenPos = null
                    menuStep = MenuStep.ENEMY_TYPE
                },
                RadialItem("🟦", "Friendly", Color(if (isLoggedIn) 0xFF1D4ED8 else 0xFF666666)) {
                    if (!isLoggedIn) { scope.launch { snackbarHostState.showSnackbar("Please log in first") }; return@RadialItem }
                    pendingScreenPos = null
                    menuStep = MenuStep.FRIENDLY_TYPE
                },
                RadialItem("🎯", "Fire\nMission", Color(if (isLoggedIn) 0xFFB91C1C else 0xFF666666)) {
                    if (!isLoggedIn) { scope.launch { snackbarHostState.showSnackbar("Please log in first") }; return@RadialItem }
                    val lat = point.latitude; val lon = point.longitude
                    pendingPoint = null; pendingScreenPos = null
                    onCallFire(lat, lon)
                },
                RadialItem("📋", "Report",  Color(if (isLoggedIn) 0xFF2563EB else 0xFF666666)) {
                    if (!isLoggedIn) { scope.launch { snackbarHostState.showSnackbar("Please log in first") }; return@RadialItem }
                    val lat = point.latitude; val lon = point.longitude
                    pendingPoint = null; pendingScreenPos = null
                    onReport(lat, lon)
                },
                RadialItem("💣", "Mortar\nFDC", Color(if (isLoggedIn) 0xFFD97706 else 0xFF666666)) {
                    if (!isLoggedIn) { scope.launch { snackbarHostState.showSnackbar("Please log in first") }; return@RadialItem }
                    val lat = point.latitude; val lon = point.longitude
                    pendingPoint = null; pendingScreenPos = null
                    onOpenMortar(lat, lon)
                },
                RadialItem("📍", "POI",     Color(0xFFD97706)) {
                    selectedType = EnemyType.POI
                    pendingScreenPos = null          // dismiss radial, show notes sheet
                    menuStep = MenuStep.NOTES
                },
                RadialItem("📏", "Measure", Color(0xFF6366F1)) {
                    // Use the tapped point as the starting end; user taps once more for the other end.
                    measureMode   = true
                    measureFirst  = point
                    measureSecond = null
                    pendingPoint     = null
                    pendingScreenPos = null
                },
                RadialItem("🛸", "Drone\nSpot", Color(if (isLoggedIn) 0xFF9333EA else 0xFF666666)) {
                    if (!isLoggedIn) { scope.launch { snackbarHostState.showSnackbar("Please log in first") }; return@RadialItem }
                    // Reset the drone form, then open the dedicated bottom sheet.
                    droneType      = "UNKNOWN"
                    droneAltitude  = ""
                    droneDirection = ""
                    droneSpeed     = ""
                    droneBehavior  = "UNKNOWN"
                    droneNotes     = ""
                    submitError    = null
                    menuStep         = MenuStep.DRONE_SPOT
                    pendingScreenPos = null   // dismiss radial, show the sheet
                },
            ),
            onDismiss = { pendingPoint = null; pendingScreenPos = null },
        )
    }

    // ── Measure tool: keep map overlays in sync with the two-point state ──────
    LaunchedEffect(measureMode, measureFirst, measureSecond, mapRef.value) {
        val map = mapRef.value ?: return@LaunchedEffect
        // Clear previous overlays first.
        measureMarkersRef.value.forEach { map.overlays.remove(it) }
        measurePolylineRef.value?.let { map.overlays.remove(it) }
        measureMarkersRef.value = emptyList()
        measurePolylineRef.value = null

        if (measureMode) {
            val markers = listOfNotNull(measureFirst, measureSecond).map { gp ->
                Marker(map).apply {
                    position = gp
                    setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
                    title = "Measurement point"
                }
            }
            markers.forEach { map.overlays.add(it) }
            measureMarkersRef.value = markers

            val a = measureFirst
            val b = measureSecond
            if (a != null && b != null) {
                val line = org.osmdroid.views.overlay.Polyline(map).apply {
                    setPoints(listOf(a, b))
                    outlinePaint.color = "#FBBF24".toColorInt()
                    outlinePaint.strokeWidth = 6f
                    outlinePaint.isAntiAlias = true
                }
                map.overlays.add(line)
                measurePolylineRef.value = line
            }
        }
        map.invalidate()
    }

    // ── Bottom sheets — shown after selecting from radial (pendingScreenPos == null) ─
    if (pendingPoint != null && pendingScreenPos == null) {
        // Skip the partial-expand state so the sheet opens fully — critical on
        // landscape phones where the half-expanded state cuts off the form.
        val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
        ModalBottomSheet(
            onDismissRequest = { pendingPoint = null },
            sheetState       = sheetState,
        ) {
            val point = pendingPoint ?: return@ModalBottomSheet
            when (menuStep) {
                MenuStep.ENEMY_TYPE -> EnemyTypeMenu(
                    onSelect = { type ->
                        selectedType = type
                        menuStep = MenuStep.NOTES
                    },
                    onBack = { pendingPoint = null },
                )

                MenuStep.FRIENDLY_TYPE -> FriendlyTypeMenu(
                    onSelect = { type ->
                        selectedFriendlyType = type
                        friendlyNotes = ""
                        menuStep = MenuStep.FRIENDLY_NOTES
                    },
                    onBack = { pendingPoint = null },
                )

                MenuStep.FRIENDLY_NOTES -> FriendlyNotesMenu(
                    type          = selectedFriendlyType,
                    notes         = friendlyNotes,
                    onNotesChange = { friendlyNotes = it },
                    submitting    = submitting,
                    error         = submitError,
                    onBack        = { menuStep = MenuStep.FRIENDLY_TYPE },
                    onSubmit      = {
                        submitting  = true
                        submitError = null
                        scope.launch {
                            container.tacticalRepository.mark(
                                TacticalObjectIn(
                                    type         = selectedFriendlyType.name,
                                    symbolCode   = selectedFriendlyType.sidc,
                                    latitude     = point.latitude,
                                    longitude    = point.longitude,
                                    notes        = friendlyNotes,
                                    affiliation  = "FRIENDLY",
                                ),
                            ).onSuccess {
                                pendingPoint  = null
                                friendlyNotes = ""
                            }.onFailure {
                                submitError = it.message ?: "Failed"
                            }
                            submitting = false
                        }
                    },
                )

                MenuStep.DRONE_SPOT -> DroneSpotMenu(
                    droneType      = droneType,    onDroneTypeChange   = { droneType = it },
                    altitude       = droneAltitude,  onAltitudeChange  = { droneAltitude = it },
                    direction      = droneDirection, onDirectionChange = { droneDirection = it },
                    speed          = droneSpeed,     onSpeedChange     = { droneSpeed = it },
                    behavior       = droneBehavior,  onBehaviorChange  = { droneBehavior = it },
                    notes          = droneNotes,     onNotesChange     = { droneNotes = it },
                    submitting     = submitting,
                    error          = submitError,
                    onBack         = { pendingPoint = null },
                    onSubmit       = {
                        submitting  = true
                        submitError = null
                        scope.launch {
                            container.reportRepository.submitDroneSpot(
                                latitude      = point.latitude,
                                longitude     = point.longitude,
                                droneType     = droneType,
                                altitudeM     = droneAltitude.toDoubleOrNull(),
                                directionDeg  = droneDirection.toDoubleOrNull(),
                                speedKts      = droneSpeed.toDoubleOrNull(),
                                behavior      = droneBehavior,
                                notes         = droneNotes,
                            ).onSuccess {
                                pendingPoint = null
                            }.onFailure {
                                submitError = it.message ?: "Failed"
                            }
                            submitting = false
                        }
                    },
                )

                MenuStep.CAS_NINE_LINER -> CasNineLinerMenu(
                    line1         = casLine1,  onLine1Change  = { casLine1 = it },
                    line2         = casLine2,  onLine2Change  = { casLine2 = it },
                    line3         = casLine3,  onLine3Change  = { casLine3 = it },
                    line4         = casLine4,  onLine4Change  = { casLine4 = it },
                    lat           = casLine5Lat, onLatChange  = { casLine5Lat = it },
                    lon           = casLine5Lon, onLonChange  = { casLine5Lon = it },
                    line6         = casLine6,  onLine6Change  = { casLine6 = it },
                    line7         = casLine7,  onLine7Change  = { casLine7 = it },
                    line8         = casLine8,  onLine8Change  = { casLine8 = it },
                    line9         = casLine9,  onLine9Change  = { casLine9 = it },
                    tic           = casTic,    onTicChange    = { casTic = it },
                    foOperatorId  = casFoId,   onFoChange     = { casFoId = it },
                    assetId       = casAssetId, onAssetChange = { casAssetId = it },
                    operators     = operators,
                    casAssets     = casAssets,
                    submitting    = submitting,
                    error         = submitError,
                    onBack        = { pendingPoint = null },
                    onSubmit      = {
                        submitting  = true
                        submitError = null
                        scope.launch {
                            val lat = casLine5Lat.toDoubleOrNull()
                            val lon = casLine5Lon.toDoubleOrNull()
                            val mgrs: String = if (lat != null && lon != null) {
                                try { MgrsConverter.encode(lat, lon) } catch (_: Exception) { "" }
                            } else ""
                            val body = com.arrow.tactical.network.CasNineLinerIn(
                                line1        = casLine1,
                                line2        = casLine2,
                                line3        = casLine3,
                                line4        = casLine4,
                                line5Mgrs    = mgrs,
                                line5Lat     = lat,
                                line5Lon     = lon,
                                line6        = casLine6,
                                line7        = casLine7,
                                line8        = casLine8,
                                line9        = casLine9,
                                tic          = casTic,
                                foOperatorId = casFoId,
                                assetId      = casAssetId,
                            )
                            container.casRepository.submitRequest(body)
                                .onSuccess { pendingPoint = null }
                                .onFailure { submitError = it.message ?: "Submission failed" }
                            submitting = false
                        }
                    },
                )

                MenuStep.NOTES -> NotesMenu(
                    type           = selectedType,
                    notes          = notes,
                    onNotesChange  = { notes = it },
                    submitting     = submitting,
                    error          = submitError,
                    photoUri       = pendingPhotoUri,
                    uploadingPhoto = uploadingPhoto,
                    onPickPhoto    = { galleryLauncher.launch("image/*") },
                    onClearPhoto   = { pendingPhotoUri = null; pendingPhotoId = null },
                    onBack = {
                        if (selectedType == EnemyType.POI) pendingPoint = null
                        else menuStep = MenuStep.ENEMY_TYPE
                        pendingPhotoId  = null
                        pendingPhotoUri = null
                    },
                    onSubmit = {
                        submitting  = true
                        submitError = null
                        scope.launch {
                            container.tacticalRepository.mark(
                                TacticalObjectIn(
                                    type       = selectedType.name,
                                    symbolCode = selectedType.sidc,
                                    latitude   = point.latitude,
                                    longitude  = point.longitude,
                                    notes      = notes,
                                    photoId    = pendingPhotoId,
                                ),
                            ).onSuccess {
                                pendingPoint    = null
                                pendingPhotoId  = null
                                pendingPhotoUri = null
                                // enemies Flow auto-updates from local DB — no manual refresh needed
                            }.onFailure {
                                submitError = it.message ?: "Failed"
                            }
                            submitting = false
                        }
                    },
                )
            }
        }
    }

    // ── Objective detail dialog ──────────────────────────────────────────────
    selectedObjective?.let { obj ->
        ObjectiveDetailDialog(
            obj         = obj,
            baseUrl     = serverUrl,
            imageLoader = container.imageLoader,
            onDismiss   = { selectedObjective = null },
        )
    }

    // ── Tactical object radial (tap enemy/POI marker) ────────────────────────
    val tactObj    = selectedTacticalObj
    val tactScreen = selectedTacticalObjScreen
    if (tactObj != null && tactScreen != null) {
        RadialMenu(
            tapOffset = tactScreen,
            items = buildList {
                if (canEditTactical) {
                    add(RadialItem("📌", "Move", Color(0xFF2563EB)) {
                        selectedTacticalObj       = null
                        selectedTacticalObjScreen = null
                        movingTacticalObjState.value = tactObj
                    })
                    add(RadialItem("🗑", "Delete", Color(0xFFDC2626)) {
                        selectedTacticalObj       = null
                        selectedTacticalObjScreen = null
                        scope.launch { container.tacticalRepository.delete(tactObj.id) }
                    })
                } else {
                    add(RadialItem("ℹ", tactObj.type, Color(0xFF64748B)) {
                        selectedTacticalObj = null; selectedTacticalObjScreen = null
                    })
                }
            },
            onDismiss = { selectedTacticalObj = null; selectedTacticalObjScreen = null },
        )
    }

    // ── Move-mode banner ──────────────────────────────────────────────────────
    if (movingTacticalObj != null) {
        Box(
            Modifier.fillMaxSize().padding(bottom = 88.dp),
            contentAlignment = Alignment.BottomCenter,
        ) {
            Surface(
                color  = MaterialTheme.colorScheme.primaryContainer,
                shape  = RoundedCornerShape(8.dp),
                modifier = Modifier.padding(horizontal = 16.dp),
            ) {
                Row(
                    Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                    verticalAlignment      = Alignment.CenterVertically,
                    horizontalArrangement  = Arrangement.spacedBy(12.dp),
                ) {
                    Text("Tap map to place marker", style = MaterialTheme.typography.bodyMedium)
                    TextButton(onClick = { movingTacticalObjState.value = null }) { Text("Cancel") }
                }
            }
        }
    }
}

@Composable
private fun ObjectiveDetailDialog(
    obj: TacticalObjectDto,
    baseUrl: String,
    imageLoader: coil.ImageLoader,
    onDismiss: () -> Unit,
) {
    val notes  = obj.notes
    val nl     = notes.indexOf('\n')
    val title  = (if (nl >= 0) notes.substring(0, nl) else notes).ifBlank { "Objective" }
    val rest   = if (nl >= 0) notes.substring(nl + 1) else ""
    val mgrs   = rest.lineSequence().firstOrNull { it.startsWith("MGRS:") }
                     ?.removePrefix("MGRS:")?.trim() ?: ""
    val desc   = rest.lineSequence().filterNot { it.startsWith("MGRS:") }
                     .joinToString("\n").trim()

    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("Close") }
        },
        title = { Text("🚩 $title", fontWeight = FontWeight.Bold) },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (mgrs.isNotBlank()) {
                    Text("MGRS: $mgrs", style = MaterialTheme.typography.labelSmall,
                         color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Text(
                    "%.5f, %.5f".format(obj.latitude, obj.longitude),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (desc.isNotBlank()) {
                    Text(desc, style = MaterialTheme.typography.bodyMedium)
                } else {
                    Text("(no description)", style = MaterialTheme.typography.bodySmall,
                         color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (obj.photoId != null && baseUrl.isNotBlank()) {
                    AsyncImage(
                        model              = "$baseUrl/photos/${obj.photoId}",
                        contentDescription = "Objective photo",
                        imageLoader        = imageLoader,
                        modifier           = Modifier
                            .fillMaxWidth()
                            .heightIn(max = 240.dp)
                            .clip(RoundedCornerShape(6.dp)),
                        contentScale       = ContentScale.Fit,
                    )
                }
            }
        },
    )
}

/** Add a tactical control graphic (point / line / polygon) to the OSMdroid map. */
private fun renderTacticalGraphic(
    map: org.osmdroid.views.MapView,
    res: android.content.res.Resources,
    g: TacticalObjectDto,
) {
    val titleSuffix = " · ${g.affiliation}" +
        (if (g.echelon.isNotBlank()) " · ${g.echelon}" else "")
    if (com.arrow.tactical.map.MilSymbolRenderer.isTacticalGraphic(g.type)) {
        // Oriented point graphic
        val drawable = com.arrow.tactical.map.MilSymbolRenderer
            .tacticalGraphic(res, g.type, g.rotation, g.echelon, g.affiliation) ?: return
        Marker(map).apply {
            position = GeoPoint(g.latitude, g.longitude)
            title    = "${g.type.replace('_', ' ')}$titleSuffix"
            snippet  = g.notes.ifBlank { "heading ${g.rotation.toInt()}°" }
            icon     = drawable
            setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
            map.overlays.add(this)
        }
        return
    }
    val style = com.arrow.tactical.map.MilSymbolRenderer
        .tacticalLineStyle(g.type, g.affiliation) ?: return
    val coords = parseGeometryCoords(g.geometry) ?: listOf(GeoPoint(g.latitude, g.longitude))
    if (coords.size < 2) return
    val dp = res.displayMetrics.density
    if (com.arrow.tactical.map.MilSymbolRenderer.isTacticalPolygon(g.type)) {
        val poly = org.osmdroid.views.overlay.Polygon(map).apply {
            points = coords
            fillPaint.color = (style.color and 0x00FFFFFF) or 0x33000000
            outlinePaint.color = style.color
            outlinePaint.strokeWidth = style.widthDp * dp
            title    = "${g.type.replace('_', ' ')}$titleSuffix"
            snippet  = g.notes
        }
        map.overlays.add(poly)
    } else {
        val line = org.osmdroid.views.overlay.Polyline(map).apply {
            setPoints(coords)
            outlinePaint.color = style.color
            outlinePaint.strokeWidth = style.widthDp * dp
            if (style.dashOnDp > 0) {
                outlinePaint.pathEffect = android.graphics.DashPathEffect(
                    floatArrayOf(style.dashOnDp * dp, style.dashOffDp * dp), 0f)
            }
            title    = "${g.type.replace('_', ' ')}$titleSuffix"
            snippet  = g.notes
        }
        map.overlays.add(line)
    }
}

/** Parse the JSON-encoded geometry into a list of OSMdroid GeoPoints (or null). */
private fun parseGeometryCoords(geometry: String): List<GeoPoint>? {
    if (geometry.isBlank()) return null
    return runCatching {
        val root = kotlinx.serialization.json.Json.parseToJsonElement(geometry).jsonObject
        val arr  = root["coords"]?.jsonArray ?: return null
        arr.map { pair ->
            val ll = pair.jsonArray
            GeoPoint(
                ll[0].jsonPrimitive.content.toDouble(),
                ll[1].jsonPrimitive.content.toDouble(),
            )
        }
    }.getOrNull()
}

/** Walk the /hierarchy JSON and return all operator IDs in the same platoon as [myId]. */
private fun parsePlatoonIds(json: String, myId: Int): Set<Int> {
    val result = mutableSetOf(myId)
    try {
        val root = kotlinx.serialization.json.Json.parseToJsonElement(json)
            .jsonObject
        val companies = root["companies"]?.jsonArray ?: return result
        for (co in companies) {
            for (plt in co.jsonObject["platoons"]?.jsonArray ?: continue) {
                val pltIds = mutableSetOf<Int>()
                var found  = false
                for (sec in plt.jsonObject["sections"]?.jsonArray ?: continue) {
                    for (team in sec.jsonObject["teams"]?.jsonArray ?: continue) {
                        for (op in team.jsonObject["operators"]?.jsonArray ?: continue) {
                            val id = op.jsonObject["id"]?.jsonPrimitive?.int ?: continue
                            pltIds += id
                            if (id == myId) found = true
                        }
                    }
                }
                if (found) { result += pltIds; return result }
            }
        }
    } catch (_: Exception) { /* return at least own id */ }
    return result
}

@Composable
private fun FriendlyTypeMenu(onSelect: (FriendlyType) -> Unit, onBack: () -> Unit) {
    val friendlyBlue = Color(0xFF1D4ED8)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .padding(top = 4.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
            }
            Text(
                "Select friendly unit type",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
        }
        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalArrangement   = Arrangement.spacedBy(6.dp),
            modifier = Modifier.heightIn(max = 260.dp),
        ) {
            items(FriendlyType.entries) { type ->
                OutlinedButton(
                    onClick = { onSelect(type) },
                    modifier = Modifier.fillMaxWidth(),
                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 6.dp),
                    colors = ButtonDefaults.outlinedButtonColors(
                        contentColor = friendlyBlue,
                    ),
                ) {
                    Text(type.label, maxLines = 2, fontSize = 13.sp)
                }
            }
        }
    }
}

@Composable
private fun FriendlyNotesMenu(
    type:          FriendlyType,
    notes:         String,
    onNotesChange: (String) -> Unit,
    submitting:    Boolean,
    error:         String?,
    onBack:        () -> Unit,
    onSubmit:      () -> Unit,
) {
    val friendlyBlue = Color(0xFF1D4ED8)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .padding(top = 4.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
            }
            Column {
                Text(
                    type.label,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    "SIDC: ${type.sidc}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        OutlinedTextField(
            value         = notes,
            onValueChange = onNotesChange,
            label         = { Text("Unit / notes") },
            placeholder   = { Text("e.g. 2nd Plt, moving to OBJ EAGLE") },
            modifier      = Modifier.fillMaxWidth(),
            singleLine    = false,
            minLines      = 1,
            maxLines      = 3,
        )
        error?.let {
            Text(it, color = MaterialTheme.colorScheme.error,
                 style = MaterialTheme.typography.bodySmall)
        }
        Button(
            onClick  = onSubmit,
            enabled  = !submitting,
            modifier = Modifier.fillMaxWidth(),
            colors   = ButtonDefaults.buttonColors(containerColor = friendlyBlue),
        ) {
            Text(if (submitting) "Marking…" else "Mark on map")
        }
    }
}

@Composable
private fun EnemyTypeMenu(onSelect: (EnemyType) -> Unit, onBack: () -> Unit) {
    val hostileTypes = EnemyType.entries.filter { it != EnemyType.POI }

    // LazyVerticalGrid scrolls itself, so the outer Column doesn't need verticalScroll
    // (mixing them throws). We cap the grid at a smaller max height so the header
    // stays visible on landscape phones (~ 400 dp tall sheets).
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .padding(top = 4.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
            }
            Text(
                "Select enemy type",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
        }
        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalArrangement   = Arrangement.spacedBy(6.dp),
            modifier = Modifier.heightIn(max = 260.dp),
        ) {
            items(hostileTypes) { type ->
                OutlinedButton(
                    onClick = { onSelect(type) },
                    modifier = Modifier.fillMaxWidth(),
                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 6.dp),
                    colors = ButtonDefaults.outlinedButtonColors(
                        contentColor = MaterialTheme.colorScheme.error,
                    ),
                ) {
                    Text(type.label, maxLines = 2, fontSize = 13.sp)
                }
            }
        }
    }
}

@Composable
private fun NotesMenu(
    type: EnemyType,
    notes: String,
    onNotesChange: (String) -> Unit,
    submitting: Boolean,
    error: String?,
    photoUri: android.net.Uri?,
    uploadingPhoto: Boolean,
    onPickPhoto: () -> Unit,
    onClearPhoto: () -> Unit,
    onBack: () -> Unit,
    onSubmit: () -> Unit,
) {
    // verticalScroll keeps the form usable on landscape phones — without it the
    // photo preview (180 dp) + multi-line notes + submit button crop off the bottom.
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp)
            .padding(top = 4.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
            }
            Column {
                Text(
                    type.label,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    "SIDC: ${type.sidc}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        OutlinedTextField(
            value         = notes,
            onValueChange = onNotesChange,
            label         = { Text("Details / observations") },
            placeholder   = { Text("e.g. ~6 dismounts, moving NE") },
            modifier      = Modifier.fillMaxWidth(),
            singleLine    = false,
            minLines      = 1,
            maxLines      = 3,
        )

        // Photo section
        if (photoUri != null) {
            Box {
                AsyncImage(
                    model              = photoUri,
                    contentDescription = "Attached photo",
                    modifier           = Modifier
                        .fillMaxWidth()
                        .heightIn(max = 140.dp)
                        .clip(RoundedCornerShape(8.dp)),
                    contentScale       = ContentScale.Crop,
                )
                IconButton(
                    onClick  = onClearPhoto,
                    modifier = Modifier.align(Alignment.TopEnd),
                ) {
                    Icon(Icons.Filled.Close, contentDescription = "Remove photo",
                         tint = MaterialTheme.colorScheme.onSurface)
                }
                if (uploadingPhoto) {
                    CircularProgressIndicator(Modifier.align(Alignment.Center))
                }
            }
        } else {
            OutlinedButton(
                onClick  = onPickPhoto,
                modifier = Modifier.fillMaxWidth(),
                enabled  = !uploadingPhoto,
            ) {
                Icon(Icons.Filled.AddPhotoAlternate, null,
                     modifier = Modifier.padding(end = 8.dp))
                Text("Add photo")
            }
        }

        error?.let {
            Text(it, color = MaterialTheme.colorScheme.error,
                 style = MaterialTheme.typography.bodySmall)
        }
        Button(
            onClick  = onSubmit,
            enabled  = !submitting && !uploadingPhoto,
            modifier = Modifier.fillMaxWidth(),
            colors   = if (type == EnemyType.POI) ButtonDefaults.buttonColors()
                       else ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
        ) {
            Text(if (submitting) "Marking…" else "Mark on map")
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DroneSpotMenu(
    droneType:         String,
    onDroneTypeChange: (String) -> Unit,
    altitude:          String,
    onAltitudeChange:  (String) -> Unit,
    direction:         String,
    onDirectionChange: (String) -> Unit,
    speed:             String,
    onSpeedChange:     (String) -> Unit,
    behavior:          String,
    onBehaviorChange:  (String) -> Unit,
    notes:             String,
    onNotesChange:     (String) -> Unit,
    submitting:        Boolean,
    error:             String?,
    onBack:            () -> Unit,
    onSubmit:          () -> Unit,
) {
    // verticalScroll so the form stays usable on a landscape phone where the
    // sheet would otherwise crop the Notes field and Submit button off-screen.
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp)
            .padding(top = 8.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("🛸  Drone Spot Report",
                 style = MaterialTheme.typography.titleSmall,
                 color = Color(0xFFA855F7))
            Spacer(Modifier.weight(1f))
            TextButton(
                onClick = onBack,
                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp),
            ) { Text("Cancel") }
        }

        DroneDropdown(label = "Drone type", value = droneType,
                      options = DRONE_TYPES, onSelect = onDroneTypeChange)

        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedTextField(
                value = altitude, onValueChange = onAltitudeChange,
                label = { Text("Alt (m)") },
                singleLine = true, modifier = Modifier.weight(1f),
                keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                    keyboardType = androidx.compose.ui.text.input.KeyboardType.Number),
            )
            OutlinedTextField(
                value = direction, onValueChange = onDirectionChange,
                label = { Text("Dir (°)") },
                singleLine = true, modifier = Modifier.weight(1f),
                keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                    keyboardType = androidx.compose.ui.text.input.KeyboardType.Number),
            )
            OutlinedTextField(
                value = speed, onValueChange = onSpeedChange,
                label = { Text("Spd (kt)") },
                singleLine = true, modifier = Modifier.weight(1f),
                keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                    keyboardType = androidx.compose.ui.text.input.KeyboardType.Number),
            )
        }

        DroneDropdown(label = "Behavior", value = behavior,
                      options = DRONE_BEHAVIOURS, onSelect = onBehaviorChange)

        OutlinedTextField(
            value = notes, onValueChange = onNotesChange,
            label = { Text("Notes") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = false, minLines = 1, maxLines = 3,
        )

        error?.let {
            Text(it, color = MaterialTheme.colorScheme.error,
                 style = MaterialTheme.typography.bodySmall)
        }

        Button(
            onClick  = onSubmit,
            enabled  = !submitting,
            modifier = Modifier.fillMaxWidth(),
            colors   = ButtonDefaults.buttonColors(containerColor = Color(0xFF9333EA)),
        ) {
            Text(if (submitting) "Reporting…" else "Submit drone spot")
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DroneDropdown(
    label:    String,
    value:    String,
    options:  List<String>,
    onSelect: (String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(
        expanded = expanded,
        onExpandedChange = { expanded = !expanded },
    ) {
        OutlinedTextField(
            value = value, onValueChange = {}, readOnly = true,
            label = { Text(label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            modifier = Modifier
                .fillMaxWidth()
                .menuAnchor(MenuAnchorType.PrimaryNotEditable),
        )
        ExposedDropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
        ) {
            options.forEach { opt ->
                DropdownMenuItem(
                    text = { Text(opt) },
                    onClick = { onSelect(opt); expanded = false },
                )
            }
        }
    }
}

private val CAS_MARK_TYPES = listOf("Laser", "Smoke", "IR pointer", "Mark-63", "WP", "None")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CasNineLinerMenu(
    line1: String, onLine1Change: (String) -> Unit,
    line2: String, onLine2Change: (String) -> Unit,
    line3: String, onLine3Change: (String) -> Unit,
    line4: String, onLine4Change: (String) -> Unit,
    lat:   String, onLatChange:   (String) -> Unit,
    lon:   String, onLonChange:   (String) -> Unit,
    line6: String, onLine6Change: (String) -> Unit,
    line7: String, onLine7Change: (String) -> Unit,
    line8: String, onLine8Change: (String) -> Unit,
    line9: String, onLine9Change: (String) -> Unit,
    tic:   Boolean, onTicChange:  (Boolean) -> Unit,
    foOperatorId: Int?,  onFoChange:    (Int?) -> Unit,
    assetId:      Int?,  onAssetChange: (Int?) -> Unit,
    operators:    List<com.arrow.tactical.network.OperatorDto>,
    casAssets:    List<com.arrow.tactical.network.CasAssetDto>,
    submitting:   Boolean,
    error:        String?,
    onBack:       () -> Unit,
    onSubmit:     () -> Unit,
) {
    val casColor = Color(0xFFB45309)

    // Derive MGRS from lat/lon for live display
    val mgrsDisplay = remember(lat, lon) {
        val la = lat.toDoubleOrNull()
        val lo = lon.toDoubleOrNull()
        if (la != null && lo != null && la in -80.0..84.0)
            runCatching { MgrsConverter.encode(la, lo) }.getOrElse { "$la, $lo" }
        else "—"
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp)
            .padding(top = 8.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        // Header
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("✈  CAS 9-Liner",
                 style = MaterialTheme.typography.titleSmall,
                 color = casColor)
            Spacer(Modifier.weight(1f))
            TextButton(
                onClick = onBack,
                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp),
            ) { Text("Cancel") }
        }

        // TIC toggle — prominent at top
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(
                    if (tic) Color(0x33EF4444) else Color(0x22151E2D),
                    RoundedCornerShape(6.dp),
                )
                .border(
                    1.dp,
                    if (tic) Color(0xFFDC2626) else Color(0xFF2A3142),
                    RoundedCornerShape(6.dp),
                )
                .clickable { onTicChange(!tic) }
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            androidx.compose.material3.Switch(
                checked = tic,
                onCheckedChange = onTicChange,
                colors = SwitchDefaults.colors(
                    checkedThumbColor  = Color.White,
                    checkedTrackColor  = Color(0xFFDC2626),
                ),
            )
            Column {
                Text(
                    "⚡ TROOPS IN CONTACT (TIC)",
                    style = MaterialTheme.typography.labelMedium,
                    color = if (tic) Color(0xFFEF4444) else Color(0xFF94A3B8),
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    "Triggers priority alarm on all Battle Captain screens",
                    style = MaterialTheme.typography.labelSmall,
                    color = Color(0xFF64748B),
                )
            }
        }

        // Line 1 – IP
        CasLineField(n = 1, label = "IP (Initial Point)", value = line1,
                     placeholder = "Name or grid of Initial Point",
                     color = casColor, onChange = onLine1Change)

        // Line 2 – Heading/Distance
        CasLineField(n = 2, label = "Heading / Distance", value = line2,
                     placeholder = "e.g. 270° / 5 km from IP",
                     color = casColor, onChange = onLine2Change)

        // Line 3 – Target elevation
        CasLineField(n = 3, label = "Target elevation (m MSL)", value = line3,
                     placeholder = "e.g. 312",
                     color = casColor, onChange = onLine3Change,
                     keyboardType = androidx.compose.ui.text.input.KeyboardType.Number)

        // Line 4 – Target description
        CasLineField(n = 4, label = "Target description", value = line4,
                     placeholder = "e.g. 4-man group, T-72, bunker",
                     color = casColor, onChange = onLine4Change)

        // Line 5 – Target location: lat/lon + MGRS
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(Color(0x220E1217), RoundedCornerShape(4.dp))
                .border(1.dp, Color(0xFF2A3142), RoundedCornerShape(4.dp))
                .padding(8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(
                "5",
                modifier = Modifier.width(22.dp),
                color = casColor,
                fontWeight = FontWeight.Bold,
                fontSize = 13.sp,
            )
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("TARGET LOCATION", fontSize = 10.sp, color = Color(0xFF94A3B8),
                     fontWeight = FontWeight.Bold)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    OutlinedTextField(
                        value = lat, onValueChange = onLatChange,
                        label = { Text("Lat") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                        keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                            keyboardType = androidx.compose.ui.text.input.KeyboardType.Decimal),
                    )
                    OutlinedTextField(
                        value = lon, onValueChange = onLonChange,
                        label = { Text("Lon") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                        keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                            keyboardType = androidx.compose.ui.text.input.KeyboardType.Decimal),
                    )
                }
                // Live MGRS display
                Text(
                    "MGRS: $mgrsDisplay",
                    fontSize = 12.sp,
                    color = Color(0xFFFBBF24),
                    fontWeight = FontWeight.SemiBold,
                    fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(Color(0x220E1217), RoundedCornerShape(4.dp))
                        .padding(horizontal = 8.dp, vertical = 4.dp),
                )
            }
        }

        // Line 6 – Type of mark (dropdown)
        DroneDropdown(
            label = "6 — Type of mark",
            value = line6,
            options = CAS_MARK_TYPES,
            onSelect = onLine6Change,
        )

        // Line 7 – Friendly location
        CasLineField(n = 7, label = "Friendly location", value = line7,
                     placeholder = "e.g. N 600m from target",
                     color = casColor, onChange = onLine7Change)

        // Line 8 – Egress
        CasLineField(n = 8, label = "Egress direction", value = line8,
                     placeholder = "e.g. 270° West after attack",
                     color = casColor, onChange = onLine8Change)

        // Line 9 – Remarks/Threats (multiline)
        OutlinedTextField(
            value = line9, onValueChange = onLine9Change,
            label = { Text("9 — Remarks / Threats / TOT") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = false, minLines = 2, maxLines = 4,
            placeholder = { Text("Restrictions, threats, authentication…",
                                  color = Color(0xFF64748B)) },
        )

        // FO dropdown
        if (operators.isNotEmpty()) {
            var foExpanded by remember { mutableStateOf(false) }
            val foLabel = operators.find { it.id == foOperatorId }?.callsign ?: "— no FO assigned —"
            ExposedDropdownMenuBox(expanded = foExpanded, onExpandedChange = { foExpanded = !foExpanded }) {
                OutlinedTextField(
                    value = foLabel, onValueChange = {}, readOnly = true,
                    label = { Text("Forward Observer (FO)") },
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = foExpanded) },
                    modifier = Modifier.fillMaxWidth()
                        .menuAnchor(MenuAnchorType.PrimaryNotEditable),
                )
                ExposedDropdownMenu(expanded = foExpanded, onDismissRequest = { foExpanded = false }) {
                    DropdownMenuItem(text = { Text("— none —") },
                                     onClick = { onFoChange(null); foExpanded = false })
                    operators.forEach { op ->
                        DropdownMenuItem(
                            text = { Text("${op.callsign} (${op.rank})") },
                            onClick = { onFoChange(op.id); foExpanded = false },
                        )
                    }
                }
            }
        }

        // CAS asset dropdown
        val availableAssets = casAssets.filter { it.status == "AVAILABLE" || it.status == "ON_STATION" }
        if (availableAssets.isNotEmpty()) {
            var assetExpanded by remember { mutableStateOf(false) }
            val assetLabel = availableAssets.find { it.id == assetId }
                ?.let { "${it.callsign} [${it.aircraftType.ifBlank { "?" }}] ${it.status}" }
                ?: "— no asset nominated —"
            ExposedDropdownMenuBox(expanded = assetExpanded, onExpandedChange = { assetExpanded = !assetExpanded }) {
                OutlinedTextField(
                    value = assetLabel, onValueChange = {}, readOnly = true,
                    label = { Text("CAS asset") },
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = assetExpanded) },
                    modifier = Modifier.fillMaxWidth()
                        .menuAnchor(MenuAnchorType.PrimaryNotEditable),
                )
                ExposedDropdownMenu(expanded = assetExpanded, onDismissRequest = { assetExpanded = false }) {
                    DropdownMenuItem(text = { Text("— none —") },
                                     onClick = { onAssetChange(null); assetExpanded = false })
                    availableAssets.forEach { a ->
                        DropdownMenuItem(
                            text = {
                                Column {
                                    Text("${a.callsign}  [${a.aircraftType.ifBlank { "?" }}]",
                                         fontWeight = FontWeight.SemiBold)
                                    if (a.ordnance.isNotBlank())
                                        Text(a.ordnance, fontSize = 11.sp, color = Color(0xFF94A3B8))
                                }
                            },
                            onClick = { onAssetChange(a.id); assetExpanded = false },
                        )
                    }
                }
            }
        } else {
            Text("No CAS assets available", fontSize = 12.sp, color = Color(0xFF64748B))
        }

        error?.let {
            Text(it, color = MaterialTheme.colorScheme.error,
                 style = MaterialTheme.typography.bodySmall)
        }

        Button(
            onClick  = onSubmit,
            enabled  = !submitting,
            modifier = Modifier.fillMaxWidth(),
            colors   = ButtonDefaults.buttonColors(containerColor = casColor),
        ) {
            Text(if (submitting) "Submitting…" else if (tic) "⚡ Submit TIC CAS Request" else "✈ Submit CAS Request")
        }
    }
}

@Composable
private fun CasLineField(
    n:           Int,
    label:       String,
    value:       String,
    placeholder: String,
    color:       Color,
    onChange:    (String) -> Unit,
    keyboardType: androidx.compose.ui.text.input.KeyboardType =
        androidx.compose.ui.text.input.KeyboardType.Text,
) {
    OutlinedTextField(
        value = value, onValueChange = onChange,
        label = { Text("$n — $label") },
        placeholder = { Text(placeholder, color = Color(0xFF64748B)) },
        modifier = Modifier.fillMaxWidth(),
        singleLine = true,
        keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(keyboardType = keyboardType),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = color,
            focusedLabelColor  = color,
        ),
    )
}

private fun <T> clusterItems(
    items: List<T>,
    zoom: Float,
    getLat: (T) -> Double?,
    getLon: (T) -> Double?
): List<List<T>> {
    if (zoom >= 13f) return items.map { listOf(it) }
    val clusters = mutableListOf<MutableList<T>>()
    val threshold = 1.0 / (1 shl (zoom.toInt() - 6).coerceAtLeast(1))
    for (item in items) {
        val lat = getLat(item) ?: continue
        val lon = getLon(item) ?: continue
        var found = false
        for (cluster in clusters) {
            val first = cluster[0]
            val clat = getLat(first)!!
            val clon = getLon(first)!!
            if (kotlin.math.abs(lat - clat) < threshold && kotlin.math.abs(lon - clon) < threshold) {
                cluster.add(item)
                found = true
                break
            }
        }
        if (!found) clusters.add(mutableListOf(item))
    }
    return clusters
}
