package com.arrow.tactical.objectives.ui

import android.content.pm.ActivityInfo
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.network.TacticalObjectDto
import kotlinx.coroutines.delay

private data class ParsedObjective(
    val id: Int,
    val title: String,
    val description: String,
    val mgrs: String,
    val lat: Double,
    val lon: Double,
    val photoId: Int?,
    val raw: TacticalObjectDto,
)

private fun parse(o: TacticalObjectDto): ParsedObjective {
    val nl     = o.notes.indexOf('\n')
    val title  = (if (nl >= 0) o.notes.substring(0, nl) else o.notes).ifBlank { "Objective" }
    val rest   = if (nl >= 0) o.notes.substring(nl + 1) else ""
    val mgrs   = rest.lineSequence().firstOrNull { it.startsWith("MGRS:") }
                     ?.removePrefix("MGRS:")?.trim().orEmpty()
    val desc   = rest.lineSequence().filterNot { it.startsWith("MGRS:") }
                     .joinToString("\n").trim()
    return ParsedObjective(o.id, title, desc, mgrs, o.latitude, o.longitude, o.photoId, o)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ObjectivesScreen(container: AppContainer) {
    val context  = LocalContext.current
    val activity = context as? android.app.Activity

    // Force portrait on this screen; restore landscape on dispose
    DisposableEffect(Unit) {
        activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        onDispose {
            activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        }
    }

    var objectives by remember { mutableStateOf<List<ParsedObjective>>(emptyList()) }
    var error      by remember { mutableStateOf<String?>(null) }
    var selected   by remember { mutableStateOf<ParsedObjective?>(null) }
    var baseUrl    by remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        baseUrl = container.settingsRepository.currentServerUrl()
    }

    // Resilient polling — refresh every 5 s, plus push updates over WebSocket
    LaunchedEffect(Unit) {
        while (true) {
            container.tacticalRepository.listObjects()
                .onSuccess { list ->
                    objectives = list.filter { it.type == "OBJECTIVE" }
                                     .sortedByDescending { it.id }
                                     .map(::parse)
                    error = if (list.isEmpty()) null else null
                }
                .onFailure { error = it.message?.take(80) }
            delay(5_000)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title  = { Text("🚩 Objectives", fontWeight = FontWeight.Bold) },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color(0xFF0D1117),
                    titleContentColor = Color(0xFF22C55E),
                ),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .background(Color(0xFF0D1117)),
        ) {
            if (error != null) {
                Text(
                    "⚠ $error",
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(16.dp),
                )
            }
            if (objectives.isEmpty() && error == null) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(
                        "No objectives yet. Mark one from the web map's radial menu.",
                        color = Color(0xFF64748B),
                        modifier = Modifier.padding(32.dp),
                    )
                }
            } else {
                LazyColumn(
                    contentPadding      = PaddingValues(12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(objectives, key = { it.id }) { obj ->
                        ObjectiveCard(obj, baseUrl, container) { selected = obj }
                    }
                }
            }
        }
    }

    selected?.let { obj ->
        ObjectiveDetailDialog(
            obj         = obj,
            baseUrl     = baseUrl,
            imageLoader = container.imageLoader,
            onDismiss   = { selected = null },
        )
    }
}

@Composable
private fun ObjectiveCard(
    obj: ParsedObjective,
    baseUrl: String,
    container: AppContainer,
    onClick: () -> Unit,
) {
    Surface(
        modifier  = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .clickable(onClick = onClick),
        color     = Color(0xFF161B25),
        tonalElevation = 0.dp,
    ) {
        Row(
            modifier = Modifier
                .background(Color(0xFF161B25))
                .padding(12.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            // Green left bar
            Box(
                modifier = Modifier
                    .width(3.dp)
                    .fillMaxHeight()
                    .heightIn(min = 60.dp)
                    .background(Color(0xFF16A34A), RoundedCornerShape(2.dp)),
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    "🚩 ${obj.title}",
                    color      = Color(0xFFE2E8F0),
                    fontWeight = FontWeight.SemiBold,
                    fontSize   = 14.sp,
                )
                if (obj.description.isNotBlank()) {
                    Text(
                        obj.description,
                        color    = Color(0xFF94A3B8),
                        fontSize = 12.sp,
                        maxLines = 2,
                    )
                }
                Spacer(Modifier.height(4.dp))
                Text(
                    "#${obj.id}  ·  ${if (obj.mgrs.isNotBlank()) obj.mgrs
                                       else "%.4f, %.4f".format(obj.lat, obj.lon)}",
                    color    = Color(0xFF475569),
                    fontSize = 10.sp,
                )
            }
            if (obj.photoId != null && baseUrl.isNotBlank()) {
                AsyncImage(
                    model              = "$baseUrl/photos/${obj.photoId}",
                    contentDescription = "Objective photo",
                    imageLoader        = container.imageLoader,
                    contentScale       = ContentScale.Crop,
                    modifier           = Modifier
                        .size(64.dp)
                        .clip(RoundedCornerShape(4.dp)),
                )
            }
        }
    }
}

@Composable
private fun ObjectiveDetailDialog(
    obj: ParsedObjective,
    baseUrl: String,
    imageLoader: coil.ImageLoader,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton    = { TextButton(onClick = onDismiss) { Text("Close") } },
        title            = { Text("🚩 ${obj.title}", fontWeight = FontWeight.Bold) },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    "#${obj.id}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (obj.mgrs.isNotBlank()) {
                    Text("MGRS: ${obj.mgrs}",
                         style = MaterialTheme.typography.labelMedium)
                }
                Text(
                    "%.5f, %.5f".format(obj.lat, obj.lon),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (obj.description.isNotBlank()) {
                    Text(obj.description, style = MaterialTheme.typography.bodyMedium)
                } else {
                    Text("(no description)",
                         style = MaterialTheme.typography.bodySmall,
                         color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (obj.photoId != null && baseUrl.isNotBlank()) {
                    AsyncImage(
                        model              = "$baseUrl/photos/${obj.photoId}",
                        contentDescription = "Objective photo",
                        imageLoader        = imageLoader,
                        contentScale       = ContentScale.Fit,
                        modifier           = Modifier
                            .fillMaxWidth()
                            .heightIn(max = 320.dp)
                            .clip(RoundedCornerShape(6.dp)),
                    )
                }
            }
        },
    )
}
