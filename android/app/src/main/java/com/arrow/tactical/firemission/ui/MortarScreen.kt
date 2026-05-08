package com.arrow.tactical.firemission.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.network.GunIn
import com.arrow.tactical.network.LatLon
import com.arrow.tactical.network.MgrsConverter
import com.arrow.tactical.network.MortarPlanIn
import com.arrow.tactical.network.MortarPlanResult
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

private val PATTERNS = listOf("POINT", "LINE", "ZONE")
private val AMMO    = listOf("HE", "ILLUM", "SMOKE", "WP")

private data class GunInput(
    val callsign: String = "",
    val mgrs:     String = "",
    val lat:      Double = 0.0,
    val lon:      Double = 0.0,
    val alt:      String = "",
    val refAz:    String = "0",
    val mgrsErr:  Boolean = false,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MortarScreen(
    container: AppContainer,
    presetLat: Double? = null,
    presetLon: Double? = null,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var gunCount by remember { mutableStateOf(2) }   // 1..4
    var guns by remember { mutableStateOf(List(4) { GunInput(callsign = "M${it + 1}") }) }
    var pattern  by remember { mutableStateOf("POINT") }
    var ammo     by remember { mutableStateOf("HE") }
    var rounds   by remember { mutableStateOf("4") }

    // Target inputs
    var pointMgrs   by remember { mutableStateOf("") }
    var pointLat    by remember { mutableStateOf(0.0) }
    var pointLon    by remember { mutableStateOf(0.0) }
    var pointMgrsErr by remember { mutableStateOf(false) }

    var lineStartMgrs by remember { mutableStateOf("") }
    var lineEndMgrs   by remember { mutableStateOf("") }
    var lineStart by remember { mutableStateOf(0.0 to 0.0) }
    var lineEnd   by remember { mutableStateOf(0.0 to 0.0) }

    var zoneCenterMgrs by remember { mutableStateOf("") }
    var zoneCenter by remember { mutableStateOf(0.0 to 0.0) }
    var zoneWidth  by remember { mutableStateOf("100") }
    var zoneHeight by remember { mutableStateOf("100") }
    var zoneRot    by remember { mutableStateOf("0") }

    var targetAlt   by remember { mutableStateOf("") }
    var description by remember { mutableStateOf("") }

    var solving    by remember { mutableStateOf(false) }
    var firing     by remember { mutableStateOf(false) }
    var statusMsg  by remember { mutableStateOf<Pair<Boolean, String>?>(null) }
    var result     by remember { mutableStateOf<MortarPlanResult?>(null) }

    LaunchedEffect(Unit) {
        // Auto-fill gun-1 from current operator GPS if available
        container.authRepository.me().onSuccess { me ->
            container.tacticalRepository.listOperators().onSuccess { ops ->
                val o = ops.find { it.id == me.id } ?: return@onSuccess
                if (o.latitude != null && o.longitude != null) {
                    val mg = runCatching { MgrsConverter.encode(o.latitude, o.longitude) }.getOrDefault("")
                    guns = guns.toMutableList().also {
                        it[0] = it[0].copy(
                            mgrs = mg, lat = o.latitude, lon = o.longitude,
                            alt = "%.0f".format(o.altitude ?: 0.0),
                        )
                    }
                }
            }
        }
        if (presetLat != null && presetLon != null && !presetLat.isNaN() && !presetLon.isNaN()) {
            pointLat = presetLat; pointLon = presetLon
            runCatching { pointMgrs = MgrsConverter.encode(presetLat, presetLon) }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("🛡️  Mortar Section — L16 81 mm", fontWeight = FontWeight.Bold)
                        Text("Fire Direction Centre",
                             style = MaterialTheme.typography.labelSmall,
                             color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color(0xFFD97706).copy(alpha = 0.15f),
                ),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(16.dp)
                .imePadding(),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            // ── Gun line ──
            Text("Gun Line  (1–4)", style = MaterialTheme.typography.labelLarge,
                 color = Color(0xFFD97706))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                (1..4).forEach { n ->
                    FilterChip(
                        selected = gunCount == n, onClick = { gunCount = n },
                        label = { Text("$n") }, modifier = Modifier.weight(1f),
                    )
                }
            }

            for (i in 0 until gunCount) {
                val g = guns[i]
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .border(0.5.dp, Color(0xFFD97706).copy(alpha = 0.4f), RoundedCornerShape(8.dp))
                        .background(Color(0xFFD97706).copy(alpha = 0.04f), RoundedCornerShape(8.dp))
                        .padding(8.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text("Gun ${i + 1}", style = MaterialTheme.typography.labelMedium,
                         fontWeight = FontWeight.Bold)
                    OutlinedTextField(
                        value = g.callsign,
                        onValueChange = { v ->
                            guns = guns.toMutableList().also { it[i] = it[i].copy(callsign = v) }
                        },
                        label = { Text("Callsign") }, singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = g.mgrs,
                        onValueChange = { v ->
                            val up = v.uppercase()
                            val parsed = runCatching { MgrsConverter.decode(up) }.getOrNull()
                            guns = guns.toMutableList().also {
                                it[i] = it[i].copy(
                                    mgrs = up,
                                    lat = parsed?.first ?: it[i].lat,
                                    lon = parsed?.second ?: it[i].lon,
                                    mgrsErr = false,
                                )
                            }
                        },
                        label = { Text("Position MGRS") },
                        placeholder = { Text("e.g. 31U FT 12345 67890") },
                        isError = g.mgrsErr,
                        modifier = Modifier.fillMaxWidth(), singleLine = true,
                        textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        OutlinedTextField(
                            value = g.alt,
                            onValueChange = { v ->
                                guns = guns.toMutableList().also { it[i] = it[i].copy(alt = v) }
                            },
                            label = { Text("Alt (m)") }, modifier = Modifier.weight(1f),
                            singleLine = true,
                        )
                        OutlinedTextField(
                            value = g.refAz,
                            onValueChange = { v ->
                                guns = guns.toMutableList().also { it[i] = it[i].copy(refAz = v) }
                            },
                            label = { Text("Ref Az (mils)") }, modifier = Modifier.weight(1f),
                            singleLine = true,
                        )
                    }
                }
            }

            HorizontalDivider()

            // ── Target shape ──
            Text("Target Shape", style = MaterialTheme.typography.labelLarge,
                 color = MaterialTheme.colorScheme.error)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
                PATTERNS.forEach { p ->
                    FilterChip(
                        selected = pattern == p, onClick = { pattern = p },
                        label = { Text(p) }, modifier = Modifier.weight(1f),
                    )
                }
            }

            when (pattern) {
                "POINT" -> {
                    OutlinedTextField(
                        value = pointMgrs,
                        onValueChange = { v ->
                            val up = v.uppercase()
                            pointMgrs = up
                            pointMgrsErr = false
                            runCatching { MgrsConverter.decode(up) }.onSuccess { (la, lo) ->
                                pointLat = la; pointLon = lo
                            }
                        },
                        label = { Text("Target MGRS") },
                        isError = pointMgrsErr,
                        modifier = Modifier.fillMaxWidth(), singleLine = true,
                        textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                        supportingText = if (pointLat != 0.0)
                            { { Text("%.5f, %.5f".format(pointLat, pointLon)) } } else null,
                    )
                }
                "LINE" -> {
                    OutlinedTextField(
                        value = lineStartMgrs,
                        onValueChange = { v ->
                            val up = v.uppercase()
                            lineStartMgrs = up
                            runCatching { MgrsConverter.decode(up) }.onSuccess { lineStart = it }
                        },
                        label = { Text("Line — START MGRS") },
                        modifier = Modifier.fillMaxWidth(), singleLine = true,
                        textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                    )
                    OutlinedTextField(
                        value = lineEndMgrs,
                        onValueChange = { v ->
                            val up = v.uppercase()
                            lineEndMgrs = up
                            runCatching { MgrsConverter.decode(up) }.onSuccess { lineEnd = it }
                        },
                        label = { Text("Line — END MGRS") },
                        modifier = Modifier.fillMaxWidth(), singleLine = true,
                        textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                    )
                }
                "ZONE" -> {
                    OutlinedTextField(
                        value = zoneCenterMgrs,
                        onValueChange = { v ->
                            val up = v.uppercase()
                            zoneCenterMgrs = up
                            runCatching { MgrsConverter.decode(up) }.onSuccess { zoneCenter = it }
                        },
                        label = { Text("Zone — CENTER MGRS") },
                        modifier = Modifier.fillMaxWidth(), singleLine = true,
                        textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        OutlinedTextField(value = zoneWidth, onValueChange = { zoneWidth = it },
                            label = { Text("Width (m)") }, singleLine = true,
                            modifier = Modifier.weight(1f))
                        OutlinedTextField(value = zoneHeight, onValueChange = { zoneHeight = it },
                            label = { Text("Depth (m)") }, singleLine = true,
                            modifier = Modifier.weight(1f))
                        OutlinedTextField(value = zoneRot, onValueChange = { zoneRot = it },
                            label = { Text("Rot mils") }, singleLine = true,
                            modifier = Modifier.weight(1f))
                    }
                }
            }

            OutlinedTextField(
                value = targetAlt, onValueChange = { targetAlt = it },
                label = { Text("Target altitude (m MSL, optional)") }, singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )

            HorizontalDivider()

            // ── Ammo ──
            Text("Ammunition", style = MaterialTheme.typography.labelLarge, color = Color(0xFFD97706))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
                AMMO.forEach { a ->
                    FilterChip(
                        selected = ammo == a, onClick = { ammo = a },
                        label = { Text(a) }, modifier = Modifier.weight(1f),
                    )
                }
            }
            OutlinedTextField(
                value = rounds, onValueChange = { rounds = it },
                label = { Text("Rounds per gun") }, singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = description, onValueChange = { description = it },
                label = { Text("Description / target description") },
                modifier = Modifier.fillMaxWidth(), minLines = 2, maxLines = 4,
            )

            statusMsg?.let { (ok, m) ->
                Text(m, color = if (ok) Color(0xFF22C55E) else MaterialTheme.colorScheme.error,
                     style = MaterialTheme.typography.bodySmall)
            }

            // ── Actions ──
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    enabled = !solving,
                    modifier = Modifier.weight(1f),
                    onClick = {
                        val plan = buildPlan(guns.take(gunCount), pattern, ammo, rounds, targetAlt,
                            pointLat, pointLon, lineStart, lineEnd, zoneCenter,
                            zoneWidth, zoneHeight, zoneRot, description) ?: run {
                            statusMsg = false to "Fill in valid MGRS for guns and target."; return@OutlinedButton
                        }
                        solving = true; statusMsg = null
                        scope.launch {
                            container.fireMissionRepository.solveMortar(plan)
                                .onSuccess { result = it; statusMsg = true to "Solution computed — review then FIRE." }
                                .onFailure { statusMsg = false to "Solve failed: ${it.message}" }
                            solving = false
                        }
                    },
                ) { Text(if (solving) "Solving…" else "Compute Solution") }

                Button(
                    enabled = !firing && result != null,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFDC2626)),
                    onClick = {
                        val plan = buildPlan(guns.take(gunCount), pattern, ammo, rounds, targetAlt,
                            pointLat, pointLon, lineStart, lineEnd, zoneCenter,
                            zoneWidth, zoneHeight, zoneRot, description) ?: return@Button
                        firing = true; statusMsg = null
                        scope.launch {
                            container.fireMissionRepository.submitMortar(plan)
                                .onSuccess { statusMsg = true to "✓ FIRE MISSION transmitted (#${it.id})" }
                                .onFailure { statusMsg = false to "✗ ${it.message}" }
                            firing = false
                        }
                    },
                ) { Text(if (firing) "Firing…" else "🔥 FIRE") }
            }

            // ── Solution display ──
            result?.let { res ->
                Spacer(Modifier.height(4.dp))
                Text("Firing Solution  ·  ${res.guns.size} gun(s)  ·  ${res.impacts.size} round(s)",
                     style = MaterialTheme.typography.titleSmall,
                     color = Color(0xFFD97706))
                res.guns.forEach { g ->
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .border(0.5.dp, Color(0xFFD97706).copy(alpha = 0.5f), RoundedCornerShape(8.dp))
                            .padding(8.dp),
                    ) {
                        Text("${g.callsign}  (Gun ${g.gunIdx})", fontWeight = FontWeight.Bold)
                        g.solutions.forEachIndexed { idx, s ->
                            val mgrs = runCatching {
                                MgrsConverter.encode(s.impact.latitude, s.impact.longitude)
                            }.getOrDefault("%.4f, %.4f".format(s.impact.latitude, s.impact.longitude))
                            if (s.error != null) {
                                Text(
                                    "  rd ${idx + 1}: ⚠ ${s.error}",
                                    color = MaterialTheme.colorScheme.error,
                                    fontFamily = FontFamily.Monospace, fontSize = 12.sp,
                                )
                            } else {
                                Text(
                                    "  rd ${idx + 1}: Ch ${s.charge}  QE ${s.qeMils}m  Defl ${s.deflMils}m  TOF ${s.tofS}s  R ${s.rangeM.toInt()}m  → $mgrs",
                                    fontFamily = FontFamily.Monospace, fontSize = 12.sp,
                                )
                            }
                        }
                    }
                }
            }

            Spacer(Modifier.height(16.dp))
        }
    }
}

/** Build the MortarPlanIn. Returns null if any required MGRS / lat-lon is missing. */
private fun buildPlan(
    guns: List<GunInput>, pattern: String, ammo: String, rounds: String, targetAlt: String,
    pointLat: Double, pointLon: Double, lineStart: Pair<Double, Double>, lineEnd: Pair<Double, Double>,
    zoneCenter: Pair<Double, Double>, zoneWidth: String, zoneHeight: String, zoneRot: String,
    description: String,
): MortarPlanIn? {
    if (guns.any { it.lat == 0.0 || it.lon == 0.0 }) return null

    val target: JsonObject = when (pattern) {
        "POINT" -> {
            if (pointLat == 0.0 || pointLon == 0.0) return null
            buildJsonObject {
                put("latitude", pointLat); put("longitude", pointLon)
            }
        }
        "LINE" -> {
            if (lineStart.first == 0.0 || lineEnd.first == 0.0) return null
            buildJsonObject {
                put("start", buildJsonObject {
                    put("latitude", lineStart.first); put("longitude", lineStart.second)
                })
                put("end", buildJsonObject {
                    put("latitude", lineEnd.first); put("longitude", lineEnd.second)
                })
            }
        }
        "ZONE" -> {
            if (zoneCenter.first == 0.0) return null
            buildJsonObject {
                put("center", buildJsonObject {
                    put("latitude", zoneCenter.first); put("longitude", zoneCenter.second)
                })
                put("width_m",       (zoneWidth.toDoubleOrNull()  ?: 100.0))
                put("height_m",      (zoneHeight.toDoubleOrNull() ?: 100.0))
                put("rotation_mils", (zoneRot.toDoubleOrNull()    ?: 0.0))
            }
        }
        else -> return null
    }

    return MortarPlanIn(
        guns = guns.map {
            GunIn(
                callsign  = it.callsign,
                latitude  = it.lat, longitude = it.lon,
                altitude  = it.alt.toDoubleOrNull() ?: 0.0,
                referenceAzMils = it.refAz.toDoubleOrNull() ?: 0.0,
            )
        },
        pattern        = pattern,
        target         = target,
        roundsPerGun   = rounds.toIntOrNull() ?: 1,
        targetAltM     = targetAlt.toDoubleOrNull() ?: 0.0,
        ammunition     = ammo,
        description    = description,
    )
}
