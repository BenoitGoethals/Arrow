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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.Canvas
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
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.map.BackendTileSource
import com.arrow.tactical.map.MapSourceDto
import com.arrow.tactical.map.MilSymbolRenderer
import com.arrow.tactical.network.OperatorDto
import com.arrow.tactical.network.TacticalObjectDto
import com.arrow.tactical.network.TacticalObjectIn
import com.arrow.tactical.tactical.EnemyType
import com.arrow.tactical.tracking.LocationService
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.osmdroid.events.MapEventsReceiver
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.MapEventsOverlay
import org.osmdroid.views.overlay.Marker

// CATEGORY is gone — replaced by RadialMenu; ENEMY_TYPE and NOTES are direct bottom sheets
private enum class MenuStep { ENEMY_TYPE, NOTES }
private enum class OverlayMode { ALL, NONE, ENEMIES, OWN_PLATOON }

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
    var enemies      by remember { mutableStateOf<List<TacticalObjectDto>>(emptyList()) }
    var fireMissions by remember { mutableStateOf<List<com.arrow.tactical.network.FireMissionDto>>(emptyList()) }
    var selectedObjective by remember { mutableStateOf<TacticalObjectDto?>(null) }
    var meId by remember { mutableStateOf<Int?>(null) }
    var hasAutocentered by remember { mutableStateOf(false) }
    var fetchError by remember { mutableStateOf<String?>(null) }
    var serverUrl by remember { mutableStateOf("") }
    // null = checking, true = online, false = offline
    var serverOnline by remember { mutableStateOf<Boolean?>(null) }
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
    var isStreaming  by remember {
        mutableStateOf(com.arrow.tactical.stream.CameraStreamService.isStreaming.get())
    }

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
        val intent = android.content.Intent(
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

    // Tap state — written from the OSMdroid tap callback
    val pendingPointState     = remember { mutableStateOf<GeoPoint?>(null) }
    val pendingScreenPosState = remember { mutableStateOf<Offset?>(null) }
    var pendingPoint     by pendingPointState
    var pendingScreenPos by pendingScreenPosState
    // null screenPos = bottom-sheet showing; non-null = radial menu showing
    var menuStep     by remember { mutableStateOf(MenuStep.ENEMY_TYPE) }
    var selectedType by remember { mutableStateOf(EnemyType.INFANTRY) }
    var notes by remember { mutableStateOf("") }
    var submitting by remember { mutableStateOf(false) }
    var submitError by remember { mutableStateOf<String?>(null) }
    var pendingPhotoId  by remember { mutableStateOf<Int?>(null) }
    var pendingPhotoUri by remember { mutableStateOf<android.net.Uri?>(null) }
    var uploadingPhoto  by remember { mutableStateOf(false) }

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
                    fetchError   = "Server returned ${health.code}"
                } else {
                    container.tacticalRepository.listOperators()
                        .onSuccess { ops ->
                            operators    = ops
                            serverOnline = true
                            fetchError   = if (ops.isEmpty()) "0 operators — run simulator?" else null
                        }
                        .onFailure { err ->
                            serverOnline = false
                            fetchError   = when {
                                err.message?.contains("401") == true ->
                                    "Not authenticated — log out and back in"
                                err.message?.contains("403") == true ->
                                    "Access denied"
                                else -> err.message?.take(80)
                            }
                        }
                    container.tacticalRepository.listObjects()
                        .onSuccess { enemies = it }
                    container.fireMissionRepository.list()
                        .onSuccess { fireMissions = it }
                    container.reportRepository.list()
                        .onSuccess { reps ->
                            cbrnReports = com.arrow.tactical.cbrn.cbrnReportsFrom(reps)
                        }
                }
            } catch (e: Exception) {
                serverOnline = false
                fetchError   = "Cannot reach ${serverUrl.ifBlank { "server" }}: ${e.message?.take(50)}"
            }
            delay(5_000)
        }
    }

    // Resilient WebSocket — reconnects automatically after any failure
    LaunchedEffect(Unit) {
        while (true) {
            try {
                container.wsClient.events().collect { evt: JsonObject ->
                    val channel = evt["channel"]?.toString()?.trim('"')
                    when (channel) {
                        "tracking"        -> container.tacticalRepository.listOperators()
                            .onSuccess { ops -> operators = ops; serverOnline = true }
                        "tactical-object" -> container.tacticalRepository.listObjects()
                            .onSuccess { enemies = it }
                        "fire-mission"    -> container.fireMissionRepository.list()
                            .onSuccess { fireMissions = it }
                        "report"          -> container.reportRepository.list()
                            .onSuccess { reps ->
                                cbrnReports = com.arrow.tactical.cbrn.cbrnReportsFrom(reps)
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

    // mapRef lets LaunchedEffect imperatively update overlays outside AndroidView.update,
    // which avoids Compose's state-tracking limitations for non-composable lambdas.
    val mapRef = remember { mutableStateOf<MapView?>(null) }

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

    // Apply the selected source to the MapView. Rebuilt on every switch — the
    // backend tile source captures the current JWT in its URL, so this also
    // refreshes auth on token rotation.
    LaunchedEffect(mapRef.value, selectedMap) {
        val map = mapRef.value ?: return@LaunchedEffect
        val src = selectedMap
        val tileSource = if (src == null || src.url_template.startsWith("http")) {
            // OSM (or no MBTiles known yet) — OSMdroid's built-in Mapnik handles tile fetch.
            BackendTileSource.OSM_DEFAULT
        } else {
            val token = container.tokenStore.current().orEmpty()
            val base  = container.settingsRepository.currentServerUrl()
            BackendTileSource(
                sourceName = src.name,
                title      = src.title,
                minZoom    = src.min_zoom,
                maxZoom    = src.max_zoom,
                format     = src.format,
                baseUrl    = base,
                token      = token,
            )
        }
        map.setTileSource(tileSource)

        // Clamp the map's zoom limits — and the current zoom — into the new
        // source's range. Without this, switching to a world-coverage MBTiles
        // (e.g. z 0..7) while viewing at z 8+ shows a black map because the
        // source has nothing to render at that level.
        val minZ = tileSource.minimumZoomLevel.toDouble()
        val maxZ = tileSource.maximumZoomLevel.toDouble()
        map.setMinZoomLevel(minZ)
        map.setMaxZoomLevel(maxZ)
        val z = map.zoomLevelDouble
        if (z > maxZ) map.controller.setZoom(maxZ)
        else if (z < minZ) map.controller.setZoom(minZ)

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

    LaunchedEffect(operators, enemies, fireMissions, cbrnReports, cbrnVisible, meId, overlayMode, tgVisible, myPlatoonIds) {
        val map = mapRef.value ?: return@LaunchedEffect
        val res = map.resources
        val currentMeId = meId

        // Wipe ALL transient overlays we own (markers + tactical graphic
        // polylines/polygons) before rebuilding. The base map-events overlay
        // sits on a different overlay slot and isn't a Marker/Polyline/Polygon.
        map.overlays.removeAll {
            it is Marker || it is org.osmdroid.views.overlay.Polyline ||
            it is org.osmdroid.views.overlay.Polygon
        }

        val visibleOps = when (overlayMode) {
            OverlayMode.ALL         -> operators
            OverlayMode.NONE        -> emptyList()
            OverlayMode.ENEMIES     -> emptyList()
            OverlayMode.OWN_PLATOON -> operators.filter { it.id in myPlatoonIds || it.id == currentMeId }
        }
        // Two independent layers:
        //   • legacy hostile/POI/objective markers ← gated by overlayMode
        //   • tactical control graphics            ← gated by tgVisible
        val showLegacyHostiles = overlayMode == OverlayMode.ALL || overlayMode == OverlayMode.ENEMIES
        val visibleEnemies = if (showLegacyHostiles)
            enemies.filterNot { MilSymbolRenderer.isTacticalGraphic(it.type) ||
                                MilSymbolRenderer.isTacticalLineOrPolygon(it.type) }
        else emptyList()
        val visibleGraphics = if (tgVisible)
            enemies.filter { MilSymbolRenderer.isTacticalGraphic(it.type) ||
                             MilSymbolRenderer.isTacticalLineOrPolygon(it.type) }
        else emptyList()

        for (op in visibleOps) {
            if (op.latitude == null || op.longitude == null) continue
            val isMe = op.id == currentMeId
            val marker = Marker(map).apply {
                position = GeoPoint(op.latitude, op.longitude)
                title    = if (isMe) "📍 You — ${op.callsign}" else "${op.callsign}  ·  ${op.rank}"
                snippet  = "${op.role}${if (op.online) " · online" else " · offline"}"
                // Synchronous placeholder while milsymbol.js renders the proper
                // MIL-STD-2525 SVG asynchronously. Anchored CENTER/CENTER —
                // updated below when the real bitmap arrives.
                icon     = MilSymbolRenderer.friendly(res, op, isMe)
                if (isMe) setAnchor(Marker.ANCHOR_CENTER, 0.39f)
                else      setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                map.overlays.add(this)
            }
            if (!isMe) {
                // SIDC for friendly ground combat infantry, with battle-captain
                // headquarters modifier ("E" at position 11) when applicable.
                val sidc = if (op.role.equals("BATTLE_CAPTAIN", true)) "SFGPUCI----E"
                           else                                       "SFGPUCI-----"
                scope.launch {
                    val opts = mapOf<String, Any?>(
                        "size" to 28,
                        "uniqueDesignation" to op.callsign,
                        "additionalInformation" to (if (op.online) "" else "OFFLINE"),
                    )
                    container.milsymRenderer.symbol(sidc, opts)?.let { r ->
                        marker.icon = r.drawable
                        marker.setAnchor(r.anchorX, r.anchorY)
                        map.invalidate()
                    }
                }
            }
        }

        for (e in visibleEnemies) {
            if (e.type == "OBJECTIVE") {
                // Objectives store "title\ndescription\nMGRS:..." in notes (web format).
                val notes  = e.notes
                val nl     = notes.indexOf('\n')
                val titleS = if (nl >= 0) notes.substring(0, nl) else notes
                val rest   = if (nl >= 0) notes.substring(nl + 1) else ""
                val descS  = rest.lineSequence().filterNot { it.startsWith("MGRS:") }
                                  .joinToString("\n").trim()
                Marker(map).apply {
                    position = GeoPoint(e.latitude, e.longitude)
                    title    = "🚩 ${titleS.ifBlank { "Objective" }}"
                    snippet  = descS.ifBlank { "(no description)" }
                    icon     = MilSymbolRenderer.objective(res)
                    setAnchor(Marker.ANCHOR_BOTTOM, Marker.ANCHOR_BOTTOM)
                    setOnMarkerClickListener { m, _ ->
                        selectedObjective = e
                        m.showInfoWindow()
                        true
                    }
                    map.overlays.add(this)
                }
                continue
            }
            // Backend often sends type="ENEMY" with the real unit in symbol_code,
            // so resolve from the SIDC first; fall back to the textual type.
            val type = EnemyType.resolve(e.type, e.symbolCode)
            val marker = Marker(map).apply {
                position = GeoPoint(e.latitude, e.longitude)
                title    = type.label
                snippet  = e.notes.ifBlank { "SIDC: ${e.symbolCode}" }
                // Synchronous placeholder — replaced by the milsymbol-rendered
                // bitmap when ready (POIs keep the hand-drawn yellow disc).
                icon     = if (type == EnemyType.POI) MilSymbolRenderer.poi(res)
                           else MilSymbolRenderer.hostile(res, type)
                setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                map.overlays.add(this)
            }
            if (type != EnemyType.POI) {
                // Trust the server's SIDC when present; fall back to the
                // per-type default (which already encodes the right affiliation
                // and function modifier).
                val sidc = if (e.symbolCode.length >= 10) e.symbolCode else type.sidc
                scope.launch {
                    container.milsymRenderer.symbol(
                        sidc, mapOf("size" to 30),
                    )?.let { r ->
                        marker.icon = r.drawable
                        marker.setAnchor(r.anchorX, r.anchorY)
                        map.invalidate()
                    }
                }
            }
        }

        // ── Tactical control graphics (Phase 2 render-only) ─────────────────
        for (g in visibleGraphics) {
            renderTacticalGraphic(map, res, g)
        }

        // Fire missions — always visible except in NONE mode
        if (overlayMode != OverlayMode.NONE) {
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

        // ── CBRN hazard layer ───────────────────────────────────────────────
        if (cbrnVisible) {
            for ((_, payload) in cbrnReports) {
                for (ov in com.arrow.tactical.cbrn.buildCbrnOverlays(map, res, payload)) {
                    map.overlays.add(ov)
                }
            }
        }

        map.invalidate()
    }

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
                    controller.setZoom(8.0)
                    controller.setCenter(GeoPoint(50.85, 4.35))

                    val events = MapEventsOverlay(object : MapEventsReceiver {
                        override fun singleTapConfirmedHelper(p: GeoPoint?): Boolean {
                            p ?: return false
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
                    overlays.add(0, events)
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
        Column(modifier = Modifier.fillMaxWidth().align(Alignment.TopStart)) {
            SitawareTopBar(
                brand   = "ARROW",
                mgrs    = mgrs,
                online  = serverOnline == true,
                alertCount = activeAlerts,
                chatCount  = 0,
                onMenu       = onOpenDrawer,
                onReportLayer= { onReport(me?.latitude ?: Double.NaN, me?.longitude ?: Double.NaN) },
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

        // ── Call for Fire button — icon-only, compact ────────────────────
        SmallFloatingActionButton(
            onClick        = { onCallFire(Double.NaN, Double.NaN) },
            containerColor = Color(0xFFB91C1C),
            contentColor   = Color.White,
            modifier       = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 12.dp, bottom = 60.dp)
                .size(40.dp),
        ) {
            Icon(Icons.Filled.GpsFixed, contentDescription = "Call for Fire",
                 modifier = Modifier.size(20.dp))
        }

        // ── TIC FAB — icon-only, compact ─────────────────────────────────
        SmallFloatingActionButton(
            onClick        = { scope.launch { container.alertRepository.trigger("TIC") } },
            containerColor = MaterialTheme.colorScheme.error,
            contentColor   = Color.White,
            modifier       = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 12.dp, bottom = 12.dp)
                .size(40.dp),
        ) {
            Icon(Icons.Filled.Warning, contentDescription = "TIC",
                 modifier = Modifier.size(20.dp))
        }

    } // Box

    // ── Radial menu — shown immediately on tap (pendingScreenPos != null) ────
    if (pendingPoint != null && pendingScreenPos != null) {
        val point = pendingPoint!!
        RadialMenu(
            tapOffset = pendingScreenPos!!,
            items = listOf(
                RadialItem("⚠", "Enemy",    Color(0xFFDC2626)) {
                    pendingScreenPos = null          // dismiss radial, show enemy picker
                    menuStep = MenuStep.ENEMY_TYPE
                },
                RadialItem("🎯", "Fire\nMission", Color(0xFFB91C1C)) {
                    val lat = point.latitude; val lon = point.longitude
                    pendingPoint = null; pendingScreenPos = null
                    onCallFire(lat, lon)
                },
                RadialItem("📋", "Report",  Color(0xFF2563EB)) {
                    val lat = point.latitude; val lon = point.longitude
                    pendingPoint = null; pendingScreenPos = null
                    onReport(lat, lon)
                },
                RadialItem("💣", "Mortar\nFDC", Color(0xFFD97706)) {
                    val lat = point.latitude; val lon = point.longitude
                    pendingPoint = null; pendingScreenPos = null
                    onOpenMortar(lat, lon)
                },
                RadialItem("📍", "POI",     Color(0xFFD97706)) {
                    selectedType = EnemyType.POI
                    pendingScreenPos = null          // dismiss radial, show notes sheet
                    menuStep = MenuStep.NOTES
                },
            ),
            onDismiss = { pendingPoint = null; pendingScreenPos = null },
        )
    }

    // ── Bottom sheets — shown after selecting from radial (pendingScreenPos == null) ─
    if (pendingPoint != null && pendingScreenPos == null) {
        ModalBottomSheet(
            onDismissRequest = { pendingPoint = null },
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
                                container.tacticalRepository.listObjects().onSuccess { enemies = it }
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
private fun EnemyTypeMenu(onSelect: (EnemyType) -> Unit, onBack: () -> Unit) {
    val hostileTypes = EnemyType.entries.filter { it != EnemyType.POI }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 24.dp)
            .padding(bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
            }
            Text(
                "Select enemy type",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
        }
        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.heightIn(max = 360.dp),
        ) {
            items(hostileTypes) { type ->
                OutlinedButton(
                    onClick = { onSelect(type) },
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.outlinedButtonColors(
                        contentColor = MaterialTheme.colorScheme.error,
                    ),
                ) {
                    Text(type.label, maxLines = 2)
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
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 24.dp)
            .padding(bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
            }
            Column {
                Text(
                    type.label,
                    style = MaterialTheme.typography.titleMedium,
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
            minLines      = 3,
            maxLines      = 5,
        )

        // Photo section
        if (photoUri != null) {
            Box {
                AsyncImage(
                    model              = photoUri,
                    contentDescription = "Attached photo",
                    modifier           = Modifier
                        .fillMaxWidth()
                        .heightIn(max = 180.dp)
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
