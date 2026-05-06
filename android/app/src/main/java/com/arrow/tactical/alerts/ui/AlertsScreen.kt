package com.arrow.tactical.alerts.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.arrow.tactical.alerts.AlertRepository
import com.arrow.tactical.network.AlertDto
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AlertsScreen(repo: AlertRepository) {
    var alerts by remember { mutableStateOf<List<AlertDto>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    suspend fun refresh() {
        repo.list().onSuccess { alerts = it }.onFailure { error = it.message }
    }

    LaunchedEffect(Unit) {
        while (true) { refresh(); delay(5_000) }
    }

    Scaffold(topBar = { TopAppBar(title = { Text("Alerts") }) }) { padding ->
        Column(modifier = Modifier.padding(padding).padding(16.dp)) {
            Text("Trigger emergency", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("TIC", "MEDICAL", "EVAC", "LOST_COMMS").forEach { type ->
                    Button(onClick = {
                        scope.launch { repo.trigger(type).onFailure { error = it.message }; refresh() }
                    }) { Text(type) }
                }
            }

            error?.let { Spacer(Modifier.height(8.dp)); Text(it, color = MaterialTheme.colorScheme.error) }

            HorizontalDivider(Modifier.padding(vertical = 12.dp))
            Text("Recent alerts", style = MaterialTheme.typography.titleMedium)
            LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                items(alerts) { a ->
                    ListItem(
                        headlineContent = { Text("${a.type} — ${a.status}") },
                        supportingContent = { Text("operator #${a.operatorId}") },
                    )
                }
            }
        }
    }
}
