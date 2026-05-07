package com.arrow.tactical.reports.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.arrow.tactical.network.ReportDto
import com.arrow.tactical.reports.ReportRepository
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

// ── 9-liner field definitions ─────────────────────────────────────────────────

private data class LineField(
    val number: Int,
    val label: String,
    val hint: String,
    val options: List<String>? = null,   // null = free text, non-null = dropdown
)

private val MEDEVAC_LINES = listOf(
    LineField(1, "Location",              "Grid coordinates of pickup site"),
    LineField(2, "Radio / Call sign",     "Freq and call sign, e.g. 46.35 DUSTOFF"),
    LineField(3, "Patients by precedence","e.g. 1U-2P  (U=Urgent P=Priority R=Routine C=Convenience)"),
    LineField(4, "Special equipment",     "Required equipment",
        listOf("None", "Hoist", "Extraction equipment", "Ventilator")),
    LineField(5, "Patients by type",      "e.g. 1L-2A  (L=Litter  A=Ambulatory)"),
    LineField(6, "Security at PZ",        "Pickup zone security",
        listOf("N – No enemy troops", "P – Possible enemy", "E – Enemy in area", "X – Enemy, armed escort needed")),
    LineField(7, "Marking method",        "How site is marked",
        listOf("Panels", "Pyrotechnics", "Smoke signal", "None", "Other")),
    LineField(8, "Nationality / Status",  "A=US Mil  B=Allied  C=Non-mil  D=EPW"),
    LineField(9, "NBC contamination",     "Contamination",
        listOf("N – None", "C – Chemical", "B – Biological", "R – Radiological")),
)

private val CAS_LINES = listOf(
    LineField(1, "IP (Initial Point)",    "Name or grid of Initial Point"),
    LineField(2, "Heading / Distance",    "Heading & distance from IP to target, e.g. 270° / 5 km"),
    LineField(3, "Target elevation",      "Elevation in metres MSL"),
    LineField(4, "Target description",    "Brief description of the target"),
    LineField(5, "Target location",       "8-digit grid or lat/lon"),
    LineField(6, "Type mark",             "How target is marked",
        listOf("Laser", "Smoke", "IR pointer", "Mark-63", "None")),
    LineField(7, "Friendly location",     "Friendly forces location relative to target"),
    LineField(8, "Egress direction",      "Desired egress direction after attack"),
    LineField(9, "Remarks / Threats",     "Restrictions, threats, TOT"),
)

private val CONTACT_LINES = listOf(
    LineField(1, "Size",                  "Number of personnel / vehicles"),
    LineField(2, "Activity",              "What the enemy is doing"),
    LineField(3, "Location",              "Grid coordinates of contact"),
    LineField(4, "Unit / Identification", "Uniform, markings, nationality"),
    LineField(5, "Time",                  "Time of observation (local / Zulu)"),
    LineField(6, "Equipment",             "Weapons, vehicles, equipment observed"),
    LineField(7, "Direction of movement", "Direction contact is moving"),
    LineField(8, "Additional info",       "Anything else notable"),
    LineField(9, "Reported by",           "Callsign / position of observer"),
)

private data class ReportTypeDef(
    val key: String,
    val label: String,
    val color: Color,
    val lines: List<LineField>,
)

private val REPORT_TYPES = listOf(
    ReportTypeDef("MEDEVAC",  "MEDEVAC",  Color(0xFF16A34A), MEDEVAC_LINES),
    ReportTypeDef("CASEVAC",  "CASEVAC",  Color(0xFF2563EB), MEDEVAC_LINES),
    ReportTypeDef("CAS",      "CAS",      Color(0xFFDC2626), CAS_LINES),
    ReportTypeDef("CONTACT",  "CONTACT",  Color(0xFFD97706), CONTACT_LINES),
    ReportTypeDef("SPOT",     "SPOT",     Color(0xFF7C3AED), CONTACT_LINES),
)

// ── Screen ────────────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReportsScreen(
    repo:      ReportRepository,
    presetLat: Double? = null,
    presetLon: Double? = null,
) {
    val scope = rememberCoroutineScope()
    var selectedType by remember { mutableStateOf(REPORT_TYPES[0]) }
    var values     by remember { mutableStateOf(List(9) { "" }) }
    var submitting by remember { mutableStateOf(false) }
    var statusMsg  by remember { mutableStateOf<String?>(null) }
    var reports    by remember { mutableStateOf<List<ReportDto>>(emptyList()) }
    var showForm   by remember { mutableStateOf(true) }

    LaunchedEffect(Unit) {
        repo.list().onSuccess { reports = it }
        // Pre-fill line 3 (Location) when launched from map tap
        if (presetLat != null && presetLon != null) {
            val mgrsStr = runCatching {
                com.arrow.tactical.network.MgrsConverter.encode(presetLat, presetLon)
            }.getOrDefault("%.5f, %.5f".format(presetLat, presetLon))
            values = List(9) { i -> if (i == 2) mgrsStr else "" }  // index 2 = line 3 = Location
        }
    }

    // Reset form values when type changes (but keep preset if just launched)
    LaunchedEffect(selectedType) { values = List(9) { "" } }

    Scaffold(
        topBar = { TopAppBar(title = { Text("Tactical Reports") }) },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.padding(padding).fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            // ── Type selector ─────────────────────────────────────────────
            item {
                Text("Report type", style = MaterialTheme.typography.labelLarge)
                Spacer(Modifier.height(6.dp))
                Row(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    REPORT_TYPES.forEach { t ->
                        val active = t.key == selectedType.key
                        FilterChip(
                            selected = active,
                            onClick  = { selectedType = t; statusMsg = null },
                            label    = { Text(t.label, fontSize = 11.sp) },
                            colors   = FilterChipDefaults.filterChipColors(
                                selectedContainerColor  = t.color.copy(alpha = 0.18f),
                                selectedLabelColor      = t.color,
                            ),
                        )
                    }
                }
            }

            // ── Form / collapse toggle ────────────────────────────────────
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "${selectedType.label} — 9-Liner",
                        style      = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold,
                        color      = selectedType.color,
                        modifier   = Modifier.weight(1f),
                    )
                    IconButton(onClick = { showForm = !showForm }) {
                        Icon(
                            if (showForm) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                            contentDescription = if (showForm) "Collapse" else "Expand",
                        )
                    }
                }
                HorizontalDivider(color = selectedType.color.copy(alpha = 0.4f))
            }

            // ── 9 line fields ─────────────────────────────────────────────
            if (showForm) {
                items(selectedType.lines) { field ->
                    NineLineField(
                        field    = field,
                        value    = values[field.number - 1],
                        onChange = { v ->
                            values = values.toMutableList().also { it[field.number - 1] = v }
                        },
                        accentColor = selectedType.color,
                    )
                }

                // Submit
                item {
                    Spacer(Modifier.height(4.dp))
                    Button(
                        enabled  = !submitting,
                        modifier = Modifier.fillMaxWidth(),
                        colors   = ButtonDefaults.buttonColors(
                            containerColor = selectedType.color,
                        ),
                        onClick = {
                            submitting = true
                            statusMsg  = null
                            scope.launch {
                                val payload = buildJsonObject {
                                    selectedType.lines.forEachIndexed { i, f ->
                                        put("line_${f.number}", JsonPrimitive(values[i]))
                                        put("label_${f.number}", JsonPrimitive(f.label))
                                    }
                                }
                                repo.submit(selectedType.key, payload)
                                    .onSuccess {
                                        statusMsg = "✓ ${selectedType.label} report submitted"
                                        values = List(9) { "" }
                                        repo.list().onSuccess { reports = it }
                                    }
                                    .onFailure { statusMsg = "✗ ${it.message}" }
                                submitting = false
                            }
                        },
                    ) {
                        Text(if (submitting) "Submitting…" else "Submit ${selectedType.label}")
                    }
                    statusMsg?.let {
                        val isErr = it.startsWith("✗")
                        Text(
                            it,
                            color = if (isErr) MaterialTheme.colorScheme.error else selectedType.color,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
            }

            // ── Recent reports ────────────────────────────────────────────
            if (reports.isNotEmpty()) {
                item {
                    Spacer(Modifier.height(8.dp))
                    Text("Recent Reports", style = MaterialTheme.typography.titleSmall,
                         fontWeight = FontWeight.Bold)
                    HorizontalDivider()
                }
                items(reports) { r -> ReportRow(r) }
            }
        }
    }
}

// ── Composables ───────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun NineLineField(
    field: LineField,
    value: String,
    onChange: (String) -> Unit,
    accentColor: Color,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.Top,
    ) {
        // Line number badge
        Box(
            modifier = Modifier
                .size(28.dp)
                .background(accentColor.copy(alpha = 0.15f), RoundedCornerShape(4.dp))
                .border(1.dp, accentColor.copy(alpha = 0.4f), RoundedCornerShape(4.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                "${field.number}",
                style      = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.Bold,
                color      = accentColor,
            )
        }

        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                field.label,
                style      = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.SemiBold,
            )
            if (field.options != null) {
                DropdownLineField(
                    options     = field.options,
                    selected    = value,
                    onSelect    = onChange,
                    placeholder = field.hint,
                )
            } else {
                OutlinedTextField(
                    value         = value,
                    onValueChange = onChange,
                    placeholder   = { Text(field.hint, fontSize = 11.sp) },
                    modifier      = Modifier.fillMaxWidth(),
                    singleLine    = true,
                    textStyle     = MaterialTheme.typography.bodySmall.copy(
                        fontFamily = FontFamily.Monospace,
                    ),
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DropdownLineField(
    options: List<String>,
    selected: String,
    onSelect: (String) -> Unit,
    placeholder: String,
) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(
        expanded         = expanded,
        onExpandedChange = { expanded = it },
    ) {
        OutlinedTextField(
            value        = selected.ifBlank { placeholder },
            onValueChange = {},
            readOnly     = true,
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
            modifier     = Modifier.menuAnchor().fillMaxWidth(),
            textStyle    = MaterialTheme.typography.bodySmall,
            colors       = ExposedDropdownMenuDefaults.outlinedTextFieldColors(),
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            options.forEach { opt ->
                DropdownMenuItem(
                    text    = { Text(opt, style = MaterialTheme.typography.bodySmall) },
                    onClick = { onSelect(opt); expanded = false },
                )
            }
        }
    }
}

@Composable
private fun ReportRow(report: ReportDto) {
    val typeDef = REPORT_TYPES.find { it.key == report.type }
    val color   = typeDef?.color ?: Color(0xFF64748B)
    var expanded by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .border(0.5.dp, color.copy(alpha = 0.4f), RoundedCornerShape(6.dp))
            .background(color.copy(alpha = 0.05f), RoundedCornerShape(6.dp))
            .padding(10.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Surface(
                color  = color.copy(alpha = 0.18f),
                shape  = RoundedCornerShape(4.dp),
            ) {
                Text(
                    report.type,
                    modifier   = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                    style      = MaterialTheme.typography.labelSmall,
                    fontWeight = FontWeight.Bold,
                    color      = color,
                )
            }
            Text(
                report.timestamp?.take(16) ?: "—",
                style  = MaterialTheme.typography.labelSmall,
                color  = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f),
            )
            IconButton(
                onClick  = { expanded = !expanded },
                modifier = Modifier.size(20.dp),
            ) {
                Icon(
                    if (expanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp),
                )
            }
        }

        if (expanded) {
            Spacer(Modifier.height(6.dp))
            HorizontalDivider(color = color.copy(alpha = 0.2f))
            Spacer(Modifier.height(6.dp))

            // Parse JSON outside composable calls; use result to drive UI
            val parsedLines = remember(report.payload) {
                runCatching {
                    val obj = kotlinx.serialization.json.Json
                        .parseToJsonElement(report.payload).jsonObject
                    (1..9).mapNotNull { n ->
                        val label: String = obj["label_$n"]?.jsonPrimitive?.content ?: return@mapNotNull null
                        val value: String = obj["line_$n"]?.jsonPrimitive?.content?.takeIf { it.isNotBlank() } ?: return@mapNotNull null
                        Triple(n, label, value)
                    }
                }.getOrNull()
            }

            if (parsedLines != null) {
                parsedLines.forEach { (n, label, value) ->
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(
                            "$n",
                            style      = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.Bold,
                            color      = color,
                            modifier   = Modifier.width(16.dp),
                        )
                        Text("$label: $value", style = MaterialTheme.typography.bodySmall)
                    }
                }
            } else {
                Text(
                    report.payload,
                    style      = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                )
            }
        }
    }
}
