package com.arrow.tactical.map.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CloudDownload
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Done
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
import com.arrow.tactical.map.MapSourceDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Operator-facing manager for offline base maps.
 *
 * Shows every downloadable source the backend exposes (`/map/sources` with
 * `downloadable=true`) and lets the user download the raw `.mbtiles` to the
 * device or delete a previously-downloaded copy. Once a source has a local
 * file, [MapScreen] renders tiles directly from it via OSMdroid's MBTiles
 * archive provider — no network needed.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OfflineMapsScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var sources by remember { mutableStateOf<List<MapSourceDto>>(emptyList()) }
    var localNames by remember { mutableStateOf<Set<String>>(emptySet()) }
    var downloadingName by remember { mutableStateOf<String?>(null) }
    var progress by remember { mutableStateOf(0f) }
    var progressLabel by remember { mutableStateOf("") }
    var loadError by remember { mutableStateOf<String?>(null) }

    suspend fun refresh() {
        sources = container.mapSourceRepository.list().filter { it.downloadable }
        localNames = container.mapSourceRepository.listLocal().toSet()
    }

    LaunchedEffect(Unit) {
        runCatching { refresh() }
            .onFailure { loadError = it.message }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Offline maps") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier.padding(padding).fillMaxSize().padding(horizontal = 12.dp),
        ) {
            Text(
                text  = "Downloaded MBTiles are stored on this device and render the map " +
                        "fully offline. Switch between sources from the Layers button on " +
                        "the tactical map.",
                style = MaterialTheme.typography.bodySmall,
                color = Color(0xFF94A3B8),
                modifier = Modifier.padding(vertical = 8.dp),
            )

            if (loadError != null) {
                Text(
                    text  = "Could not load sources: $loadError",
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                )
            }

            if (sources.isEmpty() && loadError == null) {
                Text(
                    text  = "No downloadable maps on the server. Ask an admin to upload an .mbtiles file.",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color(0xFF64748B),
                    modifier = Modifier.padding(top = 8.dp),
                )
            }

            LazyColumn(
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxSize().padding(top = 8.dp),
            ) {
                items(sources, key = { it.name }) { src ->
                    val isLocal = src.name in localNames
                    val isBusy  = downloadingName == src.name
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(Color(0xFF161B25), RoundedCornerShape(6.dp))
                            .border(1.dp, Color(0xFF2A3142), RoundedCornerShape(6.dp))
                            .padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = src.title,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.SemiBold,
                                color = Color(0xFFE2E8F0),
                            )
                            Text(
                                text  = "${src.format.uppercase()}  ·  z ${src.min_zoom}–${src.max_zoom}  ·  " +
                                        humanSize(src.size_bytes ?: 0L),
                                style = MaterialTheme.typography.bodySmall,
                                color = Color(0xFF64748B),
                            )
                            if (isBusy) {
                                LinearProgressIndicator(
                                    progress = { progress },
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(top = 6.dp)
                                        .height(4.dp),
                                )
                                Text(
                                    text  = progressLabel,
                                    style = MaterialTheme.typography.labelSmall.copy(fontSize = 11.sp),
                                    color = Color(0xFF94A3B8),
                                )
                            } else if (isLocal) {
                                Row(verticalAlignment = Alignment.CenterVertically,
                                    modifier = Modifier.padding(top = 4.dp)) {
                                    Icon(
                                        Icons.Filled.Done, contentDescription = null,
                                        tint = Color(0xFF34D399),
                                        modifier = Modifier.size(14.dp),
                                    )
                                    Text(
                                        text  = "  Downloaded — available offline",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = Color(0xFF34D399),
                                    )
                                }
                            }
                        }

                        Spacer(Modifier.width(8.dp))

                        if (isLocal) {
                            IconButton(
                                onClick = {
                                    container.mapSourceRepository.deleteLocal(src.name)
                                    localNames = localNames - src.name
                                },
                                enabled = !isBusy,
                            ) {
                                Icon(Icons.Filled.Delete, contentDescription = "Delete local copy",
                                     tint = Color(0xFFEF4444))
                            }
                        } else {
                            FilledIconButton(
                                onClick = {
                                    scope.launch {
                                        downloadingName = src.name
                                        progress = 0f
                                        progressLabel = "Starting…"
                                        val result = container.mapSourceRepository.download(src.name) { read, total ->
                                            if (total > 0) progress = (read.toFloat() / total).coerceIn(0f, 1f)
                                            progressLabel = "${humanSize(read)} / ${if (total > 0) humanSize(total) else "?"}"
                                        }
                                        downloadingName = null
                                        result.onSuccess {
                                            // Reload the local-set so the UI flips to Downloaded.
                                            withContext(Dispatchers.IO) {
                                                localNames = container.mapSourceRepository.listLocal().toSet()
                                            }
                                        }.onFailure {
                                            progressLabel = "Failed: ${it.message}"
                                        }
                                    }
                                },
                                enabled = !isBusy,
                            ) {
                                Icon(Icons.Filled.CloudDownload, contentDescription = "Download")
                            }
                        }
                    }
                }
            }
        }
    }
}

private fun humanSize(bytes: Long): String {
    if (bytes <= 0) return "0 B"
    val units = arrayOf("B", "KB", "MB", "GB", "TB")
    var n = bytes.toDouble()
    var i = 0
    while (n >= 1024 && i < units.size - 1) { n /= 1024.0; i++ }
    return if (n < 10) "%.1f %s".format(n, units[i]) else "%.0f %s".format(n, units[i])
}
