package com.arrow.tactical.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Cloud
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.PersonOff
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val BgColor     = Color(0xFF0F2540)
private val TextColor   = Color(0xFFCBD5E1)
private val OnlineColor = Color(0xFF22C55E)
private val OfflineColor= Color(0xFFEF4444)
private val GuestColor  = Color(0xFFF59E0B)

/**
 * Compact status strip shown at the top of every non-map screen.
 *
 * Left side  — auth: "GUEST" (amber) | callsign + role (green)
 * Right side — server link: green dot "ONLINE" | red dot "OFFLINE"
 */
@Composable
fun ArrowStatusBar(
    callsign: String,         // empty = guest / not authenticated
    role: String?,
    isOnline: Boolean,
    modifier: Modifier = Modifier,
) {
    val authenticated = callsign.isNotBlank()

    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(BgColor)
            .padding(horizontal = 10.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        // ── Auth section ───────────────────────────────────────────────
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                imageVector = if (authenticated) Icons.Filled.Person else Icons.Filled.PersonOff,
                contentDescription = null,
                tint = if (authenticated) OnlineColor else GuestColor,
                modifier = Modifier.size(14.dp),
            )
            Spacer(Modifier.width(5.dp))
            if (authenticated) {
                Text(
                    text = callsign.uppercase(),
                    color = TextColor,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.SemiBold,
                    fontFamily = FontFamily.Monospace,
                )
                if (!role.isNullOrBlank()) {
                    Text(
                        text = "  ·  ${role.uppercase()}",
                        color = TextColor.copy(alpha = 0.6f),
                        fontSize = 10.sp,
                        fontFamily = FontFamily.Monospace,
                    )
                }
            } else {
                Text(
                    text = "GUEST",
                    color = GuestColor,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.SemiBold,
                    fontFamily = FontFamily.Monospace,
                )
                Text(
                    text = "  ·  local only",
                    color = TextColor.copy(alpha = 0.5f),
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace,
                )
            }
        }

        // ── Server link section ───────────────────────────────────────
        Row(verticalAlignment = Alignment.CenterVertically) {
            // Coloured dot
            androidx.compose.foundation.Canvas(
                modifier = Modifier
                    .size(7.dp)
                    .clip(CircleShape),
            ) {
                drawCircle(if (isOnline) OnlineColor else OfflineColor)
            }
            Spacer(Modifier.width(5.dp))
            Icon(
                imageVector = if (isOnline) Icons.Filled.Cloud else Icons.Filled.CloudOff,
                contentDescription = null,
                tint = if (isOnline) OnlineColor else OfflineColor,
                modifier = Modifier.size(13.dp),
            )
            Spacer(Modifier.width(4.dp))
            Text(
                text = if (isOnline) "ONLINE" else "OFFLINE",
                color = if (isOnline) OnlineColor else OfflineColor,
                fontSize = 10.sp,
                fontWeight = FontWeight.SemiBold,
                fontFamily = FontFamily.Monospace,
            )
        }
    }
}
