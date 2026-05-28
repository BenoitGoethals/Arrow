package com.arrow.tactical.settings.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.CloudSync
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.arrow.tactical.auth.OperatorProfile
import com.arrow.tactical.auth.ProfileStore
import com.arrow.tactical.settings.SettingsRepository
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    repo: SettingsRepository,
    profileStore: ProfileStore,
    isAuthenticated: Boolean,
    onLogin: () -> Unit,
    onLogout: () -> Unit,
    onOpenOfflineMaps: () -> Unit = {},
    onOpenKmlLayers: () -> Unit = {},
    onOpenVisibility: () -> Unit = {},
) {
    val server   by repo.serverUrl.collectAsState(initial = SettingsRepository.DEFAULT_SERVER)
    val profile  by profileStore.profile.collectAsState(initial = null)

    // Guest-mode editable identity (only used when not authenticated)
    val callsign by repo.callsign.collectAsState(initial = "")
    val team     by repo.team.collectAsState(initial = "")
    var callsignDraft by remember(callsign) { mutableStateOf(callsign) }
    var teamDraft     by remember(team)     { mutableStateOf(team) }

    var serverDraft by remember(server) { mutableStateOf(server) }
    var saved by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Scaffold(topBar = { TopAppBar(title = { Text("Settings") }) }) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .padding(horizontal = 16.dp)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .imePadding(),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Spacer(Modifier.height(4.dp))

            // ── Guest mode banner ──────────────────────────────────────────
            if (!isAuthenticated) {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.secondaryContainer,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        modifier = Modifier.padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Icon(Icons.Filled.CloudOff, contentDescription = null,
                            tint = MaterialTheme.colorScheme.onSecondaryContainer)
                        Column {
                            Text("Guest mode — local only",
                                style = MaterialTheme.typography.titleSmall,
                                color = MaterialTheme.colorScheme.onSecondaryContainer)
                            Text("Log in to sync with the server and join your team.",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSecondaryContainer)
                        }
                    }
                }

                Button(
                    onClick  = onLogin,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(Icons.Filled.CloudSync, contentDescription = null,
                        modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("Login to sync with server")
                }

                HorizontalDivider(Modifier.padding(vertical = 4.dp))
            }

            // ── Connection ─────────────────────────────────────────────────
            Text("Connection", style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary)

            OutlinedTextField(
                value         = serverDraft,
                onValueChange = { serverDraft = it; saved = false },
                label         = { Text("Backend URL") },
                placeholder   = { Text("http://192.168.0.x:6001") },
                modifier      = Modifier.fillMaxWidth(),
                singleLine    = true,
            )

            Button(
                onClick = {
                    scope.launch {
                        if (isAuthenticated) {
                            repo.update(serverUrl = serverDraft)
                        } else {
                            repo.update(serverUrl = serverDraft,
                                        callsign = callsignDraft,
                                        team = teamDraft)
                        }
                        saved = true
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (saved) "Saved ✓" else "Save settings")
            }

            HorizontalDivider(Modifier.padding(vertical = 4.dp))

            // ── Identity ───────────────────────────────────────────────────
            if (isAuthenticated && profile != null) {
                ProfileCard(profile = profile!!)
            } else if (!isAuthenticated) {
                Text("Identity", style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.primary)

                OutlinedTextField(
                    value         = callsignDraft,
                    onValueChange = { callsignDraft = it; saved = false },
                    label         = { Text("Callsign") },
                    modifier      = Modifier.fillMaxWidth(),
                    singleLine    = true,
                )
                OutlinedTextField(
                    value         = teamDraft,
                    onValueChange = { teamDraft = it; saved = false },
                    label         = { Text("Team (guest)") },
                    modifier      = Modifier.fillMaxWidth(),
                    singleLine    = true,
                )
            }

            HorizontalDivider(Modifier.padding(vertical = 4.dp))

            // ── Offline maps ───────────────────────────────────────────────
            Text("Offline base maps", style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary)
            OutlinedButton(onClick = onOpenOfflineMaps, modifier = Modifier.fillMaxWidth()) {
                Text("Download maps for offline use")
            }

            Text("KML overlays", style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary)
            OutlinedButton(onClick = onOpenKmlLayers, modifier = Modifier.fillMaxWidth()) {
                Text("Browse imported KML layers")
            }

            Text("Visibility", style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary)
            OutlinedButton(onClick = onOpenVisibility, modifier = Modifier.fillMaxWidth()) {
                Text("Map + notification preferences")
            }

            HorizontalDivider(Modifier.padding(vertical = 8.dp))

            // ── Auth action ────────────────────────────────────────────────
            if (isAuthenticated) {
                OutlinedButton(
                    onClick  = onLogout,
                    modifier = Modifier.fillMaxWidth(),
                    colors   = ButtonDefaults.outlinedButtonColors(
                        contentColor = MaterialTheme.colorScheme.error,
                    ),
                ) {
                    Text("Sign out")
                }
            }

            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun ProfileCard(profile: OperatorProfile) {
    Text("My Profile", style = MaterialTheme.typography.labelLarge,
        color = MaterialTheme.colorScheme.primary)

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Icon(Icons.Filled.Person, contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(28.dp))
                Column {
                    Text(profile.callsign,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold)
                    Text("${profile.rank}  ·  ${profile.role}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }

            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

            if (profile.teamRole != null) {
                ProfileRow(
                    label = "Team role",
                    value = profile.teamRole.replace('_', ' ')
                        .lowercase()
                        .replaceFirstChar { it.uppercase() },
                )
            }

            // Hierarchy path: Team · Section · Platoon · Company
            val hierarchyParts = listOfNotNull(
                profile.teamName,
                profile.sectionName,
                profile.platoonName,
                profile.companyName,
            )
            if (hierarchyParts.isNotEmpty()) {
                ProfileRow(label = "Unit", value = hierarchyParts.joinToString(" › "))
            } else if (profile.teamId != null) {
                ProfileRow(label = "Team ID", value = "#${profile.teamId}")
            } else {
                ProfileRow(label = "Unit", value = "Unassigned")
            }

            if (profile.missionName != null) {
                ProfileRow(label = "Mission", value = profile.missionName)
            } else if (profile.missionId != null) {
                ProfileRow(label = "Mission ID", value = "#${profile.missionId}")
            } else {
                ProfileRow(label = "Mission", value = "Not assigned")
            }
        }
    }
}

@Composable
private fun ProfileRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium)
    }
}
