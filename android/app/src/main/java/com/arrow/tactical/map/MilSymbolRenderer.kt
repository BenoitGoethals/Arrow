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

    // ── MIL-STD-2525C affiliation palette ───────────────────────────────────
    //
    // Doctrinal "light" fill colours (medium-saturation, suitable for daylight
    // mono displays). Black 1-px frame outline on every affiliation.
    private val FRAME_FRIENDLY_FILL = Color.rgb(0x80, 0xE0, 0xFF)   // cyan
    private val FRAME_HOSTILE_FILL  = Color.rgb(0xFF, 0x80, 0x80)   // light red
    private val FRAME_NEUTRAL_FILL  = Color.rgb(0xAA, 0xFF, 0xAA)   // light green
    private val FRAME_UNKNOWN_FILL  = Color.rgb(0xFF, 0xFF, 0x80)   // light yellow
    private val FRAME_BORDER        = Color.rgb(0x0D, 0x11, 0x17)   // near-black

    // ── Friendly (MIL-STD-2525 ground unit — cyan rectangle) ────────────────

    /**
     * Renders a MIL-STD-2525C/APP-6 friendly ground-unit symbol:
     *
     *     ┌──────────┐
     *     │  ╲ ╱     │  CALLSIGN
     *     │  ╱ ╲     │
     *     └──────────┘
     *
     * Cyan-filled rectangle with a black frame, infantry "X" glyph inside (or
     * an HQ flag-staff for battle captains), and the operator's callsign as
     * the unit designator (field "T") placed to the right of the frame —
     * exactly how milsymbol.js renders ``SFGPUCI------`` with
     * ``uniqueDesignation`` on the web.
     */
    fun friendly(res: Resources, op: OperatorDto, isMe: Boolean = false): Drawable {
        if (isMe) return ownPosition(res, op)

        val dp = res.displayMetrics.density
        // Frame proportions per MIL-STD-2525C — ground-unit width ≈ 1.44 × height.
        val frameH = 20 * dp
        val frameW = 28 * dp
        val pad    = 1.5f * dp
        // Right-hand designator (callsign) sits outside the frame, like milsymbol.
        val txtSize = 10 * dp
        val txtPad  = 3 * dp
        val paint   = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            textSize = txtSize; isFakeBoldText = true
        }
        val label   = op.callsign.take(12)
        val textW   = if (label.isNotEmpty()) paint.measureText(label) + txtPad else 0f

        // Pad the LEFT side by the same amount as the right-hand callsign label
        // so the frame ends up at the centre of the bitmap. That lets the
        // marker stay anchored CENTER/CENTER without drifting with callsign length.
        val w = (textW + pad + frameW + textW + pad).toInt().coerceAtLeast(1)
        val h = (pad + frameH + pad).toInt().coerceAtLeast(1)
        val bmp    = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        val alpha  = if (op.online) 255 else 130

        val left   = textW + pad
        val top    = pad
        val right  = left + frameW
        val bottom = top + frameH
        val rect   = RectF(left, top, right, bottom)
        val borderCol = applyAlpha(FRAME_BORDER, alpha)

        // 1) Frame fill — cyan
        paint.color = applyAlpha(FRAME_FRIENDLY_FILL, alpha)
        paint.style = Paint.Style.FILL
        canvas.drawRect(rect, paint)

        // 2) Frame border — black
        paint.color = borderCol
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 1.6f * dp
        canvas.drawRect(rect, paint)

        // 3) Function-modifier glyph inside the inner area
        val inset = 3 * dp
        val inner = RectF(left + inset, top + inset, right - inset, bottom - inset)
        if (op.role.equals("BATTLE_CAPTAIN", ignoreCase = true)) {
            drawHqGlyph(canvas, inner, paint, borderCol, dp)
        } else {
            drawInfantryGlyph(canvas, inner, paint, borderCol, dp)
        }

        // 4) Callsign — placed outside, to the right of the frame (MIL-STD-2525
        //    field "T"). Black halo + light-blue text for legibility on map.
        if (label.isNotEmpty()) {
            val tx = right + txtPad
            // Baseline-centred on the frame middle
            val fm = paint.fontMetrics
            val ty = (top + bottom) / 2f - (fm.ascent + fm.descent) / 2f
            paint.style = Paint.Style.FILL
            paint.textAlign = Paint.Align.LEFT
            // Black halo (4-way offsets) for contrast on light map tiles
            paint.color = applyAlpha(Color.BLACK, alpha)
            for ((ox, oy) in listOf(-1f to 0f, 1f to 0f, 0f to -1f, 0f to 1f)) {
                canvas.drawText(label, tx + ox * dp, ty + oy * dp, paint)
            }
            paint.color = applyAlpha(Color.rgb(191, 219, 254), alpha)   // #BFDBFE
            canvas.drawText(label, tx, ty, paint)
        }

        return BitmapDrawable(res, bmp)
    }

    // ── Hostile (MIL-STD-2525 ground unit — red diamond) ────────────────────

    fun hostile(res: Resources, type: EnemyType): Drawable {
        val dp = res.displayMetrics.density
        // Larger frame so the inscribed function-modifier glyph is readable.
        val size = (48 * dp).toInt()
        val bmp = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)

        val cx = size / 2f
        val cy = size / 2f
        val r  = cx - 4 * dp                 // diamond half-diagonal

        val diamond = Path().apply {
            moveTo(cx,     cy - r)
            lineTo(cx + r, cy)
            lineTo(cx,     cy + r)
            lineTo(cx - r, cy)
            close()
        }

        // 1) Fill — light hostile red (#FF8080)
        paint.color = FRAME_HOSTILE_FILL
        paint.style = Paint.Style.FILL
        canvas.drawPath(diamond, paint)

        // 2) Frame border — black
        paint.color = FRAME_BORDER
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 1.6f * dp
        canvas.drawPath(diamond, paint)

        // 3) Inscribed function-modifier glyph. Inner square is half-diagonal × √2,
        //    shrunk slightly so the glyph sits clear of the diamond edges.
        val inscribed = (r * 0.62f)
        val inner = RectF(cx - inscribed, cy - inscribed, cx + inscribed, cy + inscribed)
        drawHostileGlyph(canvas, inner, paint, FRAME_BORDER, dp, type)

        return BitmapDrawable(res, bmp)
    }

    private fun applyAlpha(color: Int, alpha: Int): Int =
        Color.argb(alpha, Color.red(color), Color.green(color), Color.blue(color))

    // ── APP-6 function-modifier glyphs ──────────────────────────────────────
    //
    // Drawn into the inner box of an affiliation frame. Inner box is fully
    // contained within the frame so glyphs never touch the border.

    private fun drawInfantryGlyph(c: Canvas, r: RectF, p: Paint, col: Int, dp: Float) {
        p.color = col; p.style = Paint.Style.STROKE
        p.strokeWidth = 1.8f * dp; p.strokeCap = Paint.Cap.SQUARE
        c.drawLine(r.left, r.top, r.right, r.bottom, p)     // ╲
        c.drawLine(r.right, r.top, r.left, r.bottom, p)     // ╱
    }

    private fun drawArmorGlyph(c: Canvas, r: RectF, p: Paint, col: Int, dp: Float) {
        // Horizontal track-oval — APP-6 armoured / tracked-vehicle modifier.
        p.color = col; p.style = Paint.Style.FILL
        val cx = r.centerX(); val cy = r.centerY()
        val hw = r.width() * 0.40f; val hh = r.height() * 0.22f
        c.drawOval(cx - hw, cy - hh, cx + hw, cy + hh, p)
    }

    private fun drawMechInfGlyph(c: Canvas, r: RectF, p: Paint, col: Int, dp: Float) {
        drawInfantryGlyph(c, r, p, col, dp)
        drawArmorGlyph(c, r, p, col, dp)
    }

    private fun drawArtilleryGlyph(c: Canvas, r: RectF, p: Paint, col: Int, dp: Float) {
        // Filled dot (cannonball) — APP-6 field-artillery modifier.
        p.color = col; p.style = Paint.Style.FILL
        c.drawCircle(r.centerX(), r.centerY(), minOf(r.width(), r.height()) * 0.22f, p)
    }

    private fun drawAirDefenseGlyph(c: Canvas, r: RectF, p: Paint, col: Int, dp: Float) {
        // Upward chevron / triangle — APP-6 air-defence modifier.
        p.color = col; p.style = Paint.Style.STROKE
        p.strokeWidth = 1.8f * dp; p.strokeJoin = Paint.Join.MITER
        val path = Path().apply {
            moveTo(r.left + r.width() * 0.15f, r.bottom - r.height() * 0.20f)
            lineTo(r.centerX(),                r.top    + r.height() * 0.15f)
            lineTo(r.right - r.width() * 0.15f, r.bottom - r.height() * 0.20f)
        }
        c.drawPath(path, p)
    }

    private fun drawReconGlyph(c: Canvas, r: RectF, p: Paint, col: Int, dp: Float) {
        // Bottom-left to top-right slash — APP-6 reconnaissance modifier.
        p.color = col; p.style = Paint.Style.STROKE
        p.strokeWidth = 1.8f * dp; p.strokeCap = Paint.Cap.SQUARE
        c.drawLine(r.left, r.bottom, r.right, r.top, p)
    }

    private fun drawSniperGlyph(c: Canvas, r: RectF, p: Paint, col: Int, dp: Float) {
        // Infantry X + cross-hair circle — sniper / designated marksman.
        drawInfantryGlyph(c, r, p, col, dp)
        p.style = Paint.Style.STROKE; p.strokeWidth = 1.4f * dp
        c.drawCircle(r.centerX(), r.centerY(), minOf(r.width(), r.height()) * 0.18f, p)
    }

    private fun drawHqGlyph(c: Canvas, r: RectF, p: Paint, col: Int, dp: Float) {
        // Headquarters — APP-6 vertical flag-staff dropping from bottom-left
        // of the frame, infantry X on the frame itself.
        drawInfantryGlyph(c, r, p, col, dp)
        p.color = col; p.style = Paint.Style.STROKE
        p.strokeWidth = 2f * dp; p.strokeCap = Paint.Cap.SQUARE
        // Staff drops from the bottom-left frame corner down past the frame —
        // since we only have the inner box here, drop it to mid-low.
        c.drawLine(r.left + 1 * dp, r.top, r.left + 1 * dp, r.bottom + 4 * dp, p)
    }

    private fun drawUnknownGlyph(c: Canvas, r: RectF, p: Paint, col: Int, dp: Float) {
        p.color = col; p.style = Paint.Style.FILL
        p.textSize = r.height() * 0.85f
        p.textAlign = Paint.Align.CENTER
        p.isFakeBoldText = true
        val fm = p.fontMetrics
        c.drawText("?", r.centerX(), r.centerY() - (fm.ascent + fm.descent) / 2f, p)
    }

    private fun drawHostileGlyph(
        c: Canvas, inner: RectF, p: Paint, col: Int, dp: Float, type: EnemyType,
    ) {
        when (type) {
            EnemyType.INFANTRY    -> drawInfantryGlyph(c, inner, p, col, dp)
            EnemyType.ARMOR      -> drawArmorGlyph(c, inner, p, col, dp)
            EnemyType.MECHANIZED -> drawMechInfGlyph(c, inner, p, col, dp)
            EnemyType.ARTILLERY  -> drawArtilleryGlyph(c, inner, p, col, dp)
            EnemyType.AIR_DEFENSE -> drawAirDefenseGlyph(c, inner, p, col, dp)
            EnemyType.RECON      -> drawReconGlyph(c, inner, p, col, dp)
            EnemyType.SNIPER     -> drawSniperGlyph(c, inner, p, col, dp)
            EnemyType.VEHICLE    -> drawArmorGlyph(c, inner, p, col, dp)
            EnemyType.UNKNOWN    -> drawUnknownGlyph(c, inner, p, col, dp)
            EnemyType.POI        -> drawUnknownGlyph(c, inner, p, col, dp)   // POI uses poi() instead
        }
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

    // ── Tactical control graphics — point symbols (Phase 2 render-only) ─────
    //
    // Maps the web-side TG_SPEC palette: ATK_AXIS, COUNTERATTACK, DEF_AREA,
    // AMBUSH, BLOCK, BYPASS, WITHDRAW. Each is drawn upright then rotated to
    // the heading; the echelon designator (dots / bars) is drawn UPRIGHT on
    // top of the icon — independent of rotation, MIL-STD-2525 style.

    private data class TgSpec(val drawer: (Canvas, Float, Int) -> Unit)

    // NATO affiliation → colour. Drives every TG; type only controls the shape.
    private val TG_FRIENDLY = Color.rgb( 59, 130, 246)
    private val TG_ENEMY    = Color.rgb(220,  38,  38)
    private val TG_UNKNOWN  = Color.rgb(250, 204,  21)
    fun affiliationColor(affiliation: String?): Int = when (affiliation) {
        "ENEMY"   -> TG_ENEMY
        "UNKNOWN" -> TG_UNKNOWN
        else      -> TG_FRIENDLY
    }

    /** Returns null when [type] is not a tactical graphic. */
    fun tacticalGraphic(
        res: Resources, type: String, rotation: Double,
        echelon: String, affiliation: String = "FRIENDLY",
    ): Drawable? {
        val spec = TG_SPECS[type] ?: return null
        val color = affiliationColor(affiliation)
        val dp = res.displayMetrics.density
        val size = (52 * dp).toInt()
        val bmp  = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        val cx = size / 2f

        // Save, rotate around centre, draw glyph, restore — keeps echelon upright.
        canvas.save()
        canvas.rotate(rotation.toFloat(), cx, cx)
        spec.drawer(canvas, dp, color)
        canvas.restore()

        if (echelon.isNotBlank()) drawEchelon(canvas, cx, dp, echelon, color)
        return BitmapDrawable(res, bmp)
    }

    private val TG_SPECS: Map<String, TgSpec> = mapOf(
        "ATK_AXIS"      to TgSpec { c, dp, col -> drawAttackArrow(c, dp, col, dashed = false) },
        "COUNTERATTACK" to TgSpec { c, dp, col -> drawAttackArrow(c, dp, col, dashed = true) },
        "AMBUSH"        to TgSpec { c, dp, col -> drawV(c, dp, col) },
        "DEF_AREA"      to TgSpec { c, dp, col -> drawDefenseU(c, dp, col) },
        "BLOCK"         to TgSpec { c, dp, col -> drawBlockBar(c, dp, col) },
        "BYPASS"        to TgSpec { c, dp, col -> drawBypass(c, dp, col) },
        "WITHDRAW"      to TgSpec { c, dp, col -> drawWithdraw(c, dp, col) },
    )

    fun isTacticalGraphic(type: String): Boolean = type in TG_SPECS
    fun isTacticalLineOrPolygon(type: String): Boolean = type in TG_LINES_AND_POLYS

    /** Stroke / fill style for line and polygon tactical graphics. */
    data class TgLineStyle(val color: Int, val widthDp: Float, val dashOnDp: Float, val dashOffDp: Float)
    // Width + dash come from the TYPE; colour comes from the AFFILIATION.
    private data class TgLineShape(val widthDp: Float, val dashOnDp: Float, val dashOffDp: Float)
    private val TG_LINE_SHAPES: Map<String, TgLineShape> = mapOf(
        "BOUNDARY"   to TgLineShape(3f, 8f, 4f),
        "FLET"       to TgLineShape(3f, 6f, 4f),
        "FLOT"       to TgLineShape(3f, 0f, 0f),
        "PHASE_LINE" to TgLineShape(2f, 0f, 0f),
        "OBJ_AREA"   to TgLineShape(3f, 0f, 0f),
    )
    private val TG_LINES_AND_POLYS = TG_LINE_SHAPES.keys
    fun tacticalLineStyle(type: String, affiliation: String = "FRIENDLY"): TgLineStyle? =
        TG_LINE_SHAPES[type]?.let {
            TgLineStyle(affiliationColor(affiliation), it.widthDp, it.dashOnDp, it.dashOffDp)
        }
    fun isTacticalPolygon(type: String): Boolean = type == "OBJ_AREA"

    private fun drawAttackArrow(c: Canvas, dp: Float, col: Int, dashed: Boolean) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = col; style = Paint.Style.STROKE
            strokeWidth = 4 * dp; strokeCap = Paint.Cap.ROUND
            if (dashed) pathEffect = android.graphics.DashPathEffect(floatArrayOf(5 * dp, 3 * dp), 0f)
        }
        c.drawLine(26 * dp, 44 * dp, 26 * dp, 9 * dp, paint)
        // Arrowhead — solid even when shaft is dashed
        paint.pathEffect = null
        paint.style = Paint.Style.FILL
        val head = Path().apply {
            moveTo(26 * dp, 3 * dp); lineTo(18 * dp, 14 * dp); lineTo(34 * dp, 14 * dp); close()
        }
        c.drawPath(head, paint)
    }

    private fun drawV(c: Canvas, dp: Float, col: Int) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = col; style = Paint.Style.STROKE
            strokeWidth = 4 * dp; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND
        }
        val p = Path().apply {
            moveTo( 9 * dp, 34 * dp); lineTo(26 * dp,  8 * dp); lineTo(43 * dp, 34 * dp)
        }
        c.drawPath(p, paint)
    }

    private fun drawDefenseU(c: Canvas, dp: Float, col: Int) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = col; style = Paint.Style.STROKE
            strokeWidth = 4 * dp; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND
        }
        val p = Path().apply {
            moveTo( 9 * dp, 12 * dp); lineTo( 9 * dp, 34 * dp)
            lineTo(43 * dp, 34 * dp); lineTo(43 * dp, 12 * dp)
        }
        c.drawPath(p, paint)
    }

    private fun drawBlockBar(c: Canvas, dp: Float, col: Int) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = col; style = Paint.Style.STROKE
            strokeWidth = 4 * dp; strokeCap = Paint.Cap.ROUND
        }
        c.drawLine(26 * dp, 38 * dp, 26 * dp, 14 * dp, paint)
        paint.strokeWidth = 5 * dp
        c.drawLine(13 * dp, 14 * dp, 39 * dp, 14 * dp, paint)
    }

    private fun drawBypass(c: Canvas, dp: Float, col: Int) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = col; style = Paint.Style.STROKE
            strokeWidth = 4 * dp; strokeCap = Paint.Cap.ROUND
        }
        // Quarter-curve from bottom-left up to right
        val p = Path().apply {
            moveTo(17 * dp, 42 * dp)
            quadTo(17 * dp, 16 * dp, 36 * dp, 16 * dp)
        }
        c.drawPath(p, paint)
        paint.style = Paint.Style.FILL
        val head = Path().apply {
            moveTo(42 * dp, 16 * dp); lineTo(33 * dp, 11 * dp); lineTo(33 * dp, 21 * dp); close()
        }
        c.drawPath(head, paint)
    }

    private fun drawWithdraw(c: Canvas, dp: Float, col: Int) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = col; style = Paint.Style.STROKE
            strokeWidth = 4 * dp; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND
        }
        c.drawLine(26 * dp, 9 * dp, 26 * dp, 38 * dp, paint)
        // Curl at the head end
        val curl = Path().apply {
            moveTo(26 * dp, 9 * dp); quadTo(18 * dp, 9 * dp, 18 * dp, 16 * dp)
        }
        c.drawPath(curl, paint)
        paint.style = Paint.Style.FILL
        val head = Path().apply {
            moveTo(26 * dp, 44 * dp); lineTo(18 * dp, 33 * dp); lineTo(34 * dp, 33 * dp); close()
        }
        c.drawPath(head, paint)
    }

    private val ECHELON_DOTS = mapOf("TM" to 2, "SEC" to 3)
    private val ECHELON_BARS = mapOf("PL" to 1, "COY" to 2, "BN" to 3)

    private fun drawEchelon(c: Canvas, cx: Float, dp: Float, echelon: String, col: Int) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = col; style = Paint.Style.FILL }
        val edge  = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE; style = Paint.Style.STROKE; strokeWidth = 1f * dp
        }
        ECHELON_DOTS[echelon]?.let { n ->
            val r = 2.4f * dp; val gap = 5 * dp
            val start = cx - ((n - 1) * gap) / 2f
            for (i in 0 until n) {
                val x = start + i * gap
                c.drawCircle(x, 4 * dp, r, paint)
                c.drawCircle(x, 4 * dp, r, edge)
            }
            return
        }
        ECHELON_BARS[echelon]?.let { n ->
            val w = 2.5f * dp; val h = 7 * dp; val gap = 4 * dp
            val start = cx - ((n - 1) * gap) / 2f
            for (i in 0 until n) {
                val x = start + i * gap
                c.drawRect(x - w/2, 1.5f * dp, x + w/2, 1.5f * dp + h, paint)
                c.drawRect(x - w/2, 1.5f * dp, x + w/2, 1.5f * dp + h, edge)
            }
        }
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
