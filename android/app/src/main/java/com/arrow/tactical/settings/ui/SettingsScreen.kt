package com.arrow.tactical.settings.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.CloudSync
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.arrow.tactical.settings.SettingsRepository
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    repo: SettingsRepository,
    isAuthenticated: Boolean,
    onLogin: () -> Unit,
    onLogout: () -> Unit,
    onOpenOfflineMaps: () -> Unit = {},
    onOpenKmlLayers: () -> Unit = {},
    onOpenVisibility: () -> Unit = {},
) {
    val server   by repo.serverUrl.collectAsState(initial = SettingsRepository.DEFAULT_SERVER)
    val callsign by repo.callsign.collectAsState(initial = "")
    val team     by repo.team.collectAsState(initial = "")

    var serverDraft   by remember(server)   { mutableStateOf(server) }
    var callsignDraft by remember(callsign) { mutableStateOf(callsign) }
    var teamDraft     by remember(team)     { mutableStateOf(team) }
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

            // ── Sync status banner ─────────────────────────────────────────
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
                            Text("Data is saved on this device. Log in to sync with the server and collaborate with your team.",
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

            // ── Connection ────────────────────────────────────────────────
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

            // ── Identity ──────────────────────────────────────────────────
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
                label         = { Text("Team") },
                modifier      = Modifier.fillMaxWidth(),
                singleLine    = true,
            )

            Spacer(Modifier.height(4.dp))

            Button(
                onClick  = {
                    scope.launch {
                        repo.update(serverUrl = serverDraft, callsign = callsignDraft, team = teamDraft)
                        saved = true
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (saved) "Saved ✓" else "Save settings")
            }

            HorizontalDivider(Modifier.padding(vertical = 8.dp))

            // ── Offline maps ──────────────────────────────────────────────
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

            // ── Auth action ───────────────────────────────────────────────
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
