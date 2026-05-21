package com.arrow.tactical.settings.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.arrow.tactical.settings.SettingsRepository
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    repo: SettingsRepository,
    onLogout: () -> Unit,
    onOpenOfflineMaps: () -> Unit = {},
    onOpenKmlLayers: () -> Unit = {},
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
                .verticalScroll(rememberScrollState())  // scrollable in landscape
                .imePadding(),                           // scroll above keyboard
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Spacer(Modifier.height(4.dp))

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
                        repo.update(
                            serverUrl = serverDraft,
                            callsign  = callsignDraft,
                            team      = teamDraft,
                        )
                        saved = true
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (saved) "Saved ✓" else "Save settings")
            }

            HorizontalDivider(Modifier.padding(vertical = 8.dp))

            Text("Offline base maps", style = MaterialTheme.typography.labelLarge,
                 color = MaterialTheme.colorScheme.primary)
            OutlinedButton(
                onClick  = onOpenOfflineMaps,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Download maps for offline use")
            }

            Text("KML overlays", style = MaterialTheme.typography.labelLarge,
                 color = MaterialTheme.colorScheme.primary)
            OutlinedButton(
                onClick  = onOpenKmlLayers,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Browse imported KML layers")
            }

            HorizontalDivider(Modifier.padding(vertical = 8.dp))

            OutlinedButton(
                onClick  = onLogout,
                modifier = Modifier.fillMaxWidth(),
                colors   = ButtonDefaults.outlinedButtonColors(
                    contentColor = MaterialTheme.colorScheme.error,
                ),
            ) {
                Text("Sign out")
            }

            Spacer(Modifier.height(16.dp))
        }
    }
}
