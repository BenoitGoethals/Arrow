package com.arrow.tactical.reports.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.arrow.tactical.reports.ReportRepository
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReportsScreen(repo: ReportRepository) {
    val scope = rememberCoroutineScope()
    var type by remember { mutableStateOf("CONTACT") }
    var summary by remember { mutableStateOf("") }
    var size by remember { mutableStateOf("") }
    var direction by remember { mutableStateOf("") }
    var msg by remember { mutableStateOf<String?>(null) }

    Scaffold(topBar = { TopAppBar(title = { Text("Reports") }) }) { padding ->
        Column(modifier = Modifier.padding(padding).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Type", style = MaterialTheme.typography.labelLarge)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("CONTACT", "SPOT", "CASEVAC", "MEDEVAC", "CAS").forEach {
                    FilterChip(selected = type == it, onClick = { type = it }, label = { Text(it) })
                }
            }
            OutlinedTextField(value = summary, onValueChange = { summary = it }, label = { Text("Summary") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(value = size, onValueChange = { size = it }, label = { Text("Size / strength") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(value = direction, onValueChange = { direction = it }, label = { Text("Direction / heading") }, modifier = Modifier.fillMaxWidth())

            Button(
                modifier = Modifier.fillMaxWidth(),
                onClick = {
                    val payload = buildJsonObject {
                        put("summary", JsonPrimitive(summary))
                        put("size", JsonPrimitive(size))
                        put("direction", JsonPrimitive(direction))
                    }
                    scope.launch {
                        repo.submit(type, payload)
                            .onSuccess { msg = "Report submitted." }
                            .onFailure { msg = it.message }
                    }
                },
            ) { Text("Submit") }

            msg?.let { Text(it) }
        }
    }
}
