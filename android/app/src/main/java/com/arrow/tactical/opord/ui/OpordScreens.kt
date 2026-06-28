package com.arrow.tactical.opord.ui

import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.network.OpordDto
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

@Composable
fun OpordListScreen(container: AppContainer, onOpen: (Int) -> Unit) {
    val scope = rememberCoroutineScope()
    var opords by remember { mutableStateOf<List<OpordDto>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    fun load() {
        scope.launch {
            loading = true
            container.opordRepository.list()
                .onSuccess { opords = it; error = null }
                .onFailure { error = it.message }
            loading = false
        }
    }

    LaunchedEffect(Unit) { load() }

    // Live refresh on opord WS events
    LaunchedEffect(Unit) {
        container.wsClient.events().collect { evt ->
            val ch = (evt["channel"] as? JsonPrimitive)?.contentOrNull
            if (ch == "opord") load()
        }
    }

    Column(Modifier.fillMaxSize().padding(12.dp)) {
        Text("OPORDs", fontSize = 18.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        when {
            loading -> CircularProgressIndicator()
            error != null -> Text("Error: $error", color = Color.Red)
            opords.isEmpty() -> Text("No OPORDs available.", color = Color.Gray)
            else -> LazyColumn {
                items(opords, key = { it.id }) { o ->
                    Card(
                        Modifier.fillMaxWidth().padding(vertical = 4.dp).clickable { onOpen(o.id) },
                    ) {
                        Column(Modifier.padding(12.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(o.title, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                                StatusPill(o.status)
                            }
                            if (o.opordNumber.isNotBlank() || o.dtg.isNotBlank()) {
                                Text(
                                    "${o.opordNumber}  ${o.dtg}".trim(),
                                    fontFamily = FontFamily.Monospace, fontSize = 12.sp, color = Color.Gray,
                                )
                            }
                            if (o.mission.isNotBlank()) {
                                Spacer(Modifier.height(4.dp))
                                Text(o.mission, fontSize = 13.sp, maxLines = 2)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun StatusPill(status: String) {
    val (bg, fg) = if (status == "PUBLISHED") Color(0xFF064E3B) to Color(0xFF34D399)
                   else Color(0xFF1E2736) to Color(0xFF94A3B8)
    Box(Modifier.background(bg, MaterialTheme.shapes.small).padding(horizontal = 6.dp, vertical = 2.dp)) {
        Text(status, color = fg, fontSize = 10.sp, fontWeight = FontWeight.Bold)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OpordDetailScreen(container: AppContainer, opordId: Int, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    var opord by remember { mutableStateOf<OpordDto?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    // SAF: export a frozen attached layer to a file the recipient can re-import.
    var pendingAttachExport by remember { mutableStateOf<Int?>(null) }
    val attachExportLauncher = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.CreateDocument("application/json")
    ) { uri ->
        val attachId = pendingAttachExport
        pendingAttachExport = null
        if (uri != null && attachId != null) scope.launch {
            container.opordRepository.exportAttachment(opordId, attachId).onSuccess { jsonText ->
                runCatching {
                    context.contentResolver.openOutputStream(uri)?.use { it.write(jsonText.toByteArray()) }
                }
            }
        }
    }

    LaunchedEffect(opordId) {
        container.opordRepository.get(opordId)
            .onSuccess { opord = it; error = null }
            .onFailure { error = it.message }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(opord?.title ?: "OPORD") },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.Default.ArrowBack, contentDescription = "Back") }
                },
                actions = {
                    IconButton(onClick = {
                        scope.launch {
                            runCatching { container.opordRepository.downloadPdf(context, opordId) }
                                .onSuccess { uri ->
                                    val intent = Intent(Intent.ACTION_VIEW).apply {
                                        setDataAndType(uri, "application/pdf")
                                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                    }
                                    runCatching { context.startActivity(intent) }
                                }
                        }
                    }) { Icon(Icons.Default.PictureAsPdf, contentDescription = "Open PDF") }
                },
            )
        },
    ) { padding ->
        if (error != null) {
            Box(Modifier.padding(padding).padding(16.dp)) { Text("Error: $error", color = Color.Red) }
            return@Scaffold
        }
        val o = opord ?: run {
            Box(Modifier.padding(padding).padding(16.dp), Alignment.Center) { CircularProgressIndicator() }
            return@Scaffold
        }
        Column(
            Modifier.padding(padding).padding(12.dp).verticalScroll(rememberScrollState()),
        ) {
            Header(o)
            Section("1. Situation", o.situation)
            ParagraphTextSection("2. Mission", o.mission)
            Section("3. Execution", o.execution)
            Section("4. Sustainment", o.sustainment)
            Section("5. Command and Signal", o.commandSignal)
            if (o.mapSnapshots.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                Text("Map snapshots", fontWeight = FontWeight.Bold, fontSize = 14.sp)
                o.mapSnapshots.forEach { s ->
                    Spacer(Modifier.height(6.dp))
                    Card { Column(Modifier.padding(8.dp)) {
                        Text(s.label.ifBlank { "Snapshot ${s.id}" }, fontWeight = FontWeight.SemiBold)
                        AsyncImage(
                            model = ImageRequest.Builder(context)
                                .data("${runBlockingBaseUrl(container)}/photos/${s.photoId}")
                                .build(),
                            imageLoader = container.imageLoader,
                            contentDescription = s.label,
                            modifier = Modifier.fillMaxWidth().height(200.dp),
                        )
                        if (s.annotations.isNotBlank()) {
                            Spacer(Modifier.height(4.dp))
                            Text(s.annotations, fontSize = 12.sp)
                        }
                    } }
                }
            }
            if (o.attachedLayers.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                Text("Attached layers", fontWeight = FontWeight.Bold, fontSize = 14.sp)
                o.attachedLayers.forEach { a ->
                    Spacer(Modifier.height(6.dp))
                    Card { Row(
                        Modifier.padding(start = 10.dp, end = 4.dp, top = 6.dp, bottom = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(
                                "${a.kind}  ·  ${a.name}",
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 13.sp,
                            )
                            Text(
                                attachmentDetail(a),
                                color = Color(0xFF94A3B8),
                                fontSize = 11.sp,
                            )
                        }
                        IconButton(onClick = {
                            pendingAttachExport = a.id
                            attachExportLauncher.launch(
                                a.name.replace(Regex("[^A-Za-z0-9-_]"), "_") + ".layer.json"
                            )
                        }) {
                            Icon(Icons.Default.Download, contentDescription = "Export")
                        }
                    } }
                }
            }
        }
    }
}

/** Human-readable count line for an OPORD layer attachment, from its frozen envelope payload. */
private fun attachmentDetail(a: com.arrow.tactical.network.AttachedLayerDto): String {
    val payload = a.envelope?.get("payload") as? JsonObject ?: return ""
    fun arrLen(key: String) = (payload[key] as? kotlinx.serialization.json.JsonArray)?.size ?: 0
    return when (a.kind) {
        "OVERLAY" -> "${arrLen("objects")} object(s)"
        "KML" -> {
            val n = (payload["feature_count"] as? kotlinx.serialization.json.JsonPrimitive)?.content ?: "0"
            "$n feature(s)"
        }
        "OSINT" -> "${arrLen("nodes")} node(s), ${arrLen("links")} link(s)"
        else -> ""
    }
}

@Composable
private fun Header(o: OpordDto) {
    Text(o.classification.ifBlank { "UNCLASSIFIED" }, color = Color(0xFFB91C1C), fontWeight = FontWeight.Bold)
    Text("OPORD ${o.opordNumber} — ${o.title}".trim(), fontSize = 18.sp, fontWeight = FontWeight.Bold)
    val meta = listOfNotNull(
        o.dtg.takeIf { it.isNotBlank() }?.let { "DTG: $it" },
        "TZ: ${o.timeZone}",
        "Status: ${o.status}",
    ).joinToString(" · ")
    Text(meta, fontSize = 12.sp, color = Color.Gray)
    if (o.references.isNotBlank()) {
        Spacer(Modifier.height(4.dp))
        SubLabel("References"); Text(o.references, fontSize = 13.sp)
    }
    if (o.taskOrganization.isNotBlank()) {
        Spacer(Modifier.height(4.dp))
        SubLabel("Task organization"); Text(o.taskOrganization, fontSize = 13.sp)
    }
    Spacer(Modifier.height(8.dp))
}

@Composable
private fun Section(title: String, json: JsonObject) {
    if (json.isEmpty()) return
    Spacer(Modifier.height(10.dp))
    Text(title, fontWeight = FontWeight.Bold, fontSize = 15.sp, color = Color(0xFF93C5FD))
    Spacer(Modifier.height(4.dp))
    json.forEach { (k, v) ->
        val text = v.asPlainString()
        if (text.isNotBlank()) {
            SubLabel(k.replace('_', ' ').replaceFirstChar { it.titlecase() })
            Text(text, fontSize = 13.sp)
            Spacer(Modifier.height(4.dp))
        }
    }
}

@Composable
private fun ParagraphTextSection(title: String, body: String) {
    Spacer(Modifier.height(10.dp))
    Text(title, fontWeight = FontWeight.Bold, fontSize = 15.sp, color = Color(0xFF93C5FD))
    Spacer(Modifier.height(2.dp))
    Text(body.ifBlank { "—" }, fontSize = 13.sp)
}

@Composable
private fun SubLabel(t: String) {
    Text(t, fontSize = 11.sp, color = Color.Gray, fontWeight = FontWeight.SemiBold)
}

private fun JsonElement.asPlainString(): String = when (this) {
    is JsonPrimitive -> contentOrNull ?: ""
    else -> toString()
}

private fun runBlockingBaseUrl(container: AppContainer): String =
    kotlinx.coroutines.runBlocking { container.settingsRepository.currentServerUrl() }
