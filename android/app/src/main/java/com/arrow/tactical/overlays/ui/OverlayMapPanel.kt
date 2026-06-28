package com.arrow.tactical.overlays.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.LocationSearching
import androidx.compose.material.icons.filled.Upload
import androidx.compose.material.icons.filled.Download
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.arrow.tactical.overlays.OverlayDto

/**
 * Map-side panel for saved overlays. Each row toggles the overlay into the
 * per-device active set (the parent filters tactical objects to the union of
 * active overlays). Editors (ADMIN/BATTLE_CAPTAIN) can create overlays from the
 * objects on the map, export/import them as portable files, and delete them.
 */
@Composable
fun OverlayMapPanel(
    overlays: List<OverlayDto>,
    activeIds: Set<Int>,
    canEdit: Boolean,
    onToggle: (Int, Boolean) -> Unit,
    onCreate: (String) -> Unit,
    onDelete: (Int) -> Unit,
    onExport: (Int, String) -> Unit,
    onImport: () -> Unit,
    onFit: (Int) -> Unit,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var showCreate by remember { mutableStateOf(false) }

    Column(
        modifier = modifier
            .widthIn(min = 280.dp, max = 360.dp)
            .background(Color(0xFF0E1217), RoundedCornerShape(8.dp))
            .border(0.5.dp, Color(0xFF2A3142), RoundedCornerShape(8.dp))
            .padding(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = "Saved overlays",
                color = Color(0xFFE2E8F0),
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = onClose, modifier = Modifier.size(28.dp)) {
                Icon(Icons.Filled.Close, "Close", tint = Color(0xFFCBD5E1), modifier = Modifier.size(18.dp))
            }
        }

        if (canEdit) {
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedButton(
                    onClick = { showCreate = true },
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Filled.Add, null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("New", fontSize = 12.sp)
                }
                OutlinedButton(
                    onClick = onImport,
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                ) {
                    Icon(Icons.Filled.Upload, null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Import", fontSize = 12.sp)
                }
            }
        }

        Spacer(Modifier.height(6.dp))

        if (overlays.isEmpty()) {
            Text(
                text = if (canEdit) "No overlays yet. Tap New to create one." else "No overlays saved.",
                color = Color(0xFF64748B),
                fontSize = 12.sp,
                modifier = Modifier.padding(vertical = 8.dp),
            )
        } else {
            LazyColumn(
                modifier = Modifier.heightIn(max = 340.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                items(overlays, key = { it.id }) { ov ->
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(Color(0xFF161B25), RoundedCornerShape(4.dp))
                            .border(0.5.dp, Color(0xFF2A3142), RoundedCornerShape(4.dp))
                            .padding(start = 6.dp, end = 2.dp, top = 4.dp, bottom = 4.dp),
                    ) {
                        Switch(
                            checked = ov.id in activeIds,
                            onCheckedChange = { onToggle(ov.id, it) },
                            modifier = Modifier.scale(0.7f),
                        )
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                ov.name,
                                color = Color(0xFFE2E8F0),
                                fontFamily = FontFamily.Monospace,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                            Text(
                                "${ov.objectIds.size} object(s)" +
                                    if (ov.description.isNotBlank()) "  ·  ${ov.description.take(32)}" else "",
                                color = Color(0xFF64748B),
                                fontSize = 10.sp,
                            )
                        }
                        IconButton(onClick = { onFit(ov.id) }, modifier = Modifier.size(30.dp)) {
                            Icon(Icons.Filled.LocationSearching, "Fit", tint = Color(0xFFCBD5E1), modifier = Modifier.size(16.dp))
                        }
                        IconButton(onClick = { onExport(ov.id, ov.name) }, modifier = Modifier.size(30.dp)) {
                            Icon(Icons.Filled.Download, "Export", tint = Color(0xFFCBD5E1), modifier = Modifier.size(16.dp))
                        }
                        if (canEdit) {
                            IconButton(onClick = { onDelete(ov.id) }, modifier = Modifier.size(30.dp)) {
                                Icon(Icons.Filled.Delete, "Delete", tint = Color(0xFFF87171), modifier = Modifier.size(16.dp))
                            }
                        }
                    }
                }
            }
        }

        Spacer(Modifier.height(6.dp))
        Text(
            "No overlay active → every object shows. Drawings on an active overlay show with it.",
            color = Color(0xFF64748B),
            fontSize = 10.sp,
        )
    }

    if (showCreate) {
        var name by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { showCreate = false },
            title = { Text("New overlay") },
            text = {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    singleLine = true,
                    label = { Text("Name") },
                )
            },
            confirmButton = {
                TextButton(
                    onClick = { if (name.isNotBlank()) { onCreate(name.trim()); showCreate = false } },
                ) { Text("Create from visible objects") }
            },
            dismissButton = { TextButton(onClick = { showCreate = false }) { Text("Cancel") } },
        )
    }
}
