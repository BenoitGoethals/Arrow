package com.arrow.tactical.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** User-selectable theme preference (persisted in SettingsRepository). */
enum class ThemeMode { SYSTEM, DARK, LIGHT }

// ── Tactical palette ────────────────────────────────────────────────────────
private val Teal = Color(0xFF6EE7B7)
private val TealDeep = Color(0xFF065F46)
private val Green = Color(0xFF34D399)
private val Amber = Color(0xFFD29922)
private val Red = Color(0xFFEF4444)

private val ArrowDark = darkColorScheme(
    primary = Teal,
    onPrimary = Color(0xFF00251A),
    primaryContainer = Color(0xFF0F3D31),
    onPrimaryContainer = Color(0xFFB6F5DD),
    secondary = Green,
    onSecondary = Color(0xFF00241A),
    secondaryContainer = Color(0xFF12352A),
    onSecondaryContainer = Color(0xFFB6F0D6),
    tertiary = Color(0xFF7CC4FF),
    onTertiary = Color(0xFF002A45),
    tertiaryContainer = Color(0xFF143A57),
    onTertiaryContainer = Color(0xFFCDE5FF),
    background = Color(0xFF0E1217),
    onBackground = Color(0xFFE2E8F0),
    surface = Color(0xFF161B25),
    onSurface = Color(0xFFE2E8F0),
    surfaceVariant = Color(0xFF1E2530),
    onSurfaceVariant = Color(0xFF9FB0C3),
    surfaceContainer = Color(0xFF131922),
    surfaceContainerHigh = Color(0xFF1C232E),
    outline = Color(0xFF334155),
    outlineVariant = Color(0xFF24303F),
    error = Red,
    onError = Color(0xFF3A0A0A),
    errorContainer = Color(0xFF4A1212),
    onErrorContainer = Color(0xFFFFD9D6),
    scrim = Color(0xCC000000),
)

private val ArrowLight = lightColorScheme(
    primary = TealDeep,
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFB6F5DD),
    onPrimaryContainer = Color(0xFF00271C),
    secondary = Color(0xFF047857),
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFBFF3DF),
    onSecondaryContainer = Color(0xFF00251A),
    tertiary = Color(0xFF1A5C8F),
    onTertiary = Color(0xFFFFFFFF),
    background = Color(0xFFF4F7FA),
    onBackground = Color(0xFF101820),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF101820),
    surfaceVariant = Color(0xFFE2E9F0),
    onSurfaceVariant = Color(0xFF44525F),
    outline = Color(0xFF8A98A6),
    outlineVariant = Color(0xFFC5D0DB),
    error = Color(0xFFB3261E),
    onError = Color(0xFFFFFFFF),
    scrim = Color(0x99000000),
)

@Composable
fun ArrowTheme(
    mode: ThemeMode = ThemeMode.SYSTEM,
    content: @Composable () -> Unit,
) {
    val dark = when (mode) {
        ThemeMode.SYSTEM -> isSystemInDarkTheme()
        ThemeMode.DARK -> true
        ThemeMode.LIGHT -> false
    }
    MaterialTheme(
        colorScheme = if (dark) ArrowDark else ArrowLight,
        typography = ArrowTypography,
        shapes = ArrowShapes,
        content = content,
    )
}
