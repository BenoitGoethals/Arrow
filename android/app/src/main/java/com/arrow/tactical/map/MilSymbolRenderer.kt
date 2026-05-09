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

    // ── Own position (blue dot + callsign label) ────────────────────────────

    fun ownPosition(res: Resources, op: OperatorDto): Drawable {
        val dp    = res.displayMetrics.density
        val r     = 18 * dp          // circle radius
        val pad   = 4 * dp
        val textH = 13 * dp          // space reserved below circle for label
        val w     = ((r + pad) * 2).toInt()
        val h     = (r * 2 + pad * 2 + textH).toInt()
        val bmp   = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        val paint  = Paint(Paint.ANTI_ALIAS_FLAG)

        val cx = w / 2f
        val cy = pad + r             // circle centre

        // Outer glow ring (semi-transparent blue)
        paint.color = Color.argb(60, 37, 99, 235)
        paint.style = Paint.Style.FILL
        canvas.drawCircle(cx, cy, r + 4 * dp, paint)

        // Main blue dot
        paint.color = Color.rgb(37, 99, 235)   // #2563EB
        canvas.drawCircle(cx, cy, r, paint)

        // White border
        paint.color = Color.WHITE
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 3 * dp
        canvas.drawCircle(cx, cy, r, paint)

        // Inner dark-blue centre dot for depth
        paint.style = Paint.Style.FILL
        paint.color = Color.rgb(30, 64, 175)   // #1E40AF
        canvas.drawCircle(cx, cy, 5 * dp, paint)

        // Callsign label below circle — dark pill background
        val label = op.callsign.take(8)
        paint.textSize = 9 * dp
        paint.textAlign = Paint.Align.CENTER
        val textW = paint.measureText(label)
        val pillL = cx - textW / 2 - 4 * dp
        val pillR = cx + textW / 2 + 4 * dp
        val pillT = cy + r + 3 * dp
        val pillB = pillT + 11 * dp
        paint.color = Color.argb(200, 13, 17, 23)
        canvas.drawRoundRect(RectF(pillL, pillT, pillR, pillB), 4 * dp, 4 * dp, paint)

        // Label text
        paint.color = Color.rgb(147, 197, 253)  // #93C5FD light blue
        paint.isFakeBoldText = true
        canvas.drawText(label, cx, pillB - 3 * dp, paint)

        return BitmapDrawable(res, bmp)
    }

    // ── Friendly (NATO blue rectangle) ───────────────────────────────────────

    fun friendly(res: Resources, op: OperatorDto, isMe: Boolean = false): Drawable {
        if (isMe) return ownPosition(res, op)

        val dp = res.displayMetrics.density
        val w = (56 * dp).toInt()
        val h = (30 * dp).toInt()
        val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        val online = op.online
        val alpha = if (online) 255 else 110

        val inset = 3 * dp
        val frame = RectF(inset, inset, w - inset, h - inset)
        paint.color = Color.argb(alpha, 128, 224, 255)  // NATO light blue
        paint.style = Paint.Style.FILL
        canvas.drawRoundRect(frame, 4 * dp, 4 * dp, paint)

        paint.color = Color.argb(alpha, 0, 70, 180)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 2.5f * dp
        canvas.drawRoundRect(frame, 4 * dp, 4 * dp, paint)

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
        paint.isFakeBoldText = op.role != "OPERATOR"
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

    // ── Call for Fire / Fire Mission (red target crosshair) ──────────────────

    fun fireMission(res: Resources, missionType: String, status: String): Drawable {
        val dp    = res.displayMetrics.density
        val size  = (52 * dp).toInt()
        val bmp   = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        val paint  = Paint(Paint.ANTI_ALIAS_FLAG)

        val cx    = size / 2f
        val cy    = size / 2f
        val outer = cx - 2.5f * dp
        val inner = outer * 0.45f
        val alpha = when (status) {
            "COMPLETED", "CANCELLED" -> 80
            "IN_PROGRESS"            -> 200
            else                     -> 255
        }
        val baseColor = when (status) {
            "ACKNOWLEDGED" -> android.graphics.Color.argb(alpha, 0xD9, 0x77, 0x06)
            "IN_PROGRESS"  -> android.graphics.Color.argb(alpha, 0x25, 0x63, 0xEB)
            "COMPLETED"    -> android.graphics.Color.argb(alpha, 0x47, 0x55, 0x69)
            "CANCELLED"    -> android.graphics.Color.argb(alpha, 0x47, 0x55, 0x69)
            else           -> android.graphics.Color.argb(alpha, 0xDC, 0x26, 0x26) // PENDING — red
        }

        paint.color       = baseColor
        paint.style       = Paint.Style.STROKE
        paint.strokeWidth = 2.5f * dp

        // Outer target ring
        canvas.drawCircle(cx, cy, outer, paint)
        // Inner ring
        canvas.drawCircle(cx, cy, inner, paint)
        // Crosshairs
        canvas.drawLine(cx - outer, cy, cx - inner - 1 * dp, cy, paint)
        canvas.drawLine(cx + inner + 1 * dp, cy, cx + outer, cy, paint)
        canvas.drawLine(cx, cy - outer, cx, cy - inner - 1 * dp, paint)
        canvas.drawLine(cx, cy + inner + 1 * dp, cx, cy + outer, paint)

        // Mission type abbreviation in center
        val abbr = when (missionType) {
            "ADJUST_FIRE"           -> "AF"
            "FIRE_FOR_EFFECT"       -> "FFE"
            "SUPPRESSION"           -> "SUP"
            "ILLUMINATION"          -> "ILL"
            "IMMEDIATE_SUPPRESSION" -> "IM"
            else                    -> "CFF"
        }
        paint.style         = Paint.Style.FILL
        paint.textSize      = 9 * dp
        paint.textAlign     = Paint.Align.CENTER
        paint.isFakeBoldText = true
        canvas.drawText(abbr, cx, cy + 3.5f * dp, paint)

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
