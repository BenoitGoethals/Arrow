package com.arrow.tactical.map.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.CloudQueue
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.LocalFireDepartment
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.MyLocation
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material.icons.filled.Videocam
import androidx.compose.material.icons.filled.VideocamOff
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * SitaWare Edge-style chrome overlay for the tactical map.
 *
 * Layout (top to bottom, then anchored right):
 *   1. Top bar — hamburger · ARROW brand · Report Layer pill · MGRS · alerts · chat · status · overflow
 *   2. Notification banner — red alert strip with per-severity count chips (collapsible)
 *   3. Right-side FAB column — locate · zoom in · zoom out
 *
 * All callbacks are optional; pass no-op lambdas where not yet wired.
 */
object SitawareChromeColors {
    val BarBg          = Color(0xFF0F2540)
    val Brand          = Color(0xFFE2E8F0)
    val LocationLabel  = Color(0xFFA9C3DF)
    val LocationValue  = Color(0xFF9BE0FF)
    val IconTint       = Color(0xFFCBD5E1)
    val StatusOk       = Color(0xFF22C55E)
    val BannerBg       = Color(0xFFFFFFFF)
    val BannerAlertBg  = Color(0xFFC0392B)
    val BannerAlertFg  = Color.White
    val BannerText     = Color(0xFF1F2937)
    val ChipGrey       = Color(0xFF6B7280)
    val ChipBlue       = Color(0xFF2D7FB8)
    val ChipYellow     = Color(0xFFD4A017)
    val ChipRed        = Color(0xFFC0392B)
    val FabBg          = Color(0xFF0F2540)
    val FabFg          = Color(0xFFCBD5E1)
}

data class NotificationCounts(
    val info: Int = 0,
    val routine: Int = 0,
    val warning: Int = 0,
    val critical: Int = 0,
) {
    val total: Int get() = info + routine + warning + critical
}

data class OverlayChip(val key: String, val label: String, val selected: Boolean = false, val accent: Color = Color(0xFF34D399))

@Composable
fun SitawareTopBar(
    modifier: Modifier = Modifier,
    brand: String = "ARROW",
    mgrs: String = "—",
    onMenu: () -> Unit = {},
    alertCount: Int = 0,
    onAlerts: () -> Unit = {},
    chatCount: Int = 0,
    onChat: () -> Unit = {},
    online: Boolean = true,
    onStatus: () -> Unit = {},
    onOverflow: () -> Unit = {},
    overlayChips: List<OverlayChip> = emptyList(),
    onOverlayChip: (String) -> Unit = {},
    gfxOn: Boolean = false,
    onToggleGfx: () -> Unit = {},
    cbrnOn: Boolean = false,
    onToggleCbrn: () -> Unit = {},
    /** Open count of KML layers currently visible — drives the KML chip badge. */
    kmlActiveCount: Int = 0,
    onToggleKml: () -> Unit = {},
    /** Active saved-overlay count — drives the Overlays chip badge. */
    overlayActiveCount: Int = 0,
    onToggleOverlays: () -> Unit = {},
    isStreaming: Boolean = false,
    onToggleStream: () -> Unit = {},
    onLocateMe: () -> Unit = {},
    /** When non-null, renders a chevron-left button at the far right that
     *  collapses the bar. The MapScreen owns the collapse state. */
    onCollapseBar: (() -> Unit)? = null,
) {
    val c = SitawareChromeColors
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(c.BarBg)
            .padding(horizontal = 6.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        IconButton(onClick = onMenu, modifier = Modifier.size(36.dp)) {
            Icon(Icons.Filled.Menu, contentDescription = "Menu",
                 tint = c.IconTint, modifier = Modifier.size(22.dp))
        }
        // Collapse-to-left button — placed early so it stays visible even when
        // the bar's trailing icons get clipped off a narrow screen. Only
        // rendered when the parent wires the callback.
        onCollapseBar?.let { cb ->
            IconButton(onClick = cb, modifier = Modifier.size(32.dp)) {
                Icon(Icons.Filled.ChevronLeft, contentDescription = "Collapse menu",
                     tint = c.IconTint, modifier = Modifier.size(22.dp))
            }
        }
        Text(
            text = brand,
            color = c.Brand,
            fontWeight = FontWeight.Black,
            fontSize = 18.sp,
            letterSpacing = 1.5.sp,
            modifier = Modifier.padding(horizontal = 2.dp),
        )

        // Overlay-mode chips inline — All / None / Enemy / Own Plt
        overlayChips.forEach { chip ->
            Box(
                Modifier
                    .clickable { onOverlayChip(chip.key) }
                    .background(
                        if (chip.selected) chip.accent.copy(alpha = 0.18f) else Color(0xFF12233A),
                        RoundedCornerShape(4.dp),
                    )
                    .border(0.5.dp,
                            if (chip.selected) chip.accent else Color(0xFF2A3142),
                            RoundedCornerShape(4.dp))
                    .padding(horizontal = 7.dp, vertical = 3.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(chip.label, fontSize = 11.sp, fontWeight = FontWeight.SemiBold,
                     color = if (chip.selected) chip.accent else Color(0xFFCBD5E1))
            }
        }
        // Gfx toggle
        Box(
            Modifier
                .clickable { onToggleGfx() }
                .background(if (gfxOn) Color(0x33F59E0B) else Color(0xFF12233A),
                            RoundedCornerShape(4.dp))
                .border(0.5.dp, if (gfxOn) Color(0xFFF59E0B) else Color(0xFF2A3142),
                        RoundedCornerShape(4.dp))
                .padding(horizontal = 7.dp, vertical = 3.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text("Gfx", fontSize = 11.sp, fontWeight = FontWeight.SemiBold,
                 color = if (gfxOn) Color(0xFFFBBF24) else Color(0xFFCBD5E1))
        }
        // CBRN toggle — radiation/hazard layer
        Box(
            Modifier
                .clickable { onToggleCbrn() }
                .background(if (cbrnOn) Color(0x33EF4444) else Color(0xFF12233A),
                            RoundedCornerShape(4.dp))
                .border(0.5.dp, if (cbrnOn) Color(0xFFEF4444) else Color(0xFF2A3142),
                        RoundedCornerShape(4.dp))
                .padding(horizontal = 7.dp, vertical = 3.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text("☢ CBRN", fontSize = 11.sp, fontWeight = FontWeight.SemiBold,
                 color = if (cbrnOn) Color(0xFFFCA5A5) else Color(0xFFCBD5E1))
        }
        // KML layers — chip opens the layer panel; label shows live-count when >0.
        val kmlOn = kmlActiveCount > 0
        Box(
            Modifier
                .clickable { onToggleKml() }
                .background(if (kmlOn) Color(0x3322D3EE) else Color(0xFF12233A),
                            RoundedCornerShape(4.dp))
                .border(0.5.dp, if (kmlOn) Color(0xFF22D3EE) else Color(0xFF2A3142),
                        RoundedCornerShape(4.dp))
                .padding(horizontal = 7.dp, vertical = 3.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = if (kmlOn) "KML · $kmlActiveCount" else "KML",
                fontSize = 11.sp, fontWeight = FontWeight.SemiBold,
                color = if (kmlOn) Color(0xFF67E8F9) else Color(0xFFCBD5E1),
            )
        }
        // Saved overlays — chip opens the overlay panel; label shows live-count when >0.
        val ovOn = overlayActiveCount > 0
        Box(
            Modifier
                .clickable { onToggleOverlays() }
                .background(if (ovOn) Color(0x33A78BFA) else Color(0xFF12233A),
                            RoundedCornerShape(4.dp))
                .border(0.5.dp, if (ovOn) Color(0xFFA78BFA) else Color(0xFF2A3142),
                        RoundedCornerShape(4.dp))
                .padding(horizontal = 7.dp, vertical = 3.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = if (ovOn) "Ovl · $overlayActiveCount" else "Ovl",
                fontSize = 11.sp, fontWeight = FontWeight.SemiBold,
                color = if (ovOn) Color(0xFFC4B5FD) else Color(0xFFCBD5E1),
            )
        }
        // Stream toggle
        IconButton(onClick = onToggleStream, modifier = Modifier.size(32.dp)) {
            Icon(
                if (isStreaming) Icons.Filled.VideocamOff else Icons.Filled.Videocam,
                contentDescription = "Stream",
                tint = if (isStreaming) Color(0xFFEF4444) else c.IconTint,
                modifier = Modifier.size(20.dp),
            )
        }
        // Locate me
        IconButton(onClick = onLocateMe, modifier = Modifier.size(32.dp)) {
            Icon(Icons.Filled.MyLocation, contentDescription = "Locate me",
                 tint = c.IconTint, modifier = Modifier.size(20.dp))
        }

        Spacer(Modifier.weight(1f))

        // LOCATION block
        Column(horizontalAlignment = Alignment.End) {
            Text("LOCATION", color = c.LocationLabel,
                 fontSize = 9.sp, letterSpacing = 1.5.sp, fontWeight = FontWeight.Bold)
            Text(mgrs, color = c.LocationValue,
                 fontFamily = FontFamily.Monospace,
                 fontSize = 13.sp, fontWeight = FontWeight.Bold)
        }

        Spacer(Modifier.weight(1f))

        // Alerts (fire) — circle icon with optional badge
        BadgedIcon(
            icon = Icons.Filled.LocalFireDepartment,
            tint = Color(0xFFFB7185),
            count = alertCount,
            badgeColor = Color(0xFFEF4444),
            contentDescription = "Alerts",
            onClick = onAlerts,
        )

        // Chat with badge
        BadgedIcon(
            icon = Icons.AutoMirrored.Filled.Chat,
            tint = c.IconTint,
            count = chatCount,
            badgeColor = Color(0xFFF97316),
            contentDescription = "Chat",
            onClick = onChat,
        )

        // Status check — green when online
        IconButton(onClick = onStatus, modifier = Modifier.size(36.dp)) {
            Box(
                Modifier
                    .size(26.dp)
                    .clip(CircleShape)
                    .background(if (online) c.StatusOk else Color(0xFF6B7280)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Filled.Check, contentDescription = "Status",
                     tint = Color.White, modifier = Modifier.size(18.dp))
            }
        }

        IconButton(onClick = onOverflow, modifier = Modifier.size(32.dp)) {
            Icon(Icons.Filled.MoreVert, contentDescription = "More",
                 tint = c.IconTint, modifier = Modifier.size(22.dp))
        }
    }
}

/**
 * Small floating chevron shown when the top bar is collapsed; tapping it
 * restores the bar. Designed to be placed at top-left via Alignment.TopStart.
 */
@Composable
fun SitawareCollapsedHandle(
    onExpand: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val c = SitawareChromeColors
    Box(
        modifier = modifier
            .padding(start = 6.dp, top = 6.dp)
            .background(c.BarBg, RoundedCornerShape(6.dp))
            .border(0.5.dp, Color(0xFF2A3142), RoundedCornerShape(6.dp))
            .clickable { onExpand() }
            .padding(horizontal = 6.dp, vertical = 4.dp),
        contentAlignment = Alignment.Center,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Filled.Menu, contentDescription = "Show menu",
                 tint = c.IconTint, modifier = Modifier.size(18.dp))
            Icon(Icons.Filled.ChevronRight, contentDescription = null,
                 tint = c.IconTint, modifier = Modifier.size(16.dp))
        }
    }
}

@Composable
private fun BadgedIcon(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    tint: Color,
    count: Int,
    badgeColor: Color,
    contentDescription: String,
    onClick: () -> Unit,
) {
    Box(
        Modifier
            .size(40.dp)
            .clickable { onClick() },
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, contentDescription = contentDescription,
             tint = tint, modifier = Modifier.size(24.dp))
        if (count > 0) {
            Box(
                Modifier
                    .align(Alignment.TopEnd)
                    .offset(x = (-2).dp, y = 2.dp)
                    .background(badgeColor, CircleShape)
                    .padding(horizontal = 5.dp, vertical = 1.dp),
            ) {
                Text(
                    text = if (count > 99) "99+" else count.toString(),
                    color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold,
                )
            }
        }
    }
}

@Composable
fun SitawareNotificationBanner(
    counts: NotificationCounts,
    onExpand: () -> Unit = {},
    onDismiss: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    if (counts.total == 0) return
    val c = SitawareChromeColors
    var expanded by remember { mutableStateOf(false) }
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(c.BannerBg)
            .border(0.5.dp, Color(0xFFE5E7EB)),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier
                .size(40.dp)
                .background(c.BannerAlertBg),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Filled.Warning, contentDescription = null,
                 tint = c.BannerAlertFg, modifier = Modifier.size(22.dp))
        }
        Text(
            "You have ${counts.total} new notification${if (counts.total == 1) "" else "s"}",
            color = c.BannerText,
            fontSize = 13.sp,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(horizontal = 10.dp).weight(1f),
        )
        // Severity chips — only show non-zero counts
        if (counts.routine > 0) CountChip(counts.routine, c.ChipGrey)
        if (counts.info    > 0) CountChip(counts.info,    c.ChipBlue)
        if (counts.warning > 0) CountChip(counts.warning, c.ChipYellow)
        if (counts.critical > 0) CountChip(counts.critical, c.ChipRed)
        IconButton(onClick = { expanded = !expanded; onExpand() },
                   modifier = Modifier.size(36.dp)) {
            Icon(
                if (expanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                contentDescription = "Expand", tint = Color(0xFF6B7280),
            )
        }
        IconButton(onClick = onDismiss, modifier = Modifier.size(36.dp)) {
            Icon(Icons.Filled.Check, contentDescription = "Dismiss",
                 tint = Color(0xFF6B7280), modifier = Modifier.size(18.dp))
        }
    }
}

@Composable
private fun CountChip(count: Int, color: Color) {
    Box(
        Modifier
            .padding(horizontal = 3.dp)
            .size(26.dp)
            .clip(CircleShape)
            .background(color),
        contentAlignment = Alignment.Center,
    ) {
        Text(count.toString(), color = Color.White,
             fontSize = 13.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable
fun SitawareSideFabs(
    onLocate: () -> Unit,
    onZoomIn: () -> Unit,
    onZoomOut: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val c = SitawareChromeColors
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        SideFab(onLocate, Icons.Filled.MyLocation, "Locate me")
        SideFab(onZoomIn,  Icons.Filled.Add,        "Zoom in")
        SideFab(onZoomOut, Icons.Filled.Remove,     "Zoom out")
    }
}

@Composable
private fun SideFab(
    onClick: () -> Unit,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    contentDescription: String,
) {
    Box(
        Modifier
            .size(48.dp)
            .clip(CircleShape)
            .background(SitawareChromeColors.FabBg)
            .border(1.dp, Color(0xFF1B3A5B), CircleShape)
            .clickable { onClick() },
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, contentDescription = contentDescription,
             tint = SitawareChromeColors.FabFg, modifier = Modifier.size(22.dp))
    }
}
