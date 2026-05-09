package com.arrow.tactical.admin.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.arrow.tactical.admin.LogEntry
import com.arrow.tactical.admin.LogRepository
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private val LEVELS = listOf("ALL", "E", "W", "I", "D", "V")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AdminScreen(repo: LogRepository) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current

    var entries by remember { mutableStateOf<List<LogEntry>>(emptyList()) }
    var levelFilter by remember { mutableStateOf("ALL") }
    var query by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var autoRefresh by remember { mutableStateOf(true) }

    suspend fun reload() {
        loading = true
        entries = repo.fetch()
        loading = false
    }

    LaunchedEffect(Unit) { reload() }

    LaunchedEffect(autoRefresh) {
        while (autoRefresh) {
            delay(2_500)
            entries = repo.fetch()
        }
    }

    val visible = remember(entries, levelFilter, query) {
        entries.asSequence()
            .filter { levelFilter == "ALL" || it.level == levelFilter }
            .filter {
                query.isBlank() ||
                it.tag.contains(query, ignoreCase = true) ||
                it.message.contains(query, ignoreCase = true)
            }
            .toList()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title  = {
                    Column {
                        Text("⚙ Admin · Logs", fontWeight = FontWeight.Bold)
                        Text(
                            "${visible.size} of ${entries.size}${if (loading) " · loading…" else ""}",
                            style = MaterialTheme.typography.labelSmall,
                            color = Color(0xFF94A3B8),
                        )
                    }
                },
                actions = {
                    IconButton(onClick = { autoRefresh = !autoRefresh }) {
                        Text(
                            if (autoRefresh) "⏸" else "▶",
                            fontSize = 16.sp,
                            color = if (autoRefresh) Color(0xFF22C55E) else Color(0xFF94A3B8),
                        )
                    }
                    IconButton(onClick = { scope.launch { reload() } }) {
                        Icon(Icons.Filled.Refresh, contentDescription = "Reload", tint = Color(0xFFCBD5E1))
                    }
                    IconButton(onClick = {
                        copyToClipboard(context, formatForExport(visible))
                    }) {
                        Icon(Icons.Filled.ContentCopy, contentDescription = "Copy", tint = Color(0xFFCBD5E1))
                    }
                    IconButton(onClick = {
                        scope.launch { repo.clear(); reload() }
                    }) {
                        Icon(Icons.Filled.Delete, contentDescription = "Clear", tint = Color(0xFFEF4444))
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color(0xFF0D1117),
                    titleContentColor = Color(0xFFE2E8F0),
                ),
            )
        },
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .background(Color(0xFF0D1117)),
        ) {
            // Filter bar
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                LEVELS.forEach { lvl ->
                    val active = levelFilter == lvl
                    val color  = colorFor(lvl)
                    Box(
                        modifier = Modifier
                            .clickable { levelFilter = lvl }
                            .background(
                                if (active) color.copy(alpha = 0.2f) else Color(0xFF1A2233),
                                RoundedCornerShape(4.dp),
                            )
                            .padding(horizontal = 8.dp, vertical = 4.dp),
                    ) {
                        Text(
                            text = lvl,
                            color = if (active) color else Color(0xFF94A3B8),
                            fontSize = 11.sp,
                            fontWeight = if (active) FontWeight.Bold else FontWeight.Normal,
                        )
                    }
                }
                Spacer(Modifier.weight(1f))
                OutlinedTextField(
                    value         = query,
                    onValueChange = { query = it },
                    placeholder   = { Text("filter…", fontSize = 12.sp) },
                    singleLine    = true,
                    modifier      = Modifier
                        .weight(2f)
                        .heightIn(min = 36.dp),
                    textStyle     = MaterialTheme.typography.bodySmall,
                )
            }

            HorizontalDivider(color = Color(0xFF2A3142))

            if (visible.isEmpty()) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(
                        if (entries.isEmpty()) "No log entries yet."
                        else "No entries match the filter.",
                        color = Color(0xFF475569),
                    )
                }
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(vertical = 4.dp),
                ) {
                    items(visible, key = { "${it.timestamp}-${it.tag}-${it.message.hashCode()}" }) { e ->
                        LogRow(e)
                        HorizontalDivider(color = Color(0xFF161B25), thickness = 0.5.dp)
                    }
                }
            }
        }
    }
}

@Composable
private fun LogRow(e: LogEntry) {
    val color = colorFor(e.level)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(if (e.isError) Color(0x332E1010) else Color.Transparent)
            .padding(horizontal = 8.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            text = e.level,
            color = color,
            fontWeight = FontWeight.Bold,
            fontSize = 11.sp,
            fontFamily = FontFamily.Monospace,
            modifier = Modifier.width(14.dp),
        )
        Text(
            text = e.timestamp.takeLast(12),  // HH:MM:SS.mmm
            color = Color(0xFF64748B),
            fontSize = 10.sp,
            fontFamily = FontFamily.Monospace,
        )
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = e.tag,
                color = Color(0xFF94A3B8),
                fontSize = 10.sp,
                fontWeight = FontWeight.SemiBold,
                fontFamily = FontFamily.Monospace,
            )
            Text(
                text = e.message,
                color = Color(0xFFE2E8F0),
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace,
            )
        }
    }
}

private fun colorFor(level: String): Color = when (level) {
    "E", "A", "F" -> Color(0xFFEF4444)
    "W"           -> Color(0xFFF59E0B)
    "I"           -> Color(0xFF22C55E)
    "D"           -> Color(0xFF60A5FA)
    "V"           -> Color(0xFF94A3B8)
    else          -> Color(0xFFCBD5E1)
}

private fun formatForExport(entries: List<LogEntry>): String =
    entries.joinToString("\n") { "${it.timestamp} ${it.level} ${it.tag}: ${it.message}" }

private fun copyToClipboard(context: Context, text: String) {
    val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
    cm?.setPrimaryClip(ClipData.newPlainText("Arrow logs", text))
}
