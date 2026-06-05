package com.arrow.tactical.map.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.spring
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
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
 * Radial action menu centred on [tapOffset].
 *
 * Visual layers (bottom → top):
 *  1. Full-screen dimmed scrim — tap anywhere outside buttons to dismiss.
 *  2. Canvas: arc sectors (pizza slices), rings, spokes, hub.
 *  3. Compose: item buttons on outer ring + label badges below each button.
 *  4. Compose: hub "✕" dismiss hint.
 *
 * All layers animate together via a single spring [progress] value.
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
            progress.animateTo(1f, animationSpec = spring(dampingRatio = 0.55f, stiffness = 360f))
        }
    }

    // ── Geometry constants ────────────────────────────────────────────────────
    val outerRDp   = 132.dp     // item centres sit here
    val innerArcDp =  70.dp     // inner edge of arc sectors
    val hubRDp     =  30.dp     // hub circle radius
    val btnDp      =  62.dp     // item button diameter
    val labelMaxDp =  56.dp     // max width of label column

    // ── Palette ───────────────────────────────────────────────────────────────
    val ringColor  = Color.White.copy(alpha = 0.18f)
    val spokeColor = Color.White.copy(alpha = 0.09f)
    val hubFill    = Color(0xFF0D1117)
    val hubRing    = Color(0xFF6EE7B7)

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.48f))
            .clickable(
                indication        = null,
                interactionSource = remember { MutableInteractionSource() },
            ) { onDismiss() },
    ) {

        // ── 1. Canvas: arcs, rings, spokes, hub ──────────────────────────────
        Canvas(modifier = Modifier.fillMaxSize()) {
            val p    = progress.value
            val cx   = tapOffset.x
            val cy   = tapOffset.y
            val outr = outerRDp.toPx()   * p
            val innr = innerArcDp.toPx() * p
            val hub  = hubRDp.toPx()
            val n    = items.size.coerceAtLeast(1)
            val sectorSweep = 360f / n - 6f   // 6° gap between sectors

            // Arc sectors (coloured pizza slices between inner and outer rings)
            if (outr > innr && innr > 0f) {
                val arcR = (outr + innr) / 2f
                val arcW = (outr - innr)
                items.forEachIndexed { i, item ->
                    val startDeg = i * (360f / n) - 90f - sectorSweep / 2f
                    // Filled sector body
                    drawArc(
                        color      = item.color.copy(alpha = 0.20f * p),
                        startAngle = startDeg,
                        sweepAngle = sectorSweep,
                        useCenter  = false,
                        topLeft    = Offset(cx - arcR, cy - arcR),
                        size       = Size(arcR * 2, arcR * 2),
                        style      = Stroke(width = arcW, cap = StrokeCap.Butt),
                    )
                    // Bright outer-edge arc
                    drawArc(
                        color      = item.color.copy(alpha = 0.60f * p),
                        startAngle = startDeg,
                        sweepAngle = sectorSweep,
                        useCenter  = false,
                        topLeft    = Offset(cx - outr, cy - outr),
                        size       = Size(outr * 2, outr * 2),
                        style      = Stroke(width = 2.dp.toPx(), cap = StrokeCap.Butt),
                    )
                }
            }

            // Outer ring
            drawCircle(
                color  = ringColor.copy(alpha = ringColor.alpha * p),
                radius = outr,
                center = Offset(cx, cy),
                style  = Stroke(width = 1.5.dp.toPx()),
            )
            // Inner arc ring
            drawCircle(
                color  = ringColor.copy(alpha = ringColor.alpha * 0.50f * p),
                radius = innr,
                center = Offset(cx, cy),
                style  = Stroke(width = 1.dp.toPx()),
            )

            // Spoke lines: hub edge → outer ring
            items.forEachIndexed { i, _ ->
                val rad = Math.toRadians((i * 360.0 / n) - 90.0)
                drawLine(
                    color       = spokeColor.copy(alpha = spokeColor.alpha * p),
                    start       = Offset((cx + hub * cos(rad)).toFloat(), (cy + hub * sin(rad)).toFloat()),
                    end         = Offset((cx + outr * cos(rad)).toFloat(), (cy + outr * sin(rad)).toFloat()),
                    strokeWidth = 1.dp.toPx(),
                )
            }

            // Hub glow
            drawCircle(
                color  = hubRing.copy(alpha = 0.18f * p),
                radius = hub * 1.65f,
                center = Offset(cx, cy),
            )
            // Hub fill
            drawCircle(color = hubFill, radius = hub, center = Offset(cx, cy))
            // Hub border
            drawCircle(
                color  = hubRing.copy(alpha = 0.90f),
                radius = hub,
                center = Offset(cx, cy),
                style  = Stroke(width = 2.dp.toPx()),
            )
        }

        // ── 2. Hub "✕" dismiss label ─────────────────────────────────────────
        val hubPx = hubRDp
        Box(
            modifier = Modifier
                .offset {
                    IntOffset(
                        x = tapOffset.x.roundToInt() - hubPx.roundToPx(),
                        y = tapOffset.y.roundToInt() - hubPx.roundToPx(),
                    )
                }
                .size(hubPx * 2),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text       = "✕",
                color      = hubRing.copy(alpha = progress.value * 0.75f),
                fontSize   = 13.sp,
                fontWeight = FontWeight.Bold,
            )
        }

        // ── 3. Item buttons ───────────────────────────────────────────────────
        items.forEachIndexed { i, item ->
            val angleDeg = i * (360.0 / items.size) - 90.0
            val angleRad = Math.toRadians(angleDeg)
            val p        = progress.value

            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier
                    .width(labelMaxDp)
                    .offset {
                        val r  = outerRDp.toPx() * p
                        val bh = (btnDp.toPx() / 2).roundToInt()
                        IntOffset(
                            x = (tapOffset.x + r * cos(angleRad)).roundToInt() - bh,
                            y = (tapOffset.y + r * sin(angleRad)).roundToInt() - bh,
                        )
                    },
            ) {
                // Button circle
                Box(
                    modifier = Modifier
                        .size(btnDp)
                        .background(item.color.copy(alpha = (0.15f + 0.70f * p).coerceIn(0f, 1f)), CircleShape)
                        .clickable(
                            indication        = null,
                            interactionSource = remember { MutableInteractionSource() },
                        ) { item.action() },
                    contentAlignment = Alignment.Center,
                ) {
                    // White inner ring highlight
                    Canvas(modifier = Modifier.fillMaxSize()) {
                        drawCircle(
                            color  = Color.White.copy(alpha = 0.28f * p),
                            radius = size.minDimension / 2,
                            style  = Stroke(width = 1.5.dp.toPx()),
                        )
                    }
                    Text(
                        text     = item.icon,
                        fontSize = 26.sp,
                    )
                }

                Spacer(Modifier.height(5.dp))

                // Label badge
                Box(
                    modifier = Modifier
                        .background(
                            Color.Black.copy(alpha = 0.60f * p),
                            RoundedCornerShape(4.dp),
                        )
                        .padding(horizontal = 5.dp, vertical = 2.dp),
                ) {
                    Text(
                        text       = item.label,
                        fontSize   = 10.sp,
                        fontWeight = FontWeight.SemiBold,
                        color      = Color.White.copy(alpha = p),
                        textAlign  = TextAlign.Center,
                        lineHeight = 12.sp,
                        maxLines   = 2,
                    )
                }
            }
        }
    }
}
