package com.arrow.tactical.map.ui

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.network.TacticalObjectIn
import com.arrow.tactical.tactical.EnemyType
import com.google.android.gms.location.LocationServices
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MarkEnemyScreen(
    container: AppContainer,
    presetLat: Double?,
    presetLon: Double?,
    onMarked: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var selected by remember { mutableStateOf(EnemyType.INFANTRY) }
    var notes by remember { mutableStateOf("") }
    var visibility by remember { mutableStateOf("COMPANY") }
    var lat by remember { mutableStateOf(presetLat?.toString() ?: "") }
    var lon by remember { mutableStateOf(presetLon?.toString() ?: "") }
    var status by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }

    @SuppressLint("MissingPermission")
    fun fillFromCurrentLocation() {
        val ok = ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        if (!ok) { status = "Location permission required"; return }
        LocationServices.getFusedLocationProviderClient(context).lastLocation
            .addOnSuccessListener { loc ->
                if (loc != null) { lat = loc.latitude.toString(); lon = loc.longitude.toString() }
                else status = "No fix yet"
            }
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text("Mark Enemy / Object") }) },
    ) { padding ->
        Column(
            modifier = Modifier.padding(padding).padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("Type", style = MaterialTheme.typography.labelLarge)
            FlowRowChips(
                items = EnemyType.entries,
                selected = selected,
                onSelect = { selected = it },
                label = { it.label },
            )

            HorizontalDivider()
            Text("Location", style = MaterialTheme.typography.labelLarge)
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(value = lat, onValueChange = { lat = it }, label = { Text("Latitude") },
                    singleLine = true, modifier = Modifier.weight(1f))
                OutlinedTextField(value = lon, onValueChange = { lon = it }, label = { Text("Longitude") },
                    singleLine = true, modifier = Modifier.weight(1f))
            }
            TextButton(onClick = { fillFromCurrentLocation() }) { Text("Use my current GPS") }

            HorizontalDivider()
            Text("Comment / details", style = MaterialTheme.typography.labelLarge)
            OutlinedTextField(
                value = notes,
                onValueChange = { notes = it },
                label = { Text("e.g. ~10 dismounts heading north, light contact") },
                minLines = 3,
                modifier = Modifier.fillMaxWidth(),
            )

            HorizontalDivider()
            Text("Visibility", style = MaterialTheme.typography.labelLarge)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("TEAM", "SECTION", "PLATOON", "COMPANY").forEach {
                    FilterChip(selected = visibility == it, onClick = { visibility = it }, label = { Text(it) })
                }
            }

            Text("SIDC: ${selected.sidc}", style = MaterialTheme.typography.bodySmall)

            Spacer(Modifier.height(8.dp))
            Button(
                enabled = !busy && lat.toDoubleOrNull() != null && lon.toDoubleOrNull() != null,
                onClick = {
                    busy = true; status = null
                    scope.launch {
                        val payload = TacticalObjectIn(
                            type = selected.name,
                            symbolCode = selected.sidc,
                            latitude = lat.toDouble(),
                            longitude = lon.toDouble(),
                            notes = notes,
                            visibility = visibility,
                        )
                        container.tacticalRepository.mark(payload)
                            .onSuccess { busy = false; onMarked() }
                            .onFailure { busy = false; status = it.message }
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            ) { Text(if (busy) "Marking…" else "Mark on map") }

            status?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        }
    }
}

@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun <T> FlowRowChips(
    items: List<T>,
    selected: T,
    onSelect: (T) -> Unit,
    label: (T) -> String,
) {
    androidx.compose.foundation.layout.FlowRow(
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        items.forEach { item ->
            FilterChip(
                selected = item == selected,
                onClick = { onSelect(item) },
                label = { Text(label(item)) },
            )
        }
    }
}
