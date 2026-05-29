package com.arrow.tactical.map.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.arrow.tactical.map.RainViewerFrame
import java.text.SimpleDateFormat
import java.util.*

private val utcFmt = SimpleDateFormat("HH:mm'Z'", Locale.US).also {
    it.timeZone = TimeZone.getTimeZone("UTC")
}

private fun fmtUtc(epochSeconds: Long): String = utcFmt.format(Date(epochSeconds * 1000))

@Composable
fun WeatherPanel(
    radarFrames: List<RainViewerFrame>,
    nowcastStartIndex: Int,
    currentFrameIndex: Int,
    radarActive: Boolean,
    radarOpacity: Float,
    playing: Boolean,
    satActive: Boolean,
    satOpacity: Float,
    hasSat: Boolean,
    onClose: () -> Unit,
    onToggleRadar: (Boolean) -> Unit,
    onRadarOpacity: (Float) -> Unit,
    onTogglePlay: () -> Unit,
    onPrev: () -> Unit,
    onNext: () -> Unit,
    onSeek: (Int) -> Unit,
    onToggleSat: (Boolean) -> Unit,
    onSatOpacity: (Float) -> Unit,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val panelBg     = Color(0xF00B0F1C)
    val panelBorder = Color(0xFF1E293B)
    val textPrimary = Color(0xFFE2E8F0)
    val textMuted   = Color(0xFF94A3B8)
    val radarBlue   = Color(0xFF38BDF8)
    val satPurple   = Color(0xFFA78BFA)

    Column(
        modifier = modifier
            .width(272.dp)
            .background(panelBg, RoundedCornerShape(8.dp))
            .border(1.dp, panelBorder, RoundedCornerShape(8.dp))
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        // ── Header ────────────────────────────────────────────────────────
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("⛅ WEATHER", fontSize = 13.sp, fontWeight = FontWeight.Bold, color = textPrimary)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("↻", color = textMuted, fontSize = 16.sp,
                     modifier = Modifier.clickable { onRefresh() }.padding(4.dp))
                Text("✕", color = textMuted, fontSize = 14.sp,
                     modifier = Modifier.clickable { onClose() }.padding(4.dp))
            }
        }

        HorizontalDivider(color = panelBorder)

        // ── Radar section ─────────────────────────────────────────────────
        Text("RADAR", fontSize = 10.sp, color = textMuted,
             letterSpacing = 1.sp, fontWeight = FontWeight.SemiBold)

        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
            Checkbox(
                checked = radarActive,
                onCheckedChange = onToggleRadar,
                colors = CheckboxDefaults.colors(checkedColor = radarBlue),
                modifier = Modifier.size(20.dp),
            )
            Spacer(Modifier.width(8.dp))
            Text("🌧 Rain Radar", color = textPrimary, fontSize = 12.sp)
        }

        if (radarActive && radarFrames.isNotEmpty()) {
            // Opacity slider
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Opacity", color = textMuted, fontSize = 11.sp, modifier = Modifier.width(52.dp))
                Slider(
                    value = radarOpacity,
                    onValueChange = onRadarOpacity,
                    valueRange = 0f..1f,
                    modifier = Modifier.weight(1f).height(24.dp),
                    colors = SliderDefaults.colors(
                        thumbColor = radarBlue, activeTrackColor = radarBlue,
                    ),
                )
            }

            // Frame time + forecast indicator
            val frameTime = if (currentFrameIndex in radarFrames.indices)
                fmtUtc(radarFrames[currentFrameIndex].time) else "--:--Z"
            val isForecast = currentFrameIndex >= nowcastStartIndex

            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("⏮", color = textPrimary, fontSize = 20.sp,
                         modifier = Modifier.clickable { onPrev() }.padding(horizontal = 6.dp))
                    Text(if (playing) "⏸" else "▶", color = radarBlue, fontSize = 20.sp,
                         modifier = Modifier.clickable { onTogglePlay() }.padding(horizontal = 6.dp))
                    Text("⏭", color = textPrimary, fontSize = 20.sp,
                         modifier = Modifier.clickable { onNext() }.padding(horizontal = 6.dp))
                    Box(
                        modifier = Modifier
                            .background(
                                if (isForecast) Color(0xFF92400E) else Color(0xFF1E3A5F),
                                RoundedCornerShape(4.dp),
                            )
                            .padding(horizontal = 8.dp, vertical = 3.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = if (isForecast) "⚡ $frameTime" else frameTime,
                            color = if (isForecast) Color(0xFFFBBF24) else Color(0xFF7DD3FC),
                            fontSize = 10.sp,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }

                // Frame timeline slider
                Slider(
                    value = currentFrameIndex.toFloat(),
                    onValueChange = { onSeek(it.toInt()) },
                    valueRange = 0f..(radarFrames.size - 1).toFloat().coerceAtLeast(0f),
                    steps = (radarFrames.size - 2).coerceAtLeast(0),
                    modifier = Modifier.fillMaxWidth().height(24.dp),
                    colors = SliderDefaults.colors(
                        thumbColor = radarBlue, activeTrackColor = radarBlue,
                    ),
                )

                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(
                        text = radarFrames.firstOrNull()?.let { fmtUtc(it.time) } ?: "",
                        color = textMuted, fontSize = 9.sp,
                    )
                    if (nowcastStartIndex < radarFrames.size)
                        Text("⚡ Nowcast", color = Color(0xFFFBBF24), fontSize = 9.sp)
                    Text("LIVE ▸", color = Color(0xFF34D399), fontSize = 9.sp)
                }
            }
        }

        // ── Satellite section ─────────────────────────────────────────────
        if (hasSat) {
            HorizontalDivider(color = panelBorder)
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Checkbox(
                    checked = satActive,
                    onCheckedChange = onToggleSat,
                    colors = CheckboxDefaults.colors(checkedColor = satPurple),
                    modifier = Modifier.size(20.dp),
                )
                Spacer(Modifier.width(8.dp))
                Text("🛰 IR Satellite", color = textPrimary, fontSize = 12.sp)
            }
            if (satActive) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Opacity", color = textMuted, fontSize = 11.sp, modifier = Modifier.width(52.dp))
                    Slider(
                        value = satOpacity,
                        onValueChange = onSatOpacity,
                        valueRange = 0f..1f,
                        modifier = Modifier.weight(1f).height(24.dp),
                        colors = SliderDefaults.colors(
                            thumbColor = satPurple, activeTrackColor = satPurple,
                        ),
                    )
                }
            }
        }

        // ── Radar legend ─────────────────────────────────────────────────
        if (radarActive && radarFrames.isNotEmpty()) {
            HorizontalDivider(color = panelBorder)
            Text("RADAR INTENSITY (dBZ)", fontSize = 9.sp, color = textMuted, letterSpacing = 0.8.sp)
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(8.dp)
                    .background(
                        Brush.horizontalGradient(
                            listOf(
                                Color(0xFF0000CD),
                                Color(0xFF00BFFF),
                                Color(0xFF00FF00),
                                Color(0xFFFFFF00),
                                Color(0xFFFF4500),
                                Color(0xFF880088),
                            )
                        ),
                        RoundedCornerShape(4.dp),
                    )
            )
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                listOf("Light", "Mod.", "Heavy", "Extreme").forEach {
                    Text(it, color = textMuted, fontSize = 9.sp)
                }
            }
        }

        // ── Credits ───────────────────────────────────────────────────────
        Text(
            text = "Radar · Satellite: RainViewer",
            color = textMuted.copy(alpha = 0.55f),
            fontSize = 9.sp,
        )
    }
}
