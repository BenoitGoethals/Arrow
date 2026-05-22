package com.arrow.tactical.admin.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.ui.unit.sp
import com.arrow.tactical.admin.ALL_VIS_FLAGS
import com.arrow.tactical.admin.MAP_FLAGS
import com.arrow.tactical.admin.NOTIF_FLAGS
import com.arrow.tactical.admin.VisibilityFlag
import com.arrow.tactical.di.AppContainer
import kotlinx.coroutines.launch

/**
 * Per-operator visibility preferences — every operator on this device has
 * their own. Two grids: what's drawn on the tactical map and what pops up as
 * a toast / system notification. The underlying records are not deleted.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VisibilitySettingsScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val visibility by container.mapVisibilityRepository.flow.collectAsState()

    LaunchedEffect(Unit) { container.mapVisibilityRepository.seedFromServerIfEmpty() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Map + notification visibility") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    TextButton(onClick = {
                        scope.launch { container.mapVisibilityRepository.setAll(true) }
                    }) { Text("Show all", color = Color(0xFF34D399)) }
                    TextButton(onClick = {
                        scope.launch { container.mapVisibilityRepository.setAll(false) }
                    }) { Text("Hide all", color = Color(0xFFEF4444)) }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 12.dp),
        ) {
            Spacer(Modifier.height(4.dp))
            Text(
                text  = "These preferences are stored on this device only — every " +
                        "operator controls what they see without affecting anyone " +
                        "else. The underlying records are NOT deleted; flipping a " +
                        "flag back on brings them straight back.",
                color = Color(0xFF94A3B8),
                fontSize = 12.sp,
                modifier = Modifier.padding(bottom = 12.dp),
            )

            SectionHeader("🗺  On the map")
            for (f in MAP_FLAGS) {
                VisRow(f, on = f.get(visibility)) { wantOn ->
                    scope.launch { container.mapVisibilityRepository.setFlag(f.key, wantOn) }
                }
            }

            Spacer(Modifier.height(12.dp))
            SectionHeader("🔔  Notifications")
            for (f in NOTIF_FLAGS) {
                VisRow(f, on = f.get(visibility)) { wantOn ->
                    scope.launch { container.mapVisibilityRepository.setFlag(f.key, wantOn) }
                }
            }

            Spacer(Modifier.height(16.dp))
            OutlinedButton(
                onClick = {
                    scope.launch { container.mapVisibilityRepository.resetToServerDefaults() }
                },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("↺  Reset to admin defaults") }
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun SectionHeader(text: String) {
    Text(
        text  = text,
        color = Color(0xFF94A3B8),
        fontSize = 11.sp,
        letterSpacing = 1.5.sp,
        fontWeight = FontWeight.Bold,
        modifier = Modifier.padding(top = 8.dp, bottom = 6.dp),
    )
}

@Composable
private fun VisRow(
    f: VisibilityFlag,
    on: Boolean,
    onChange: (Boolean) -> Unit,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .background(Color(0xFF161B25), RoundedCornerShape(6.dp))
            .border(0.5.dp, if (on) Color(0xFF1E3A2F) else Color(0xFF2A3142),
                    RoundedCornerShape(6.dp))
            .padding(horizontal = 10.dp, vertical = 8.dp),
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = "${f.icon}  ${f.label}",
                    color = Color(0xFFE2E8F0),
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 13.sp,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    text = if (on) "VISIBLE" else "HIDDEN",
                    color = if (on) Color(0xFF34D399) else Color(0xFFEF4444),
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
            Text(
                text = f.description,
                color = Color(0xFF94A3B8),
                fontSize = 11.sp,
                modifier = Modifier.padding(top = 2.dp),
            )
        }
        Switch(checked = on, onCheckedChange = onChange)
    }
    Spacer(Modifier.height(6.dp))
}
