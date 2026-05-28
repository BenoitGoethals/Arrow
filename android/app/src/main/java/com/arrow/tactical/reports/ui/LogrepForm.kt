package com.arrow.tactical.reports.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.arrow.tactical.auth.ProfileStore
import com.arrow.tactical.reports.ReportRepository
import kotlinx.coroutines.launch
import kotlinx.serialization.json.*
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

// ── Payload data structures ────────────────────────────────────────────────────

data class AmmoEntry(
    val type: String = "",
    val onHand: String = "0",
    val consumption: String = "0",
)

data class EqpEntry(
    val type: String = "",
    val auth: String = "0",
    val onHand: String = "0",
    val fmc: String = "0",
    val pmc: String = "0",
    val nmc: String = "0",
)

data class LogreqEntry(
    val prio: String = "1",
    val item: String = "",
    val qty: String = "",
    val eta: String = "",
)

private val SECTION_COLORS = listOf(
    Color(0xFF0EA5E9), // A – PERSTAT
    Color(0xFF22C55E), // B – Supply
    Color(0xFFF59E0B), // C – EQPSTAT
    Color(0xFFEF4444), // D – Maintenance
    Color(0xFFEC4899), // E – Medical
    Color(0xFF8B5CF6), // F – LOGREQ
    Color(0xFF64748B), // G – Assessment
)

// ── Main composable ────────────────────────────────────────────────────────────

@Composable
fun LogrepForm(
    repo: ReportRepository,
    profileStore: ProfileStore?,
    onSubmitted: () -> Unit,
) {
    val profile by (profileStore?.profile ?: kotlinx.coroutines.flow.flowOf(null))
        .collectAsState(initial = null)
    val scope = rememberCoroutineScope()
    var submitting by remember { mutableStateOf(false) }
    var statusMsg  by remember { mutableStateOf<String?>(null) }

    // ── Header ─────────────────────────────────────────────────────────────────
    val nowDtg = remember {
        DateTimeFormatter.ofPattern("ddHHmm'Z'MMMuu").withZone(ZoneOffset.UTC)
            .format(Instant.now()).uppercase()
    }
    var periodFrom  by remember { mutableStateOf("") }
    var periodTo    by remember { mutableStateOf("") }
    var serialNo    by remember { mutableStateOf("001") }
    var higherHq    by remember { mutableStateOf("") }

    // ── A – PERSTAT ────────────────────────────────────────────────────────────
    var authorized  by remember { mutableStateOf("") }
    var present     by remember { mutableStateOf("") }
    var kia         by remember { mutableStateOf("0") }
    var wiaEvac     by remember { mutableStateOf("0") }
    var wiaDuty     by remember { mutableStateOf("0") }
    var missing     by remember { mutableStateOf("0") }
    var sick        by remember { mutableStateOf("0") }

    // ── B – Supply ─────────────────────────────────────────────────────────────
    var dos            by remember { mutableStateOf("") }
    var rationsType    by remember { mutableStateOf("24h ration pack") }
    var waterLiters    by remember { mutableStateOf("") }
    var dieselOnHand   by remember { mutableStateOf("") }
    var dieselConsDay  by remember { mutableStateOf("") }
    var petrolOnHand   by remember { mutableStateOf("") }
    var petrolConsDay  by remember { mutableStateOf("") }
    var avgasOnHand    by remember { mutableStateOf("0") }
    val classV = remember {
        mutableStateListOf(
            AmmoEntry("5.56mm Ball"),
            AmmoEntry("7.62mm"),
            AmmoEntry("40mm HE"),
            AmmoEntry("AT4"),
            AmmoEntry("81mm HE"),
            AmmoEntry("Smoke"),
        )
    }
    var morphine        by remember { mutableStateOf("") }
    var tourniquets     by remember { mutableStateOf("") }
    var ivBags          by remember { mutableStateOf("") }
    var viii_shortfalls by remember { mutableStateOf("") }
    var ix_shortfalls   by remember { mutableStateOf("") }

    // ── C – EQPSTAT ───────────────────────────────────────────────────────────
    val eqpstat = remember { mutableStateListOf<EqpEntry>() }

    // ── D – Maintenance ───────────────────────────────────────────────────────
    var openWo     by remember { mutableStateOf("0") }
    var deadlines  by remember { mutableStateOf("") }
    var partsAwait by remember { mutableStateOf("") }

    // ── E – Medical ───────────────────────────────────────────────────────────
    var evacuations24h    by remember { mutableStateOf("0") }
    var medicOperational  by remember { mutableStateOf(true) }
    var suppliesCritical  by remember { mutableStateOf(false) }
    var medNote           by remember { mutableStateOf("") }

    // ── F – LOGREQ ────────────────────────────────────────────────────────────
    val logreq = remember { mutableStateListOf<LogreqEntry>() }

    // ── G – Assessment ────────────────────────────────────────────────────────
    var assessment by remember { mutableStateOf("GREEN") }
    var remarks    by remember { mutableStateOf("") }

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {

        // Header info
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("LOGREP", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                Text("DTG: $nowDtg  ·  Unit: ${profile?.callsign ?: "—"}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    LrField("Period from", periodFrom, { periodFrom = it }, Modifier.weight(1f))
                    LrField("Period to",   periodTo,   { periodTo   = it }, Modifier.weight(1f))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    LrField("Serial", serialNo, { serialNo = it }, Modifier.weight(1f))
                    LrField("Higher HQ", higherHq, { higherHq = it }, Modifier.weight(2f))
                }
            }
        }

        // A – PERSTAT
        LrSection("A — PERSTAT", SECTION_COLORS[0]) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                LrNum("AUTH",   authorized, { authorized = it }, Modifier.weight(1f))
                LrNum("PRESENT",present,    { present    = it }, Modifier.weight(1f))
                LrNum("SICK",   sick,       { sick        = it }, Modifier.weight(1f))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                LrNum("KIA",     kia,     { kia     = it }, Modifier.weight(1f))
                LrNum("WIA evac",wiaEvac, { wiaEvac = it }, Modifier.weight(1f))
                LrNum("WIA duty",wiaDuty, { wiaDuty = it }, Modifier.weight(1f))
                LrNum("MISSING", missing, { missing = it }, Modifier.weight(1f))
            }
        }

        // B – Supply
        LrSection("B — Supply", SECTION_COLORS[1]) {
            Text("Class I — Rations & Water", style = MaterialTheme.typography.labelMedium,
                color = SECTION_COLORS[1])
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                LrNum("DOS",   dos,        { dos        = it }, Modifier.weight(1f))
                LrNum("Water (L/day)", waterLiters, { waterLiters = it }, Modifier.weight(1f))
                LrField("Ration type", rationsType, { rationsType = it }, Modifier.weight(2f))
            }

            Spacer(Modifier.height(4.dp))
            Text("Class III — POL (Fuel)", style = MaterialTheme.typography.labelMedium,
                color = SECTION_COLORS[1])
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                LrNum("Diesel on hand (L)", dieselOnHand, { dieselOnHand = it }, Modifier.weight(1f))
                LrNum("Diesel cons/day (L)", dieselConsDay, { dieselConsDay = it }, Modifier.weight(1f))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                LrNum("Petrol on hand (L)", petrolOnHand, { petrolOnHand = it }, Modifier.weight(1f))
                LrNum("Petrol cons/day (L)", petrolConsDay, { petrolConsDay = it }, Modifier.weight(1f))
                LrNum("AvGas on hand (L)", avgasOnHand, { avgasOnHand = it }, Modifier.weight(1f))
            }

            Spacer(Modifier.height(4.dp))
            Text("Class V — Ammunition", style = MaterialTheme.typography.labelMedium,
                color = SECTION_COLORS[1])
            AmmoTable(classV)

            Spacer(Modifier.height(4.dp))
            Text("Class VIII — Medical Supplies", style = MaterialTheme.typography.labelMedium,
                color = SECTION_COLORS[1])
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                LrNum("Morphine auto-inj",  morphine,    { morphine    = it }, Modifier.weight(1f))
                LrNum("Tourniquets",         tourniquets, { tourniquets = it }, Modifier.weight(1f))
                LrNum("IV bags",             ivBags,      { ivBags      = it }, Modifier.weight(1f))
            }
            LrText("Shortfalls", viii_shortfalls, { viii_shortfalls = it })

            Spacer(Modifier.height(4.dp))
            Text("Class IX — Spare Parts", style = MaterialTheme.typography.labelMedium,
                color = SECTION_COLORS[1])
            LrText("Critical shortfalls", ix_shortfalls, { ix_shortfalls = it })
        }

        // C – EQPSTAT
        LrSection("C — EQPSTAT", SECTION_COLORS[2]) {
            EqpTable(eqpstat)
        }

        // D – Maintenance
        LrSection("D — Maintenance", SECTION_COLORS[3]) {
            LrNum("Open work orders", openWo, { openWo = it })
            LrText("Deadline equipment", deadlines, { deadlines = it })
            LrText("Parts awaiting",     partsAwait, { partsAwait = it })
        }

        // E – Medical summary
        LrSection("E — Medical", SECTION_COLORS[4]) {
            LrNum("Evacuations (24h)", evacuations24h, { evacuations24h = it })
            LrCheckRow("Medic operational", medicOperational, { medicOperational = it })
            LrCheckRow("Supplies critical", suppliesCritical, { suppliesCritical = it })
            LrText("Note", medNote, { medNote = it })
        }

        // F – LOGREQ
        LrSection("F — LOGREQ", SECTION_COLORS[5]) {
            LogreqTable(logreq)
        }

        // G – Assessment
        LrSection("G — Assessment", SECTION_COLORS[6]) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("GREEN", "AMBER", "RED").forEach { s ->
                    val col = when (s) {
                        "GREEN" -> Color(0xFF22C55E)
                        "AMBER" -> Color(0xFFF59E0B)
                        else    -> Color(0xFFEF4444)
                    }
                    val selected = assessment == s
                    FilterChip(
                        selected = selected,
                        onClick  = { assessment = s },
                        label    = { Text(s, fontWeight = FontWeight.Bold) },
                        colors   = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = col.copy(alpha = 0.18f),
                            selectedLabelColor     = col,
                        ),
                    )
                }
            }
            LrText("Commander's remarks", remarks, { remarks = it })
        }

        // ── Submit ─────────────────────────────────────────────────────────────
        Button(
            enabled  = !submitting,
            modifier = Modifier.fillMaxWidth(),
            onClick  = {
                submitting = true; statusMsg = null
                val payload = buildLogrepPayload(
                    callsign       = profile?.callsign ?: "",
                    dtg            = nowDtg,
                    periodFrom     = periodFrom,
                    periodTo       = periodTo,
                    serialNo       = serialNo,
                    higherHq       = higherHq,
                    authorized     = authorized,
                    present        = present,
                    kia            = kia,
                    wiaEvac        = wiaEvac,
                    wiaDuty        = wiaDuty,
                    missing        = missing,
                    sick           = sick,
                    dos            = dos,
                    rationsType    = rationsType,
                    waterLiters    = waterLiters,
                    dieselOnHand   = dieselOnHand,
                    dieselConsDay  = dieselConsDay,
                    petrolOnHand   = petrolOnHand,
                    petrolConsDay  = petrolConsDay,
                    avgasOnHand    = avgasOnHand,
                    classV         = classV,
                    morphine       = morphine,
                    tourniquets    = tourniquets,
                    ivBags         = ivBags,
                    viiiShortfalls = viii_shortfalls,
                    ixShortfalls   = ix_shortfalls,
                    eqpstat        = eqpstat,
                    openWo         = openWo,
                    deadlines      = deadlines,
                    partsAwait     = partsAwait,
                    evacuations24h = evacuations24h,
                    medicOp        = medicOperational,
                    supCritical    = suppliesCritical,
                    medNote        = medNote,
                    logreq         = logreq,
                    assessment     = assessment,
                    remarks        = remarks,
                )
                scope.launch {
                    repo.submit("LOGREP", payload)
                        .onSuccess { statusMsg = "✓ LOGREP submitted"; onSubmitted() }
                        .onFailure { statusMsg = "✗ ${it.message}" }
                    submitting = false
                }
            },
        ) {
            Text(if (submitting) "Submitting…" else "Submit LOGREP")
        }

        statusMsg?.let {
            Text(
                it,
                color = if (it.startsWith("✗")) MaterialTheme.colorScheme.error
                        else Color(0xFF22C55E),
                style = MaterialTheme.typography.bodySmall,
            )
        }

        Spacer(Modifier.height(16.dp))
    }
}

// ── Sub-composables ────────────────────────────────────────────────────────────

@Composable
private fun LrSection(
    title: String,
    color: Color,
    content: @Composable ColumnScope.() -> Unit,
) {
    var expanded by remember { mutableStateOf(true) }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp)) {
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    Modifier
                        .size(8.dp)
                        .background(color, RoundedCornerShape(2.dp))
                )
                Spacer(Modifier.width(8.dp))
                Text(title,
                    style      = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    color      = color,
                    modifier   = Modifier.weight(1f))
                IconButton(onClick = { expanded = !expanded }, modifier = Modifier.size(24.dp)) {
                    Icon(
                        if (expanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                        tint = color,
                    )
                }
            }
            if (expanded) {
                Spacer(Modifier.height(8.dp))
                Column(verticalArrangement = Arrangement.spacedBy(6.dp), content = content)
            }
        }
    }
}

@Composable
private fun LrField(
    label: String,
    value: String,
    onValue: (String) -> Unit,
    modifier: Modifier = Modifier.fillMaxWidth(),
) {
    OutlinedTextField(
        value         = value,
        onValueChange = onValue,
        label         = { Text(label, fontSize = 10.sp) },
        modifier      = modifier,
        singleLine    = true,
        textStyle     = MaterialTheme.typography.bodySmall,
    )
}

@Composable
private fun LrNum(
    label: String,
    value: String,
    onValue: (String) -> Unit,
    modifier: Modifier = Modifier.fillMaxWidth(),
) {
    OutlinedTextField(
        value         = value,
        onValueChange = onValue,
        label         = { Text(label, fontSize = 10.sp) },
        modifier      = modifier,
        singleLine    = true,
        textStyle     = MaterialTheme.typography.bodySmall,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
    )
}

@Composable
private fun LrText(
    label: String,
    value: String,
    onValue: (String) -> Unit,
) {
    OutlinedTextField(
        value         = value,
        onValueChange = onValue,
        label         = { Text(label, fontSize = 10.sp) },
        modifier      = Modifier.fillMaxWidth(),
        minLines      = 2,
        maxLines      = 4,
        textStyle     = MaterialTheme.typography.bodySmall,
    )
}

@Composable
private fun LrCheckRow(label: String, checked: Boolean, onChecked: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Checkbox(checked = checked, onCheckedChange = onChecked)
        Text(label, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun ColumnScope.AmmoTable(list: SnapshotStateList<AmmoEntry>) {
    Row(
        Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(4.dp))
            .padding(horizontal = 8.dp, vertical = 4.dp),
    ) {
        Text("Type",     Modifier.weight(2f), style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
        Text("On hand",  Modifier.weight(1f), style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
        Text("Cons/24h", Modifier.weight(1f), style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
        Spacer(Modifier.size(32.dp))
    }
    list.forEachIndexed { i, entry ->
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            OutlinedTextField(
                value = entry.type, onValueChange = { list[i] = entry.copy(type = it) },
                modifier = Modifier.weight(2f), singleLine = true,
                textStyle = MaterialTheme.typography.bodySmall,
            )
            OutlinedTextField(
                value = entry.onHand, onValueChange = { list[i] = entry.copy(onHand = it) },
                modifier = Modifier.weight(1f), singleLine = true,
                textStyle = MaterialTheme.typography.bodySmall,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            )
            OutlinedTextField(
                value = entry.consumption, onValueChange = { list[i] = entry.copy(consumption = it) },
                modifier = Modifier.weight(1f), singleLine = true,
                textStyle = MaterialTheme.typography.bodySmall,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            )
            IconButton(onClick = { list.removeAt(i) }, modifier = Modifier.size(32.dp)) {
                Icon(Icons.Filled.Delete, null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.error)
            }
        }
    }
    TextButton(onClick = { list.add(AmmoEntry()) }) {
        Icon(Icons.Filled.Add, null, Modifier.size(16.dp))
        Text("Add ammo type", fontSize = 11.sp)
    }
}

@Composable
private fun ColumnScope.EqpTable(list: SnapshotStateList<EqpEntry>) {
    if (list.isNotEmpty()) {
        Row(
            Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(4.dp))
                .padding(horizontal = 4.dp, vertical = 4.dp),
        ) {
            Text("Equipment",Modifier.weight(3f), style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
            listOf("AUTH","OH","FMC","PMC","NMC").forEach {
                Text(it, Modifier.weight(1f), style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
            }
            Spacer(Modifier.size(32.dp))
        }
    }
    list.forEachIndexed { i, e ->
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            OutlinedTextField(
                value = e.type, onValueChange = { list[i] = e.copy(type = it) },
                modifier = Modifier.weight(3f), singleLine = true,
                label = { Text("Type", fontSize = 9.sp) },
                textStyle = MaterialTheme.typography.bodySmall,
            )
            listOf(
                e.auth  to { v: String -> list[i] = e.copy(auth  = v) },
                e.onHand to { v: String -> list[i] = e.copy(onHand = v) },
                e.fmc   to { v: String -> list[i] = e.copy(fmc   = v) },
                e.pmc   to { v: String -> list[i] = e.copy(pmc   = v) },
                e.nmc   to { v: String -> list[i] = e.copy(nmc   = v) },
            ).forEachIndexed { j, (v, upd) ->
                OutlinedTextField(
                    value = v, onValueChange = upd,
                    modifier = Modifier.weight(1f), singleLine = true,
                    textStyle = MaterialTheme.typography.bodySmall.copy(fontSize = 11.sp),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                )
            }
            IconButton(onClick = { list.removeAt(i) }, modifier = Modifier.size(32.dp)) {
                Icon(Icons.Filled.Delete, null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.error)
            }
        }
    }
    TextButton(onClick = { list.add(EqpEntry()) }) {
        Icon(Icons.Filled.Add, null, Modifier.size(16.dp))
        Text("Add equipment", fontSize = 11.sp)
    }
}

@Composable
private fun ColumnScope.LogreqTable(list: SnapshotStateList<LogreqEntry>) {
    list.forEachIndexed { i, e ->
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
        ) {
            Column(Modifier.padding(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Text("Prio", style = MaterialTheme.typography.labelSmall)
                    OutlinedTextField(
                        value = e.prio, onValueChange = { list[i] = e.copy(prio = it) },
                        modifier = Modifier.width(60.dp), singleLine = true,
                        textStyle = MaterialTheme.typography.bodySmall,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    )
                    Spacer(Modifier.weight(1f))
                    IconButton(onClick = { list.removeAt(i) }, modifier = Modifier.size(32.dp)) {
                        Icon(Icons.Filled.Delete, null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.error)
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    OutlinedTextField(
                        value = e.item, onValueChange = { list[i] = e.copy(item = it) },
                        label = { Text("Item", fontSize = 10.sp) },
                        modifier = Modifier.weight(2f), singleLine = true,
                        textStyle = MaterialTheme.typography.bodySmall,
                    )
                    OutlinedTextField(
                        value = e.qty, onValueChange = { list[i] = e.copy(qty = it) },
                        label = { Text("Quantity", fontSize = 10.sp) },
                        modifier = Modifier.weight(1f), singleLine = true,
                        textStyle = MaterialTheme.typography.bodySmall,
                    )
                    OutlinedTextField(
                        value = e.eta, onValueChange = { list[i] = e.copy(eta = it) },
                        label = { Text("Required by", fontSize = 10.sp) },
                        modifier = Modifier.weight(1f), singleLine = true,
                        textStyle = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }
    }
    TextButton(onClick = { list.add(LogreqEntry(prio = "${list.size + 1}")) },
        modifier = Modifier.fillMaxWidth()) {
        Icon(Icons.Filled.Add, null, Modifier.size(16.dp))
        Text("Add request", fontSize = 11.sp)
    }
}

// ── Payload builder ────────────────────────────────────────────────────────────

private fun buildLogrepPayload(
    callsign: String, dtg: String, periodFrom: String, periodTo: String,
    serialNo: String, higherHq: String,
    authorized: String, present: String, kia: String, wiaEvac: String,
    wiaDuty: String, missing: String, sick: String,
    dos: String, rationsType: String, waterLiters: String,
    dieselOnHand: String, dieselConsDay: String,
    petrolOnHand: String, petrolConsDay: String, avgasOnHand: String,
    classV: List<AmmoEntry>,
    morphine: String, tourniquets: String, ivBags: String,
    viiiShortfalls: String, ixShortfalls: String,
    eqpstat: List<EqpEntry>,
    openWo: String, deadlines: String, partsAwait: String,
    evacuations24h: String, medicOp: Boolean, supCritical: Boolean, medNote: String,
    logreq: List<LogreqEntry>,
    assessment: String, remarks: String,
): JsonObject = buildJsonObject {
    put("callsign",    callsign)
    put("dtg",         dtg)
    put("period_from", periodFrom)
    put("period_to",   periodTo)
    put("serial",      serialNo)
    put("higher_hq",   higherHq)

    putJsonObject("section_a") {
        put("authorised",    authorized.toIntOrNull() ?: 0)
        put("present",       present.toIntOrNull()    ?: 0)
        put("kia",           kia.toIntOrNull()        ?: 0)
        put("wia_evacuated", wiaEvac.toIntOrNull()    ?: 0)
        put("wia_duty",      wiaDuty.toIntOrNull()    ?: 0)
        put("missing",       missing.toIntOrNull()    ?: 0)
        put("sick",          sick.toIntOrNull()       ?: 0)
    }

    putJsonObject("section_b") {
        putJsonObject("class_i") {
            put("dos",          dos.toDoubleOrNull() ?: 0.0)
            put("ration_type",  rationsType)
            put("water_litres", waterLiters.toDoubleOrNull() ?: 0.0)
        }
        putJsonObject("class_iii") {
            put("diesel_litres", dieselOnHand.toDoubleOrNull()  ?: 0.0)
            put("petrol_litres", petrolOnHand.toDoubleOrNull()  ?: 0.0)
            put("avgas_litres",  avgasOnHand.toDoubleOrNull()   ?: 0.0)
        }
        putJsonArray("class_v") {
            classV.forEach { a ->
                addJsonObject {
                    put("type",        a.type)
                    put("on_hand",     a.onHand.toIntOrNull()     ?: 0)
                    put("consumption", a.consumption.toIntOrNull() ?: 0)
                }
            }
        }
        putJsonObject("class_viii") {
            put("morphine",     morphine.toIntOrNull()     ?: 0)
            put("tourniquets",  tourniquets.toIntOrNull()  ?: 0)
            put("iv_bags",      ivBags.toIntOrNull()       ?: 0)
            put("shortfalls",   viiiShortfalls)
        }
        put("class_ix_shortfalls", ixShortfalls)
    }

    putJsonArray("section_c") {
        eqpstat.forEach { e ->
            addJsonObject {
                put("type",    e.type)
                put("auth",    e.auth.toIntOrNull()   ?: 0)
                put("on_hand", e.onHand.toIntOrNull() ?: 0)
                put("fmc",     e.fmc.toIntOrNull()    ?: 0)
                put("pmc",     e.pmc.toIntOrNull()    ?: 0)
                put("nmc",     e.nmc.toIntOrNull()    ?: 0)
            }
        }
    }

    putJsonObject("section_d") {
        put("open_work_orders",   openWo.toIntOrNull() ?: 0)
        put("deadline_equipment", deadlines)
        put("parts_awaiting",     partsAwait)
    }

    putJsonObject("section_e") {
        put("evacuations_24h",   evacuations24h.toIntOrNull() ?: 0)
        put("medic_operational", medicOp)
        put("supplies_critical", supCritical)
        put("note",              medNote)
    }

    putJsonArray("section_f") {
        logreq.forEach { r ->
            addJsonObject {
                put("priority", r.prio.toIntOrNull() ?: 0)
                put("item",     r.item)
                put("quantity", r.qty)
                put("eta",      r.eta)
            }
        }
    }

    putJsonObject("section_g") {
        put("assessment", assessment)
        put("remarks",    remarks)
    }
}
