package com.arrow.tactical.map.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.spring
import androidx.compose.foundation.MutatePriority
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin

data class RadialItem(
    val icon:  String,
    val label: String,
    val color: Color,
    val action: () -> Unit,
)

/**
 * Full-screen radial (pie) menu centred at [tapOffset].
 * Items animate outward from the tap point using a spring.
 * Tapping the dimmed background calls [onDismiss].
 */
@Composable
fun RadialMenu(
    tapOffset: Offset,
    items:     List<RadialItem>,
    onDismiss: () -> Unit,
) {
    val scales  = remember { items.map { Animatable(0f) } }
    val scope   = rememberCoroutineScope()

    // Animate items springing outward
    LaunchedEffect(tapOffset) {
        items.indices.forEach { i ->
            scope.launch {
                scales[i].animateTo(1f, animationSpec = spring(
                    dampingRatio = 0.55f, stiffness = 400f,
                ))
            }
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.45f))
            .clickable(
                indication        = null,
                interactionSource = remember { MutableInteractionSource() },
            ) { onDismiss() },
    ) {
        // Tap-point indicator
        Box(
            modifier = Modifier
                .size(14.dp)
                .offset {
                    IntOffset(
                        (tapOffset.x - 7).roundToInt(),
                        (tapOffset.y - 7).roundToInt(),
                    )
                }
                .background(Color.White.copy(alpha = 0.9f), CircleShape),
        )

        val btnDp   = 54.dp
        val labelDp = 14.dp
        val radiusDp = 96.dp

        items.forEachIndexed { i, item ->
            val angleDeg = i * (360f / items.size) - 90f          // start at top
            val angleRad = Math.toRadians(angleDeg.toDouble())
            val scale    = scales[i].value

            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier
                    .offset {
                        val r = radiusDp.toPx() * scale
                        val bh = (btnDp.toPx() / 2).roundToInt()
                        val lh = (labelDp.toPx() / 2).roundToInt()
                        IntOffset(
                            (tapOffset.x + r * cos(angleRad)).roundToInt() - bh,
                            (tapOffset.y + r * sin(angleRad)).roundToInt() - bh - lh,
                        )
                    },
            ) {
                // Circle button
                Box(
                    modifier = Modifier
                        .size(btnDp)
                        .background(item.color, CircleShape)
                        .clickable(
                            indication        = null,
                            interactionSource = remember { MutableInteractionSource() },
                        ) { item.action() },
                    contentAlignment = Alignment.Center,
                ) {
                    Text(item.icon, fontSize = 22.sp)
                }
                Spacer(Modifier.height(3.dp))
                Text(
                    item.label,
                    fontSize    = 9.sp,
                    fontWeight  = FontWeight.Bold,
                    color       = Color.White,
                    textAlign   = TextAlign.Center,
                    lineHeight  = 10.sp,
                )
            }
        }
    }
}
