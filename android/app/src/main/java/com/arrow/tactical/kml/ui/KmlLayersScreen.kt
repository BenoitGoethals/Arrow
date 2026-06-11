package com.arrow.tactical.kml.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
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
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.kml.KmlLayerDto
import kotlinx.coroutines.launch

/**
 * Lets the operator browse imported KML layers and toggle their visibility.
 *
 * The toggle hits ``PATCH /kml-layers/{id}`` so the choice is shared across
 * every connected client — operators don't keep "their own" view, which is the
 * tactical contract (BC says "Route Alpha is live" and everyone sees it).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KmlLayersScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var layers by remember { mutableStateOf<List<KmlLayerDto>>(emptyList()) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf<Int?>(null) }   // id of layer mid-toggle

    suspend fun refresh() {
        container.kmlLayerRepository.list()
            .onSuccess { layers = it; loadError = null }
            .onFailure { loadError = it.message }
    }

    LaunchedEffect(Unit) { refresh() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("KML layers") },
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
                text  = "KML layers are imported on the web dashboard. Toggle visibility " +
                        "here to overlay them on the tactical map.",
                style = MaterialTheme.typography.bodySmall,
                color = Color(0xFF94A3B8),
                modifier = Modifier.padding(vertical = 8.dp),
            )

            loadError?.let {
                Text(
                    text  = "Could not load layers: $it",
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                )
            }

            if (layers.isEmpty() && loadError == null) {
                Text(
                    text  = "No KML layers yet. Ask Battle Captain to import one from the web map.",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color(0xFF64748B),
                    modifier = Modifier.padding(top = 8.dp),
                )
            }

            LazyColumn(
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxSize().padding(top = 8.dp),
            ) {
                items(layers, key = { it.id }) { layer ->
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
                                text = layer.name,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.SemiBold,
                                color = Color(0xFFE2E8F0),
                            )
                            Text(
                                text  = "${layer.featureCount} feature(s)",
                                style = MaterialTheme.typography.bodySmall,
                                color = Color(0xFF64748B),
                            )
                            if (layer.description.isNotBlank()) {
                                Text(
                                    text  = layer.description,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = Color(0xFF94A3B8),
                                )
                            }
                        }
                        Switch(
                            checked = layer.visible,
                            enabled = busy != layer.id,
                            onCheckedChange = { wantOn ->
                                scope.launch {
                                    busy = layer.id
                                    container.kmlLayerRepository.setVisible(layer.id, wantOn)
                                        .onSuccess {
                                            layers = layers.map {
                                                if (it.id == layer.id) it.copy(visible = wantOn) else it
                                            }
                                        }
                                    busy = null
                                }
                            },
                        )
                    }
                }
            }
        }
    }
}
