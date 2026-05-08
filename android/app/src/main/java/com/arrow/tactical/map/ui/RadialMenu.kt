package com.arrow.tactical.map.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.spring
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
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
    val icon:   String,
    val label:  String,
    val color:  Color,
    val action: () -> Unit,
)

/**
 * Radial menu with an outer ring and inner-circle hub.
 *
 * Layout (all centred on [tapOffset]):
 *   ┌──────────────────────────────┐
 *   │  outer ring  (r = 110 dp)   │  ← items sit on this ring
 *   │    mid ring  (r =  64 dp)   │  ← decorative separator
 *   │    inner hub (r =  26 dp)   │  ← filled centre dot
 *   └──────────────────────────────┘
 *
 * All three rings + items animate from 0 → 1 with a single spring so
 * the whole menu opens as one unit.  Spoke lines connect hub to each item.
 */
@Composable
fun RadialMenu(
    tapOffset: Offset,
    items:     List<RadialItem>,
    onDismiss: () -> Unit,
) {
    val progress = remember { Animatable(0f) }
    val scope    = rememberCoroutineScope()

    LaunchedEffect(tapOffset) {
        scope.launch {
            progress.animateTo(
                1f,
                animationSpec = spring(dampingRatio = 0.6f, stiffness = 380f),
            )
        }
    }

    // Geometry (dp values — converted to px inside the Canvas / offset blocks)
    val outerRadiusDp = 110.dp
    val midRadiusDp   =  64.dp
    val hubRadiusDp   =  26.dp
    val btnDp         =  52.dp
    val labelMaxDp    =  48.dp

    // Colours
    val ringColor  = Color.White.copy(alpha = 0.22f)
    val spokeColor = Color.White.copy(alpha = 0.12f)
    val hubFill    = Color(0xFF0D1117)          // app background
    val hubRing    = Color(0xFF6EE7B7)          // teal — primary colour

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.50f))
            .clickable(
                indication        = null,
                interactionSource = remember { MutableInteractionSource() },
            ) { onDismiss() },
    ) {

        // ── Rings + spokes drawn on a full-size canvas ────────────────────
        Canvas(modifier = Modifier.fillMaxSize()) {
            val p   = progress.value
            val cx  = tapOffset.x
            val cy  = tapOffset.y
            val out = outerRadiusDp.toPx() * p
            val mid = midRadiusDp.toPx()   * p
            val hub = hubRadiusDp.toPx()

            // Spoke lines from hub edge to outer ring (one per item)
            items.forEachIndexed { i, _ ->
                val angleDeg = i * (360f / items.size) - 90f
                val rad      = Math.toRadians(angleDeg.toDouble())
                drawLine(
                    color       = spokeColor.copy(alpha = spokeColor.alpha * p),
                    start       = Offset(
                        (cx + hub  * cos(rad)).toFloat(),
                        (cy + hub  * sin(rad)).toFloat(),
                    ),
                    end         = Offset(
                        (cx + out  * cos(rad)).toFloat(),
                        (cy + out  * sin(rad)).toFloat(),
                    ),
                    strokeWidth = 1.dp.toPx(),
                )
            }

            // Outer ring
            drawCircle(
                color  = ringColor.copy(alpha = ringColor.alpha * p),
                radius = out,
                center = Offset(cx, cy),
                style  = Stroke(width = 1.5.dp.toPx()),
            )

            // Mid ring (decorative separator)
            drawCircle(
                color  = ringColor.copy(alpha = ringColor.alpha * p * 0.6f),
                radius = mid,
                center = Offset(cx, cy),
                style  = Stroke(width = 1.dp.toPx()),
            )

            // Inner hub — filled
            drawCircle(
                color  = hubFill,
                radius = hub,
                center = Offset(cx, cy),
            )
            // Inner hub — teal ring
            drawCircle(
                color  = hubRing.copy(alpha = 0.85f),
                radius = hub,
                center = Offset(cx, cy),
                style  = Stroke(width = 1.5.dp.toPx()),
            )
        }

        // ── Items positioned on the outer ring ───────────────────────────
        items.forEachIndexed { i, item ->
            val angleDeg = i * (360f / items.size) - 90f
            val angleRad = Math.toRadians(angleDeg.toDouble())
            val p        = progress.value

            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier
                    .width(labelMaxDp)
                    .offset {
                        val r  = outerRadiusDp.toPx() * p
                        val bh = (btnDp.toPx() / 2).roundToInt()
                        val lw = labelMaxDp.toPx().roundToInt() / 2
                        IntOffset(
                            x = (tapOffset.x + r * cos(angleRad)).roundToInt() - bh,
                            y = (tapOffset.y + r * sin(angleRad)).roundToInt() - bh,
                        )
                    },
            ) {
                // Item button — sits on the ring
                Box(
                    modifier = Modifier
                        .size(btnDp)
                        .background(
                            item.color.copy(alpha = 0.15f + 0.70f * p),
                            CircleShape,
                        )
                        .clickable(
                            indication        = null,
                            interactionSource = remember { MutableInteractionSource() },
                        ) { item.action() },
                    contentAlignment = Alignment.Center,
                ) {
                    // Outer tinted ring on each button
                    Canvas(modifier = Modifier.fillMaxSize()) {
                        drawCircle(
                            color  = item.color.copy(alpha = 0.6f * p),
                            radius = size.minDimension / 2,
                            style  = Stroke(width = 1.5.dp.toPx()),
                        )
                    }
                    Text(
                        text     = item.icon,
                        fontSize = 22.sp,
                    )
                }
                Spacer(Modifier.height(4.dp))
                Text(
                    text      = item.label,
                    fontSize  = 9.sp,
                    fontWeight= FontWeight.Bold,
                    color     = Color.White.copy(alpha = p),
                    textAlign = TextAlign.Center,
                    lineHeight= 11.sp,
                    maxLines  = 2,
                )
            }
        }
    }
}
