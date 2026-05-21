package com.arrow.tactical.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Coarse form-factor classification. Mirrors Material 3's WindowSizeClass without pulling
 * in the extra dependency. Read once at the top of a Composable via [rememberWindowSize]
 * and branch UI density / max-widths / column counts on it.
 *
 *  - COMPACT  : phones in any orientation, < 600 dp wide
 *  - MEDIUM   : small tablets, large phones in landscape, 600 – 839 dp
 *  - EXPANDED : tablets and larger, ≥ 840 dp
 */
enum class WindowSize { COMPACT, MEDIUM, EXPANDED }

@Composable
@ReadOnlyComposable
fun rememberWindowSize(): WindowSize {
    val widthDp = LocalConfiguration.current.screenWidthDp.dp
    return when {
        widthDp < 600.dp -> WindowSize.COMPACT
        widthDp < 840.dp -> WindowSize.MEDIUM
        else             -> WindowSize.EXPANDED
    }
}

/** Pick one of three values based on the current [WindowSize]. */
@Composable
@ReadOnlyComposable
fun <T> byWindow(compact: T, medium: T, expanded: T): T = when (rememberWindowSize()) {
    WindowSize.COMPACT  -> compact
    WindowSize.MEDIUM   -> medium
    WindowSize.EXPANDED -> expanded
}

/** Convenience for picking dp values by form factor. */
@Composable
@ReadOnlyComposable
fun byWindowDp(compact: Dp, medium: Dp, expanded: Dp): Dp = byWindow(compact, medium, expanded)
