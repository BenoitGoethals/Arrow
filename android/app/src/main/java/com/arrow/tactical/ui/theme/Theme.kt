package com.arrow.tactical.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val TacticalDark = darkColorScheme(
    primary = Color(0xFF6EE7B7),
    secondary = Color(0xFF34D399),
    background = Color(0xFF0E1217),
    surface = Color(0xFF161B25),
    error = Color(0xFFEF4444),
)

private val TacticalLight = lightColorScheme(
    primary = Color(0xFF065F46),
    secondary = Color(0xFF047857),
)

@Composable
fun ArrowTheme(content: @Composable () -> Unit) {
    val scheme = if (isSystemInDarkTheme()) TacticalDark else TacticalLight
    MaterialTheme(colorScheme = scheme, content = content)
}
