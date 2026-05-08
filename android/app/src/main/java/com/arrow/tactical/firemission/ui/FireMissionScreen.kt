package com.arrow.tactical.firemission.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.network.FireMissionDto
import com.arrow.tactical.network.FireMissionIn
import com.arrow.tactical.network.MgrsConverter
import kotlinx.coroutines.launch

private val MISSION_TYPES = listOf(
    "ADJUST_FIRE"           to "Adjust Fire (AF)",
    "FIRE_FOR_EFFECT"       to "Fire for Effect (FFE)",
    "SUPPRESSION"           to "Suppression",
    "ILLUMINATION"          to "Illumination",
    "IMMEDIATE_SUPPRESSION" to "Immediate Suppression",
)

private val AMMO_TYPES = listOf(
    "HE" to "HE — High Explosive",
    "ILLUM" to "ILLUM — Illumination",
    "SMOKE" to "SMOKE",
    "WP"    to "WP — White Phosphorus",
    "ICM"   to "ICM — Improved Conv. Munition",
    "AP"    to "AP — Anti-Personnel",
    "FRAG"  to "FRAG",
    "MIXED" to "MIXED",
)

private val STATUS_COLORS = mapOf(
    "PENDING"    to Color(0xFFDC2626),
    "ACKNOWLEDGED" to Color(0xFFD97706),
    "IN_PROGRESS"  to Color(0xFF2563EB),
    "COMPLETED"    to Color(0xFF16A34A),
    "CANCELLED"    to Color(0xFF475569),
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FireMissionScreen(
    container:  AppContainer,
    presetLat:  Double? = null,
    presetLon:  Double? = null,
    onBack:     () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var tab by remember { mutableStateOf(0) }  // 0 = Call Fire, 1 = Log

    // Form state — coordinates stored as MGRS string
    var mgrs        by remember { mutableStateOf("") }
    var mgrsError   by remember { mutableStateOf(false) }
    var lat         by remember { mutableStateOf(0.0) }
    var lon         by remember { mutableStateOf(0.0) }
    var alt         by remember { mutableStateOf("") }
    var direction   by remember { mutableStateOf("") }
    var missionType by remember { mutableStateOf(MISSION_TYPES[0].first) }
    var ammunition  by remember { mutableStateOf(AMMO_TYPES[0].first) }
    var quantity    by remember { mutableStateOf("1") }
    var description by remember { mutableStateOf("") }
    var submitting  by remember { mutableStateOf(false) }
    var statusMsg   by remember { mutableStateOf<Pair<Boolean,String>?>(null) }

    var missions    by remember { mutableStateOf<List<FireMissionDto>>(emptyList()) }

    LaunchedEffect(Unit) {
        container.fireMissionRepository.list().onSuccess { missions = it }

        if (presetLat != null && presetLon != null && !presetLat.isNaN() && !presetLon.isNaN()) {
            // Pre-fill from map tap
            lat = presetLat; lon = presetLon
            runCatching { mgrs = MgrsConverter.encode(presetLat, presetLon) }
        } else {
            // Pre-fill from GPS
            container.authRepository.me().onSuccess { me ->
                container.tacticalRepository.listOperators().onSuccess { ops ->
                    val op = ops.find { it.id == me.id }
                    if (op?.latitude != null && op.longitude != null) {
                        lat = op.latitude; lon = op.longitude
                        alt = "%.0f".format(op.altitude ?: 0.0)
                        runCatching { mgrs = MgrsConverter.encode(op.latitude, op.longitude) }
                    }
                }
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("🎯 Call for Fire", fontWeight = FontWeight.Bold)
                        Text("Artillery Fire Mission", style = MaterialTheme.typography.labelSmall,
                             color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.25f),
                ),
            )
        },
    ) { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxSize()) {

            // Tab bar
            TabRow(selectedTabIndex = tab) {
                Tab(selected = tab == 0, onClick = { tab = 0 },
                    text = { Text("Call Fire", fontSize = 12.sp) })
                Tab(selected = tab == 1, onClick = {
                        tab = 1
                        scope.launch { container.fireMissionRepository.list().onSuccess { missions = it } }
                    },
                    text = { Text("Mission Log", fontSize = 12.sp) })
            }

            if (tab == 0) {
                // ── Call Fire form ─────────────────────────────────────────
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(16.dp)
                        .imePadding(),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    // Target location — MGRS
                    Text("Target Location", style = MaterialTheme.typography.labelLarge,
                         color = MaterialTheme.colorScheme.error)
                    OutlinedTextField(
                        value         = mgrs,
                        onValueChange = { v ->
                            mgrs = v.uppercase()
                            mgrsError = false
                            // Live parse: update internal lat/lon when valid
                            runCatching { MgrsConverter.decode(v) }.onSuccess { (la, lo) ->
                                lat = la; lon = lo
                            }
                        },
                        label       = { Text("MGRS Grid") },
                        placeholder = { Text("e.g. 31U ES 83612 87180") },
                        isError     = mgrsError,
                        supportingText = if (mgrsError) {{ Text("Invalid MGRS — check format") }}
                                         else if (lat != 0.0) {{ Text("%.5f, %.5f".format(lat, lon),
                                             style = MaterialTheme.typography.labelSmall,
                                             color = MaterialTheme.colorScheme.onSurfaceVariant) }}
                                         else null,
                        modifier    = Modifier.fillMaxWidth(),
                        singleLine  = true,
                        textStyle   = MaterialTheme.typography.bodyMedium.copy(
                            fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace),
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = alt, onValueChange = { alt = it },
                            label = { Text("Altitude (m MSL)") }, singleLine = true,
                            modifier = Modifier.weight(1f),
                            textStyle = MaterialTheme.typography.bodyMedium.copy(
                                fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace),
                        )
                        OutlinedTextField(
                            value = direction, onValueChange = { direction = it },
                            label = { Text("Direction (°)") },
                            placeholder = { Text("0–360") }, singleLine = true,
                            modifier = Modifier.weight(1f),
                            textStyle = MaterialTheme.typography.bodyMedium.copy(
                                fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace),
                        )
                    }

                    HorizontalDivider()

                    // Mission type (AF / FFE)
                    Text("Type of Mission", style = MaterialTheme.typography.labelLarge,
                         color = MaterialTheme.colorScheme.error)
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp),
                        modifier = Modifier.fillMaxWidth()) {
                        MISSION_TYPES.forEach { (key, lbl) ->
                            FilterChip(
                                selected = missionType == key,
                                onClick  = { missionType = key },
                                label    = { Text(lbl.substringBefore(" (").take(12), fontSize = 12.sp) },
                                modifier = Modifier.weight(1f),
                                colors   = FilterChipDefaults.filterChipColors(
                                    selectedContainerColor = MaterialTheme.colorScheme.error.copy(alpha = 0.2f),
                                    selectedLabelColor     = MaterialTheme.colorScheme.error,
                                ),
                            )
                        }
                    }

                    HorizontalDivider()

                    // Ammunition
                    Text("Ammunition", style = MaterialTheme.typography.labelLarge,
                         color = MaterialTheme.colorScheme.error)
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        AMMO_TYPES.take(4).forEach { (key, _) ->
                            FilterChip(
                                selected = ammunition == key,
                                onClick  = { ammunition = key },
                                label    = { Text(key, fontSize = 12.sp) },
                                modifier = Modifier.weight(1f),
                                colors   = FilterChipDefaults.filterChipColors(
                                    selectedContainerColor = Color(0xFFD97706).copy(alpha = 0.2f),
                                    selectedLabelColor     = Color(0xFFD97706),
                                ),
                            )
                        }
                    }
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        AMMO_TYPES.drop(4).forEach { (key, _) ->
                            FilterChip(
                                selected = ammunition == key,
                                onClick  = { ammunition = key },
                                label    = { Text(key, fontSize = 12.sp) },
                                modifier = Modifier.weight(1f),
                                colors   = FilterChipDefaults.filterChipColors(
                                    selectedContainerColor = Color(0xFFD97706).copy(alpha = 0.2f),
                                    selectedLabelColor     = Color(0xFFD97706),
                                ),
                            )
                        }
                    }

                    OutlinedTextField(
                        value = quantity, onValueChange = { quantity = it },
                        label = { Text("Rounds / quantity") }, singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )

                    HorizontalDivider()

                    // Target description
                    Text("Target Description", style = MaterialTheme.typography.labelLarge,
                         color = MaterialTheme.colorScheme.error)
                    OutlinedTextField(
                        value = description, onValueChange = { description = it },
                        label = { Text("e.g. Infantry platoon in open, moving NE") },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 3, maxLines = 5,
                    )

                    statusMsg?.let { (ok, msg) ->
                        Text(msg,
                             color = if (ok) Color(0xFF22C55E) else MaterialTheme.colorScheme.error,
                             style = MaterialTheme.typography.bodySmall)
                    }

                    Button(
                        enabled  = !submitting,
                        modifier = Modifier.fillMaxWidth(),
                        colors   = ButtonDefaults.buttonColors(containerColor = Color(0xFFDC2626)),
                        onClick  = {
                            val dirD = direction.toDoubleOrNull()
                            // Validate MGRS
                            val parsed = runCatching { MgrsConverter.decode(mgrs) }.getOrNull()
                            if (parsed == null) { mgrsError = true; return@Button }
                            if (dirD == null) {
                                statusMsg = false to "Direction (azimuth) is required."
                                return@Button
                            }
                            submitting = true; statusMsg = null; mgrsError = false
                            scope.launch {
                                container.fireMissionRepository.submit(
                                    FireMissionIn(
                                        latitude    = parsed.first,
                                        longitude   = parsed.second,
                                        altitude    = alt.toDoubleOrNull() ?: 0.0,
                                        direction   = dirD,
                                        missionType = missionType,
                                        ammunition  = ammunition,
                                        quantity    = quantity.toIntOrNull() ?: 1,
                                        description = description,
                                    )
                                ).onSuccess {
                                    statusMsg   = true to "✓ Fire mission submitted to FDC"
                                    description = ""
                                    container.fireMissionRepository.list()
                                        .onSuccess { missions = it }
                                }.onFailure {
                                    statusMsg = false to "✗ ${it.message}"
                                }
                                submitting = false
                            }
                        },
                    ) {
                        Text(
                            if (submitting) "Transmitting…"
                            else "🎯  CALL FOR FIRE  —  ${MISSION_TYPES.find { it.first == missionType }?.second ?: missionType}",
                            fontWeight = FontWeight.Bold,
                        )
                    }

                    Spacer(Modifier.height(16.dp))
                }
            } else {
                // ── Mission log ────────────────────────────────────────────
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    if (missions.isEmpty()) {
                        item {
                            Text("No fire missions yet.",
                                 color = MaterialTheme.colorScheme.onSurfaceVariant,
                                 modifier = Modifier.padding(16.dp))
                        }
                    } else {
                        items(missions) { fm -> FireMissionRow(fm) }
                    }
                }
            }
        }
    }
}

@Composable
private fun FireMissionRow(fm: FireMissionDto) {
    val color    = STATUS_COLORS[fm.status] ?: Color(0xFF64748B)
    var expanded by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .border(0.5.dp, color.copy(alpha = 0.5f), RoundedCornerShape(8.dp))
            .background(color.copy(alpha = 0.05f), RoundedCornerShape(8.dp))
            .padding(10.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Surface(color = color.copy(alpha = 0.2f), shape = RoundedCornerShape(4.dp)) {
                Text(fm.status, modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                     style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold,
                     color = color)
            }
            Text(fm.missionType.replace('_', ' '),
                 style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold,
                 modifier = Modifier.weight(1f))
            Text(fm.ammunition, style = MaterialTheme.typography.labelSmall,
                 color = Color(0xFFD97706))
            IconButton(onClick = { expanded = !expanded }, modifier = Modifier.size(20.dp)) {
                Icon(if (expanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                     null, modifier = Modifier.size(16.dp))
            }
        }

        if (expanded) {
            Spacer(Modifier.height(6.dp))
            HorizontalDivider(color = color.copy(alpha = 0.2f))
            Spacer(Modifier.height(6.dp))
            val mgrsStr = runCatching { MgrsConverter.encode(fm.latitude, fm.longitude) }
                .getOrDefault("%.5f, %.5f".format(fm.latitude, fm.longitude))
            listOf(
                "Grid"        to mgrsStr,
                "Alt"         to "${fm.altitude.toInt()} m MSL",
                "Direction"   to "${fm.direction.toInt()}°",
                "Qty"         to "${fm.quantity} rounds",
                "Description" to fm.description.ifBlank { "—" },
                "Time"        to (fm.timestamp?.take(16) ?: "—"),
            ).forEach { (lbl, value) ->
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(lbl, style = MaterialTheme.typography.labelSmall,
                         color = MaterialTheme.colorScheme.onSurfaceVariant,
                         modifier = Modifier.width(72.dp))
                    Text(value, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}
