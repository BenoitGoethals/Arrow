package com.arrow.tactical.mission.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.network.MissionDto
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MissionSelectionScreen(
    container: AppContainer,
    onMissionSelected: () -> Unit,
) {
    val scope    = rememberCoroutineScope()
    var missions by remember { mutableStateOf<List<MissionDto>>(emptyList()) }
    var loading  by remember { mutableStateOf(true) }
    var error    by remember { mutableStateOf<String?>(null) }
    var showCreate  by remember { mutableStateOf(false) }
    var newName     by remember { mutableStateOf("") }
    var newMgrs     by remember { mutableStateOf("") }
    var newZoom     by remember { mutableStateOf("13") }
    var creating    by remember { mutableStateOf(false) }

    val activeMission by container.missionRepository.activeMission.collectAsState()

    LaunchedEffect(Unit) {
        container.missionRepository.listMissions()
            .onSuccess { missions = it; loading = false }
            .onFailure { error = it.message; loading = false }
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text("Select Mission") }) },
        floatingActionButton = {
            FloatingActionButton(onClick = { showCreate = true }) {
                Icon(Icons.Default.Add, "New mission")
            }
        },
    ) { padding ->
        Box(Modifier.padding(padding).fillMaxSize()) {
            when {
                loading -> CircularProgressIndicator(Modifier.align(Alignment.Center))
                error != null -> Text("Error: $error",
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.align(Alignment.Center).padding(16.dp))
                else -> LazyColumn(contentPadding = PaddingValues(12.dp),
                                   verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    item {
                        NoMissionCard(
                            isActive = activeMission == null,
                            onSelect = {
                                container.missionRepository.clearMission()
                                onMissionSelected()
                            },
                        )
                    }
                    if (missions.isEmpty()) {
                        item {
                            Text(
                                "No missions yet — tap + to create one",
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(8.dp),
                            )
                        }
                    }
                    items(missions, key = { it.id }) { mission ->
                        MissionCard(
                            mission   = mission,
                            isActive  = mission.id == activeMission?.id,
                            onSelect  = {
                                container.missionRepository.selectMission(mission)
                                onMissionSelected()
                            },
                        )
                    }
                }
            }
        }
    }

    if (showCreate) {
        AlertDialog(
            onDismissRequest = { showCreate = false; newName = ""; newMgrs = ""; newZoom = "13" },
            title   = { Text("New Mission") },
            text    = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = newName,
                        onValueChange = { newName = it },
                        label = { Text("Mission name") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = newMgrs,
                        onValueChange = { newMgrs = it },
                        label = { Text("Map center (MGRS, optional)") },
                        placeholder = { Text("e.g. 31UCU 12345 67890") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = newZoom,
                        onValueChange = { newZoom = it },
                        label = { Text("Zoom (3–19)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
            confirmButton = {
                Button(
                    enabled = newName.isNotBlank() && !creating,
                    onClick = {
                        creating = true
                        scope.launch {
                            val zoom = newZoom.trim().toIntOrNull()?.coerceIn(3, 19) ?: 13
                            val center = if (newMgrs.isNotBlank())
                                com.arrow.tactical.network.MgrsConverter.decode(newMgrs.trim())
                            else null
                            container.missionRepository.createMission(
                                name         = newName.trim(),
                                mapCenterLat = center?.first,
                                mapCenterLng = center?.second,
                                mapZoom      = zoom,
                            )
                                .onSuccess { m ->
                                    missions = missions + m
                                    showCreate = false
                                    newName = ""; newMgrs = ""; newZoom = "13"
                                    container.missionRepository.selectMission(m)
                                    onMissionSelected()
                                }
                                .onFailure { error = it.message }
                            creating = false
                        }
                    },
                ) { Text(if (creating) "Creating…" else "Create") }
            },
            dismissButton = {
                TextButton(onClick = {
                    showCreate = false; newName = ""; newMgrs = ""; newZoom = "13"
                }) { Text("Cancel") }
            },
        )
    }
}

@Composable
private fun NoMissionCard(
    isActive: Boolean,
    onSelect: () -> Unit,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onSelect),
        colors = CardDefaults.cardColors(
            containerColor = if (isActive)
                MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.3f)
            else MaterialTheme.colorScheme.surfaceVariant,
        ),
        border = if (isActive) androidx.compose.foundation.BorderStroke(
            1.5.dp, MaterialTheme.colorScheme.primary
        ) else null,
    ) {
        Row(
            Modifier.padding(14.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Icon(
                if (isActive) Icons.Default.CheckCircle else Icons.Default.RadioButtonUnchecked,
                contentDescription = null,
                tint = if (isActive) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline,
            )
            Text(
                "No mission",
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun MissionCard(
    mission: MissionDto,
    isActive: Boolean,
    onSelect: () -> Unit,
) {
    val statusColor = when (mission.status) {
        "ACTIVE"   -> Color(0xFF22C55E)
        "PLANNING" -> Color(0xFFF59E0B)
        "ENDED"    -> Color(0xFFEF4444)
        else       -> Color(0xFF64748B)
    }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onSelect),
        colors = CardDefaults.cardColors(
            containerColor = if (isActive)
                MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.3f)
            else MaterialTheme.colorScheme.surfaceVariant,
        ),
        border = if (isActive) androidx.compose.foundation.BorderStroke(
            1.5.dp, MaterialTheme.colorScheme.primary
        ) else null,
    ) {
        Row(
            Modifier.padding(14.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Icon(
                if (isActive) Icons.Default.CheckCircle else Icons.Default.RadioButtonUnchecked,
                contentDescription = null,
                tint = if (isActive) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline,
            )
            Column(Modifier.weight(1f)) {
                Text(mission.name, fontWeight = FontWeight.SemiBold,
                     color = MaterialTheme.colorScheme.onSurface)
                if (mission.description.isNotBlank()) {
                    Text(mission.description, fontSize = 12.sp,
                         color = MaterialTheme.colorScheme.onSurfaceVariant,
                         maxLines = 2)
                }
                if (mission.mapCenterMgrs != null) {
                    Text(
                        "📍 ${mission.mapCenterMgrs} z${mission.mapZoom}",
                        fontSize = 11.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Surface(
                color = statusColor.copy(alpha = 0.15f),
                shape = MaterialTheme.shapes.small,
            ) {
                Text(
                    mission.status,
                    fontSize = 11.sp,
                    color = statusColor,
                    fontWeight = FontWeight.Medium,
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                )
            }
        }
    }
}
