package com.arrow.tactical.alerts.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.arrow.tactical.alerts.AlertRepository
import com.arrow.tactical.network.AlertDto
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private data class AlertTypeDef(val key: String, val label: String, val color: Color)

private val ALERT_TYPES = listOf(
    AlertTypeDef("TIC",        "⚠ TIC",        Color(0xFFDC2626)),
    AlertTypeDef("MEDICAL",    "✚ MEDICAL",     Color(0xFF16A34A)),
    AlertTypeDef("EVAC",       "↑ EVAC",        Color(0xFFD97706)),
    AlertTypeDef("LOST_COMMS", "✕ LOST COMMS",  Color(0xFF2563EB)),
)

// Received-only alert types — shown in the feed/marker but NOT offered in the
// raise picker above (DRONE_SPOTTED = drone-spot side-effect; ATAK_EMERGENCY =
// ATAK CoT emergency button).
private val ALERT_TYPES_RECEIVED = listOf(
    AlertTypeDef("DRONE_SPOTTED",  "🛸 DRONE",      Color(0xFFD2A8FF)),
    AlertTypeDef("ATAK_EMERGENCY", "⚠ ATAK EMERG", Color(0xFFDC2626)),
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AlertsScreen(repo: AlertRepository) {
    var alerts by remember { mutableStateOf<List<AlertDto>>(emptyList()) }
    var error  by remember { mutableStateOf<String?>(null) }
    val scope  = rememberCoroutineScope()

    suspend fun refresh() {
        repo.list().onSuccess { alerts = it }.onFailure { error = it.message }
    }

    LaunchedEffect(Unit) {
        while (true) { refresh(); delay(5_000) }
    }

    Scaffold(topBar = { TopAppBar(title = { Text("Alerts") }) }) { padding ->
        LazyColumn(
            modifier        = Modifier.padding(padding).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding  = PaddingValues(vertical = 16.dp),
        ) {
            item {
                Text(
                    "Trigger emergency",
                    style      = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(10.dp))
                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    ALERT_TYPES.forEach { def ->
                        Button(
                            onClick = {
                                error = null
                                scope.launch {
                                    repo.trigger(def.key).onFailure { error = it.message }
                                    refresh()
                                }
                            },
                            modifier = Modifier.weight(1f),
                            colors   = ButtonDefaults.buttonColors(containerColor = def.color),
                        ) {
                            Text(def.label, fontSize = 11.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                        }
                    }
                }
                error?.let {
                    Spacer(Modifier.height(6.dp))
                    Text(it, color = MaterialTheme.colorScheme.error,
                         style = MaterialTheme.typography.bodySmall)
                }
            }

            item {
                Spacer(Modifier.height(4.dp))
                HorizontalDivider()
                Spacer(Modifier.height(8.dp))
                Text(
                    "Recent alerts",
                    style      = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
            }

            if (alerts.isEmpty()) {
                item {
                    Text(
                        "No alerts.",
                        color  = MaterialTheme.colorScheme.onSurfaceVariant,
                        style  = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(vertical = 8.dp),
                    )
                }
            } else {
                items(alerts) { a -> AlertRow(a) }
            }
        }
    }
}

@Composable
private fun AlertRow(alert: AlertDto) {
    val def   = (ALERT_TYPES + ALERT_TYPES_RECEIVED).find { it.key == alert.type }
    val color = def?.color ?: Color(0xFF64748B)

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .border(0.5.dp, color.copy(alpha = 0.35f), RoundedCornerShape(8.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment     = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Surface(color = color.copy(alpha = 0.18f), shape = RoundedCornerShape(4.dp)) {
            Text(
                alert.type,
                modifier   = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                style      = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Bold,
                color      = color,
            )
        }
        Column(modifier = Modifier.weight(1f)) {
            Text(alert.status, style = MaterialTheme.typography.bodySmall,
                 fontWeight = FontWeight.Medium)
            Text("Operator #${alert.operatorId}",
                 style = MaterialTheme.typography.labelSmall,
                 color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
