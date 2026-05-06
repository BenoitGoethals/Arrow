package com.arrow.tactical.settings.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.arrow.tactical.settings.SettingsRepository
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(repo: SettingsRepository, onLogout: () -> Unit) {
    val server by repo.serverUrl.collectAsState(initial = SettingsRepository.DEFAULT_SERVER)
    val callsign by repo.callsign.collectAsState(initial = "")
    val team by repo.team.collectAsState(initial = "")

    var serverDraft by remember(server) { mutableStateOf(server) }
    var callsignDraft by remember(callsign) { mutableStateOf(callsign) }
    var teamDraft by remember(team) { mutableStateOf(team) }
    var saved by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Scaffold(topBar = { TopAppBar(title = { Text("Settings") }) }) { padding ->
        Column(modifier = Modifier.padding(padding).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedTextField(
                value = serverDraft,
                onValueChange = { serverDraft = it; saved = false },
                label = { Text("Backend URL (e.g. http://10.0.2.2:6001)") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            OutlinedTextField(
                value = callsignDraft,
                onValueChange = { callsignDraft = it; saved = false },
                label = { Text("Default callsign") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            OutlinedTextField(
                value = teamDraft,
                onValueChange = { teamDraft = it; saved = false },
                label = { Text("Team") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )

            Button(
                onClick = {
                    scope.launch {
                        repo.update(serverUrl = serverDraft, callsign = callsignDraft, team = teamDraft)
                        saved = true
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            ) { Text(if (saved) "Saved ✓" else "Save") }

            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            OutlinedButton(onClick = onLogout, modifier = Modifier.fillMaxWidth()) { Text("Sign out") }
        }
    }
}
