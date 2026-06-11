package com.arrow.tactical.overlays.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
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
 * Map-side panel listing saved overlays. Each row carries a Switch that adds
 * or removes the overlay from the per-device active set; the parent screen
 * filters tactical objects to the union of active overlays' object_ids.
 */
@Composable
fun OverlayMapPanel(
    overlays: List<OverlayDto>,
    activeIds: Set<Int>,
    onToggle: (Int, Boolean) -> Unit,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .widthIn(min = 260.dp, max = 340.dp)
            .background(Color(0xFF0E1217), RoundedCornerShape(8.dp))
            .border(0.5.dp, Color(0xFF2A3142), RoundedCornerShape(8.dp))
            .padding(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text  = "Saved overlays",
                color = Color(0xFFE2E8F0),
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = onClose, modifier = Modifier.size(28.dp)) {
                Icon(Icons.Filled.Close, contentDescription = "Close",
                     tint = Color(0xFFCBD5E1), modifier = Modifier.size(18.dp))
            }
        }
        Spacer(Modifier.height(4.dp))

        if (overlays.isEmpty()) {
            Text(
                text  = "No overlays saved.\nCreate them on the web map.",
                color = Color(0xFF64748B),
                fontSize = 12.sp,
                modifier = Modifier.padding(vertical = 8.dp),
            )
        } else {
            LazyColumn(
                modifier = Modifier.heightIn(max = 320.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                items(overlays, key = { it.id }) { ov ->
                    val active = ov.id in activeIds
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(Color(0xFF161B25), RoundedCornerShape(4.dp))
                            .border(0.5.dp, Color(0xFF2A3142), RoundedCornerShape(4.dp))
                            .padding(horizontal = 6.dp, vertical = 4.dp),
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = ov.name,
                                color = Color(0xFFE2E8F0),
                                fontFamily = FontFamily.Monospace,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                            Text(
                                text  = "${ov.objectIds.size} object(s)" +
                                        if (ov.description.isNotBlank()) "  ·  ${ov.description.take(40)}" else "",
                                color = Color(0xFF64748B),
                                fontSize = 10.sp,
                            )
                        }
                        Switch(
                            checked = active,
                            onCheckedChange = { onToggle(ov.id, it) },
                            modifier = Modifier.scale(0.75f),
                        )
                    }
                }
            }
        }

        Spacer(Modifier.height(6.dp))
        Text(
            text  = "No overlay active → every tactical object is shown.",
            color = Color(0xFF64748B),
            fontSize = 10.sp,
        )
    }
}
