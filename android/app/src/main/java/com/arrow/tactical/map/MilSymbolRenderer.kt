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

    // ── Own position (blue arrow + callsign label) ──────────────────────────

    fun ownPosition(res: Resources, op: OperatorDto): Drawable {
        val dp    = res.displayMetrics.density
        val halfW = 14 * dp          // arrow half-width
        val halfH = 18 * dp          // arrow half-height (tip to tail)
        val pad   = 4 * dp
        val textH = 13 * dp
        val w     = ((halfW + pad) * 2).toInt()
        val h     = (halfH * 2 + pad * 2 + textH).toInt()
        val bmp   = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        val paint  = Paint(Paint.ANTI_ALIAS_FLAG)

        val cx = w / 2f
        val cy = pad + halfH         // arrow centre

        // Arrow points up (north). Notch at the tail makes a chevron.
        val arrow = Path().apply {
            moveTo(cx,           cy - halfH)               // tip
            lineTo(cx + halfW,   cy + halfH)               // bottom-right
            lineTo(cx,           cy + halfH * 0.45f)       // tail notch
            lineTo(cx - halfW,   cy + halfH)               // bottom-left
            close()
        }

        // Fill: bright blue
        paint.color = Color.rgb(37, 99, 235)   // #2563EB
        paint.style = Paint.Style.FILL
        canvas.drawPath(arrow, paint)

        // White border
        paint.color = Color.WHITE
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 2.5f * dp
        paint.strokeJoin = Paint.Join.ROUND
        canvas.drawPath(arrow, paint)

        // Callsign label below arrow — dark pill background
        val label = op.callsign.take(8)
        paint.style = Paint.Style.FILL
        paint.strokeWidth = 0f
        paint.textSize = 9 * dp
        paint.textAlign = Paint.Align.CENTER
        val textW = paint.measureText(label)
        val pillL = cx - textW / 2 - 4 * dp
        val pillR = cx + textW / 2 + 4 * dp
        val pillT = cy + halfH + 3 * dp
        val pillB = pillT + 11 * dp
        paint.color = Color.argb(200, 13, 17, 23)
        canvas.drawRoundRect(RectF(pillL, pillT, pillR, pillB), 4 * dp, 4 * dp, paint)

        paint.color = Color.rgb(147, 197, 253)  // #93C5FD light blue
        paint.isFakeBoldText = true
        canvas.drawText(label, cx, pillB - 3 * dp, paint)

        return BitmapDrawable(res, bmp)
    }

    // ── Friendly (NATO blue rectangle) ───────────────────────────────────────

    fun friendly(res: Resources, op: OperatorDto, isMe: Boolean = false): Drawable {
        if (isMe) return ownPosition(res, op)

        val dp = res.displayMetrics.density
        val r  = 5 * dp                          // small dot radius
        val pad = 2 * dp
        val size = ((r + pad) * 2).toInt()
        val bmp = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        val alpha = if (op.online) 255 else 110

        val cx = size / 2f
        val cy = size / 2f

        // Blue dot
        paint.color = Color.argb(alpha, 37, 99, 235)   // #2563EB
        paint.style = Paint.Style.FILL
        canvas.drawCircle(cx, cy, r, paint)

        // Thin white outline for contrast on map
        paint.color = Color.argb(alpha, 255, 255, 255)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 1.5f * dp
        canvas.drawCircle(cx, cy, r, paint)

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

    // ── Objective (green flag, friendly task graphic) ────────────────────────

    fun objective(res: Resources): Drawable {
        val dp   = res.displayMetrics.density
        val w    = (30 * dp).toInt()
        val h    = (34 * dp).toInt()
        val bmp  = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        val paint  = Paint(Paint.ANTI_ALIAS_FLAG)

        // Pole
        val poleX = 6 * dp
        paint.color = Color.rgb(20, 20, 20)
        paint.style = Paint.Style.FILL
        canvas.drawRect(poleX - 1.5f * dp, 2 * dp, poleX + 1.5f * dp, h - 2 * dp, paint)

        // Flag triangle (green, points right, then back)
        val flag = Path().apply {
            moveTo(poleX,            3 * dp)
            lineTo(w - 3 * dp,       9 * dp)
            lineTo(poleX,            15 * dp)
            close()
        }
        paint.color = Color.rgb(22, 163, 74)   // #16A34A
        canvas.drawPath(flag, paint)

        paint.color = Color.rgb(6, 95, 40)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 1.5f * dp
        canvas.drawPath(flag, paint)

        // Base disc at pole foot
        paint.style = Paint.Style.FILL
        paint.color = Color.rgb(22, 163, 74)
        canvas.drawCircle(poleX, h - 4 * dp, 3 * dp, paint)
        paint.color = Color.WHITE
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 1f * dp
        canvas.drawCircle(poleX, h - 4 * dp, 3 * dp, paint)

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
