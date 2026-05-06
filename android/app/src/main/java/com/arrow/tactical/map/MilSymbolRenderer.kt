package com.arrow.tactical.map

import android.content.res.Resources
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.drawable.BitmapDrawable
import android.graphics.drawable.Drawable
import com.arrow.tactical.network.OperatorDto
import com.arrow.tactical.tactical.EnemyType

/**
 * Renders NATO APP-6 / MIL-STD-2525C affiliation frames as Drawables for OSMdroid markers.
 *
 * Friendly  → blue rectangle  (ground units)
 * Hostile   → red diamond
 * POI       → yellow circle with cross-hair (neutral infrastructure)
 */
object MilSymbolRenderer {

    // ── Friendly (blue rectangle) ────────────────────────────────────────────

    fun friendly(res: Resources, op: OperatorDto, isMe: Boolean = false): Drawable {
        val dp = res.displayMetrics.density
        val w = (56 * dp).toInt()
        val h = (30 * dp).toInt()
        val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        val online = op.status == "ONLINE"
        val alpha = if (online) 255 else 110

        // Fill: brighter cyan for self, standard NATO blue for others
        val inset = if (isMe) 2 * dp else 3 * dp
        val frame = RectF(inset, inset, w - inset, h - inset)
        paint.color = if (isMe) Color.argb(alpha, 0, 220, 160)   // bright teal = self
                      else      Color.argb(alpha, 128, 224, 255)  // NATO light blue = others
        paint.style = Paint.Style.FILL
        canvas.drawRoundRect(frame, 4 * dp, 4 * dp, paint)

        // Stroke: thicker + brighter for self
        paint.color = if (isMe) Color.argb(alpha, 0, 120, 80)
                      else      Color.argb(alpha, 0, 70, 180)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = if (isMe) 3 * dp else 2.5f * dp
        canvas.drawRoundRect(frame, 4 * dp, 4 * dp, paint)

        // Small dot in top-left corner to mark own unit
        if (isMe) {
            paint.style = Paint.Style.FILL
            paint.color = Color.argb(alpha, 255, 255, 0)  // yellow self-indicator
            canvas.drawCircle(inset + 4 * dp, inset + 4 * dp, 3 * dp, paint)
        }

        // Role indicator line at top for BC/ADMIN
        if (op.role == "BATTLE_CAPTAIN" || op.role == "ADMIN") {
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = 3 * dp
            paint.color = Color.argb(alpha, 0, 40, 140)
            val topY = inset + 6 * dp
            canvas.drawLine(inset + 6 * dp, topY, w - inset - 6 * dp, topY, paint)
        }

        // Callsign text
        paint.style = Paint.Style.FILL
        paint.color = Color.argb(alpha, 0, 0, 0)
        paint.textSize = 8 * dp
        paint.textAlign = Paint.Align.CENTER
        paint.isFakeBoldText = isMe || op.role != "OPERATOR"
        canvas.drawText(op.callsign.take(9), w / 2f, h / 2f + 3 * dp, paint)

        return BitmapDrawable(res, bmp)
    }

    // ── Hostile (red diamond) ────────────────────────────────────────────────

    fun hostile(res: Resources, type: EnemyType): Drawable {
        val dp = res.displayMetrics.density
        val size = (38 * dp).toInt()
        val bmp = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)

        val cx = size / 2f
        val cy = size / 2f
        val r = cx - 3 * dp

        val diamond = Path().apply {
            moveTo(cx,     cy - r)   // top
            lineTo(cx + r, cy)       // right
            lineTo(cx,     cy + r)   // bottom
            lineTo(cx - r, cy)       // left
            close()
        }

        // Fill: NATO hostile red
        paint.color = Color.rgb(200, 0, 0)
        paint.style = Paint.Style.FILL
        canvas.drawPath(diamond, paint)

        // Stroke: darker red
        paint.color = Color.rgb(110, 0, 0)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 2.5f * dp
        canvas.drawPath(diamond, paint)

        // Abbreviation
        paint.style = Paint.Style.FILL
        paint.color = Color.WHITE
        paint.textSize = 8 * dp
        paint.textAlign = Paint.Align.CENTER
        paint.isFakeBoldText = true
        canvas.drawText(type.abbr, cx, cy + 3 * dp, paint)

        return BitmapDrawable(res, bmp)
    }

    // ── POI (yellow circle, neutral infrastructure) ──────────────────────────

    fun poi(res: Resources): Drawable {
        val dp = res.displayMetrics.density
        val size = (32 * dp).toInt()
        val bmp = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)

        val cx = size / 2f
        val cy = size / 2f
        val r = cx - 3 * dp

        // Fill: neutral yellow
        paint.color = Color.rgb(255, 200, 0)
        paint.style = Paint.Style.FILL
        canvas.drawCircle(cx, cy, r, paint)

        // Stroke: black
        paint.color = Color.BLACK
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 2.5f * dp
        canvas.drawCircle(cx, cy, r, paint)

        // Cross-hair (MIL-STD-2525 infrastructure point symbol)
        val arm = r * 0.42f
        paint.strokeWidth = 1.8f * dp
        canvas.drawLine(cx - arm, cy, cx + arm, cy, paint)
        canvas.drawLine(cx, cy - arm, cx, cy + arm, paint)
        canvas.drawCircle(cx, cy, arm * 0.45f, paint)

        return BitmapDrawable(res, bmp)
    }
}
