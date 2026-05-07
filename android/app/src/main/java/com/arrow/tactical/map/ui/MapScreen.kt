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
import androidx.compose.material.icons.filled.MyLocation
import androidx.compose.material.icons.filled.Warning
import androidx.compose.ui.layout.ContentScale
import coil.compose.AsyncImage
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.Canvas
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

private enum class MenuStep { CATEGORY, ENEMY_TYPE, NOTES }
private enum class OverlayMode { ALL, NONE, ENEMIES, OWN_PLATOON }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MapScreen(container: AppContainer, onCallFire: () -> Unit = {}) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var operators by remember { mutableStateOf<List<OperatorDto>>(emptyList()) }
    var enemies by remember { mutableStateOf<List<TacticalObjectDto>>(emptyList()) }
    var meId by remember { mutableStateOf<Int?>(null) }
    var hasAutocentered by remember { mutableStateOf(false) }
    var fetchError by remember { mutableStateOf<String?>(null) }
    var serverUrl by remember { mutableStateOf("") }
    // null = checking, true = online, false = offline
    var serverOnline by remember { mutableStateOf<Boolean?>(null) }
    var overlayMode by remember { mutableStateOf(OverlayMode.ALL) }
    var myPlatoonIds by remember { mutableStateOf<Set<Int>>(emptySet()) }

    LaunchedEffect(Unit) {
        serverUrl = container.settingsRepository.currentServerUrl()
    }

    // Resolve own-platoon membership from hierarchy whenever meId becomes available
    LaunchedEffect(meId) {
        val id = meId ?: return@LaunchedEffect
        container.tacticalRepository.getHierarchyJson()
            .onSuccess { json ->
                myPlatoonIds = parsePlatoonIds(json, id)
            }
    }

    // Bottom-sheet state — written from the OSMdroid tap callback
    val pendingPointState = remember { mutableStateOf<GeoPoint?>(null) }
    var pendingPoint by pendingPointState
    var menuStep by remember { mutableStateOf(MenuStep.CATEGORY) }
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

    LaunchedEffect(operators, enemies, meId, overlayMode, myPlatoonIds) {
        val map = mapRef.value ?: return@LaunchedEffect
        val res = map.resources
        val currentMeId = meId

        map.overlays.removeAll { it is Marker }

        val visibleOps = when (overlayMode) {
            OverlayMode.ALL        -> operators
            OverlayMode.NONE       -> emptyList()
            OverlayMode.ENEMIES    -> emptyList()
            OverlayMode.OWN_PLATOON -> operators.filter { it.id in myPlatoonIds || it.id == currentMeId }
        }
        val visibleEnemies = when (overlayMode) {
            OverlayMode.ALL, OverlayMode.ENEMIES -> enemies
            else -> emptyList()
        }

        for (op in visibleOps) {
            if (op.latitude == null || op.longitude == null) continue
            val isMe = op.id == currentMeId
            Marker(map).apply {
                position = GeoPoint(op.latitude, op.longitude)
                title    = if (isMe) "You — ${op.callsign}" else "${op.callsign}  ·  ${op.rank}"
                snippet  = "${op.role} · ${op.status}"
                icon     = MilSymbolRenderer.friendly(res, op, isMe)
                setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                map.overlays.add(this)
            }
        }

        for (e in visibleEnemies) {
            val type = runCatching { EnemyType.valueOf(e.type) }.getOrElse { EnemyType.UNKNOWN }
            Marker(map).apply {
                position = GeoPoint(e.latitude, e.longitude)
                title    = type.label
                snippet  = e.notes.ifBlank { "SIDC: ${e.symbolCode}" }
                icon     = if (type == EnemyType.POI) MilSymbolRenderer.poi(res)
                           else MilSymbolRenderer.hostile(res, type)
                setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                map.overlays.add(this)
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
                            pendingPointState.value = p
                            menuStep        = MenuStep.CATEGORY
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

        // ── Status + overlay bar — Compose layer (always above the map) ───
        val online = operators.count { it.online }
        val dotColor = when (serverOnline) {
            true  -> Color(0xFF22C55E)
            false -> MaterialTheme.colorScheme.error
            null  -> Color(0xFFFBBF24)
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.TopStart)
                .background(Color(0xE50D1117))   // 90 % opaque dark
                .padding(horizontal = 8.dp, vertical = 3.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Canvas(Modifier.size(9.dp)) { drawCircle(dotColor) }

            Text(
                text  = if (serverOnline == false) "ARROW — OFFLINE"
                        else "ARROW  ·  $online / ${operators.size} online",
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

        // ── 🎯 Call for Fire FAB ──────────────────────────────────────────
        FloatingActionButton(
            onClick        = onCallFire,
            containerColor = Color(0xFFB91C1C),
            modifier       = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 16.dp, bottom = 72.dp)
                .size(44.dp),
        ) {
            Text("🎯", fontSize = 20.sp)
        }

        // ── TIC FAB ───────────────────────────────────────────────────────
        FloatingActionButton(
            onClick        = { scope.launch { container.alertRepository.trigger("TIC") } },
            containerColor = MaterialTheme.colorScheme.error,
            modifier       = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 16.dp, bottom = 16.dp)
                .size(44.dp),
        ) {
            Icon(Icons.Filled.Warning, contentDescription = "TIC", tint = Color.White,
                 modifier = Modifier.size(22.dp))
        }

    } // Box

    // Bottom sheet — shown whenever a map point is pending
    if (pendingPoint != null) {
        ModalBottomSheet(
            onDismissRequest = { pendingPoint = null },
        ) {
            val point = pendingPoint ?: return@ModalBottomSheet
            when (menuStep) {
                MenuStep.CATEGORY -> CategoryMenu(
                    point = point,
                    onEnemy = { menuStep = MenuStep.ENEMY_TYPE },
                    onPoi = {
                        selectedType = EnemyType.POI
                        menuStep = MenuStep.NOTES
                    },
                )

                MenuStep.ENEMY_TYPE -> EnemyTypeMenu(
                    onSelect = { type ->
                        selectedType = type
                        menuStep = MenuStep.NOTES
                    },
                    onBack = { menuStep = MenuStep.CATEGORY },
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
                        menuStep        = if (selectedType == EnemyType.POI) MenuStep.CATEGORY else MenuStep.ENEMY_TYPE
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
private fun CategoryMenu(point: GeoPoint, onEnemy: () -> Unit, onPoi: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 24.dp)
            .padding(bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(
            "Mark location",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            "%.5f, %.5f".format(point.latitude, point.longitude),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(4.dp))
        Button(
            onClick = onEnemy,
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
        ) {
            Text("⚠ Enemy location")
        }
        OutlinedButton(
            onClick = onPoi,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("📍 POI / Observation")
        }
    }
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
