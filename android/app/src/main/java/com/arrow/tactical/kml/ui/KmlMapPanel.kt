package com.arrow.tactical.kml.ui

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
import com.arrow.tactical.kml.KmlLayerDto
import kotlinx.coroutines.launch

/**
 * Floating panel anchored to the right side of the tactical map. Lists the
 * imported KML layers and lets the operator toggle each one on/off.
 *
 * Toggles ``PATCH /kml-layers/{id}``, matching the web client — visibility is
 * shared across every operator so a BC can show/hide a layer for everyone.
 * Local-only hiding can be added later as a second flag if doctrine changes.
 */
@Composable
fun KmlMapPanel(
    layers: List<KmlLayerDto>,
    onToggle: suspend (Int, Boolean) -> Result<Unit>,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf<Int?>(null) }
    Column(
        modifier = modifier
            .widthIn(min = 240.dp, max = 320.dp)
            .background(Color(0xFF0E1217), RoundedCornerShape(8.dp))
            .border(0.5.dp, Color(0xFF2A3142), RoundedCornerShape(8.dp))
            .padding(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text  = "KML layers",
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

        if (layers.isEmpty()) {
            Text(
                text  = "No layers imported.\nImport KML/KMZ from the web map.",
                color = Color(0xFF64748B),
                fontSize = 12.sp,
                modifier = Modifier.padding(vertical = 8.dp),
            )
        } else {
            LazyColumn(
                modifier = Modifier.heightIn(max = 320.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                items(layers, key = { it.id }) { layer ->
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
                                text = layer.name,
                                color = Color(0xFFE2E8F0),
                                fontFamily = FontFamily.Monospace,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                            Text(
                                text  = "${layer.featureCount} feature(s)",
                                color = Color(0xFF64748B),
                                fontSize = 10.sp,
                            )
                        }
                        Switch(
                            checked = layer.visible,
                            enabled = busy != layer.id,
                            onCheckedChange = { wantOn ->
                                scope.launch {
                                    busy = layer.id
                                    onToggle(layer.id, wantOn)
                                    busy = null
                                }
                            },
                            modifier = Modifier.scale(0.75f),
                        )
                    }
                }
            }
        }
    }
}
