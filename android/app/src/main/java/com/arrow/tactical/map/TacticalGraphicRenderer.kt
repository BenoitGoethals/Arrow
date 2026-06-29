package com.arrow.tactical.map

import android.content.res.Resources
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.drawable.BitmapDrawable
import com.arrow.tactical.network.TacticalObjectDto
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Overlay
import org.osmdroid.views.overlay.Polygon
import org.osmdroid.views.overlay.Polyline
import kotlin.math.*

/**
 * Renders APP-6 / MIL-STD-2525C tactical control measures as OSMdroid overlays.
 * Matches the `buildTacticalGraphic()` renderer in front/map/html/map.html.
 *
 * Types handled: ATK_AXIS, AXIS, COUNTERATTACK, BYPASS, WITHDRAW, DEF_AREA, BLOCK,
 * AMBUSH, OBJ_AREA, BOUNDARY, PHASE_LINE, ROUTE, FLOT, FLET, FSCL, CFL, NFL,
 * NFA, FFA, ENGAGEMENT_AREA, ASSEMBLY_AREA, ZONE, NAI, TAI.
 */
object TacticalGraphicRenderer {

    // ── APP-6 affiliation palette (matches front _affColor) ───────────────────
    fun affiliationColor(affiliation: String?): Int = when (affiliation?.uppercase()) {
        "HOSTILE", "ENEMY" -> Color.parseColor("#f85149")
        "NEUTRAL"          -> Color.parseColor("#3fb950")
        "UNKNOWN"          -> Color.parseColor("#d29922")
        else               -> Color.parseColor("#00aaff")
    }

    // ── Type registry ─────────────────────────────────────────────────────────

    private enum class TgKind {
        WIDE_ARROW, ARROW, DEFENSE, BLOCK_BAR, HORSESHOE,
        SCALLOP, LINE_LABEL, FSCM, BOUNDARY, AREA, AREA_DASHED, HATCH,
        SOF_POINT  // rendered via MilSymbolRenderer fallback (no geometry)
    }

    private data class TgSpec(
        val kind: TgKind,
        val widthDp: Float = 2.5f,
        val affByAff: Boolean = false,
        val fixedColor: Int? = null,
        val tag: String = "",
        val dashOnDp: Float = 0f,
        val dashOffDp: Float = 0f,
    )

    private val TG_REGISTRY: Map<String, TgSpec> = mapOf(
        // Offensive manoeuvre
        "ATK_AXIS"        to TgSpec(TgKind.WIDE_ARROW,  3.0f, affByAff = true),
        "AXIS"            to TgSpec(TgKind.ARROW,        3.5f, affByAff = true),
        "COUNTERATTACK"   to TgSpec(TgKind.ARROW,        3.0f, affByAff = true, dashOnDp = 12f, dashOffDp = 5f),
        "BYPASS"          to TgSpec(TgKind.ARROW,        3.0f, affByAff = true),
        "WITHDRAW"        to TgSpec(TgKind.ARROW,        3.0f, affByAff = true, dashOnDp = 5f,  dashOffDp = 5f),
        // Defensive
        "DEF_AREA"        to TgSpec(TgKind.DEFENSE,      3.0f, affByAff = true),
        "BLOCK"           to TgSpec(TgKind.BLOCK_BAR,    3.0f, affByAff = true),
        "AMBUSH"          to TgSpec(TgKind.HORSESHOE,    3.0f, affByAff = true),
        // Areas (affiliation-coloured)
        "OBJ_AREA"        to TgSpec(TgKind.AREA, 2.0f, affByAff = true, tag = "OBJ"),
        // Areas and zones (fixed standard colours)
        "FFA"             to TgSpec(TgKind.AREA,       2.0f, fixedColor = 0xFF00CC00.toInt(), tag = "FFA"),
        "ENGAGEMENT_AREA" to TgSpec(TgKind.AREA,       2.0f, fixedColor = 0xFFFF3300.toInt(), tag = "EA"),
        "ASSEMBLY_AREA"   to TgSpec(TgKind.AREA,       2.0f, fixedColor = 0xFF44AAFF.toInt(), tag = "AA"),
        "ZONE"            to TgSpec(TgKind.AREA,       2.0f, fixedColor = 0xFFD29922.toInt(), tag = ""),
        "NFA"             to TgSpec(TgKind.HATCH,      2.0f, fixedColor = 0xFFFF0000.toInt(), tag = "NFA"),
        "NAI"             to TgSpec(TgKind.AREA_DASHED, 2.0f, fixedColor = 0xFFAA44FF.toInt(), tag = "NAI"),
        "TAI"             to TgSpec(TgKind.AREA_DASHED, 2.0f, fixedColor = 0xFFFF44AA.toInt(), tag = "TAI"),
        // Forward lines + phase lines
        "BOUNDARY"   to TgSpec(TgKind.BOUNDARY,  2.0f, affByAff = true),
        "PHASE_LINE" to TgSpec(TgKind.LINE_LABEL, 3.0f, affByAff = true, tag = "PL"),
        "ROUTE"      to TgSpec(TgKind.LINE_LABEL, 2.0f, affByAff = true, tag = "RTE", dashOnDp = 10f, dashOffDp = 5f),
        "FLOT"       to TgSpec(TgKind.SCALLOP, 2.5f, fixedColor = 0xFF00CC55.toInt(), tag = "FLOT"),
        "FLET"       to TgSpec(TgKind.SCALLOP, 2.5f, fixedColor = 0xFFF85149.toInt(), tag = "FLET"),
        // Fire-support coordination measures
        "FSCL" to TgSpec(TgKind.FSCM, 3.0f, fixedColor = 0xFFFF8800.toInt(), tag = "FSCL"),
        "CFL"  to TgSpec(TgKind.FSCM, 2.5f, fixedColor = 0xFFFF4400.toInt(), tag = "CFL"),
        "NFL"  to TgSpec(TgKind.FSCM, 2.5f, fixedColor = 0xFFFF0000.toInt(), tag = "NFL"),
        // SOF / Paracommando point markers — routed via MilSymbolRenderer fallback
        "SOF_OP"       to TgSpec(TgKind.SOF_POINT, fixedColor = 0xFFF59E0B.toInt()),
        "SOF_LUP"      to TgSpec(TgKind.SOF_POINT, fixedColor = 0xFFF59E0B.toInt()),
        "SOF_IP"       to TgSpec(TgKind.SOF_POINT, fixedColor = 0xFF22C55E.toInt()),
        "SOF_BIVAK"    to TgSpec(TgKind.SOF_POINT, fixedColor = 0xFFF59E0B.toInt()),
        "SOF_PUP"      to TgSpec(TgKind.SOF_POINT, fixedColor = 0xFF60A5FA.toInt()),
        "SOF_DP"       to TgSpec(TgKind.SOF_POINT, fixedColor = 0xFF60A5FA.toInt()),
        "SOF_RV"       to TgSpec(TgKind.SOF_POINT, fixedColor = 0xFFA855F7.toInt()),
        "SOF_ERV"      to TgSpec(TgKind.SOF_POINT, fixedColor = 0xFFEC4899.toInt()),
        "SOF_CP"       to TgSpec(TgKind.SOF_POINT, fixedColor = 0xFFF59E0B.toInt()),
        "SOF_FUP"      to TgSpec(TgKind.SOF_POINT, fixedColor = 0xFF22C55E.toInt()),
        "SOF_HLZ"      to TgSpec(TgKind.SOF_POINT, fixedColor = 0xFF60A5FA.toInt()),
        "SOF_DZ"       to TgSpec(TgKind.SOF_POINT, fixedColor = 0xFF22C55E.toInt()),
        // SOF lines
        "SOF_BASELINE" to TgSpec(TgKind.LINE_LABEL, 2.5f, fixedColor = 0xFFF59E0B.toInt(), tag = "BSL",
                                 dashOnDp = 8f, dashOffDp = 4f),
        "SOF_FLANK"    to TgSpec(TgKind.ARROW,      2.5f, fixedColor = 0xFFF59E0B.toInt()),
    )

    fun isTacticalControl(type: String): Boolean = type in TG_REGISTRY

    // ── Entry point ───────────────────────────────────────────────────────────

    fun buildTacticalGraphicOverlays(
        map: MapView, res: Resources, g: TacticalObjectDto, coords: List<GeoPoint>,
    ): List<Overlay> {
        val spec  = TG_REGISTRY[g.type] ?: return emptyList()
        val color = spec.fixedColor ?: affiliationColor(g.affiliation)
        val dp    = res.displayMetrics.density
        val w     = spec.widthDp * dp
        val len   = polyLen(coords)
        // Arrowhead ground-size: 15% of total length, clamped [200 m, 3 000 m]
        val head  = min(max(len * 0.15, 200.0), 3000.0)
        val tip   = coords.last()
        val prev  = coords[coords.size - 2]
        val brg   = bearing(prev, tip)

        return when (spec.kind) {
            TgKind.WIDE_ARROW  -> buildWideArrow(map, coords, color, w, len, brg, tip)
            TgKind.ARROW       -> buildArrow(map, coords, color, w, dp, head, brg, tip, spec.dashOnDp, spec.dashOffDp)
            TgKind.DEFENSE     -> buildDefense(map, coords, color, w, dp, len)
            TgKind.BLOCK_BAR   -> buildBlockBar(map, coords, color, w, head, brg, tip)
            TgKind.HORSESHOE   -> buildHorseshoe(map, coords, color, w, head, brg, tip)
            TgKind.SCALLOP     -> buildScallop(map, res, coords, color, w, len, spec.tag)
            TgKind.LINE_LABEL,
            TgKind.FSCM        -> buildLineLabel(map, res, coords, color, w, dp, spec, g.notes, g.type)
            TgKind.BOUNDARY    -> buildBoundary(map, res, coords, color, w, dp, g.notes)
            TgKind.AREA        -> buildArea(map, res, coords, color, w, dp, spec.tag, dashed = false)
            TgKind.AREA_DASHED -> buildArea(map, res, coords, color, w, dp, spec.tag, dashed = true)
            TgKind.HATCH       -> buildHatch(map, res, coords, color, w, dp, spec.tag)
            TgKind.SOF_POINT   -> emptyList() // rendered via MilSymbolRenderer fallback
        }
    }

    // ── Geodesy helpers ───────────────────────────────────────────────────────

    private fun bearing(a: GeoPoint, b: GeoPoint): Double {
        val lat1 = Math.toRadians(a.latitude);  val lat2 = Math.toRadians(b.latitude)
        val dLon = Math.toRadians(b.longitude - a.longitude)
        val y    = sin(dLon) * cos(lat2)
        val x    = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dLon)
        return (Math.toDegrees(atan2(y, x)) + 360) % 360
    }

    private fun destPoint(from: GeoPoint, bearingDeg: Double, distM: Double): GeoPoint {
        val R    = 6371000.0;  val d = distM / R
        val lat1 = Math.toRadians(from.latitude)
        val lon1 = Math.toRadians(from.longitude)
        val brg  = Math.toRadians(bearingDeg)
        val lat2 = asin(sin(lat1) * cos(d) + cos(lat1) * sin(d) * cos(brg))
        val lon2 = lon1 + atan2(sin(brg) * sin(d) * cos(lat1), cos(d) - sin(lat1) * sin(lat2))
        return GeoPoint(Math.toDegrees(lat2), Math.toDegrees(lon2))
    }

    private fun distM(a: GeoPoint, b: GeoPoint): Double {
        val R    = 6371000.0
        val dLat = Math.toRadians(b.latitude - a.latitude)
        val dLon = Math.toRadians(b.longitude - a.longitude)
        val la1  = Math.toRadians(a.latitude);  val la2 = Math.toRadians(b.latitude)
        val x    = sin(dLat / 2).pow(2) + cos(la1) * cos(la2) * sin(dLon / 2).pow(2)
        return 2 * R * asin(sqrt(x))
    }

    private fun polyLen(pts: List<GeoPoint>): Double =
        (1 until pts.size).sumOf { distM(pts[it - 1], pts[it]) }

    private fun ptAtDist(pts: List<GeoPoint>, d: Double): Pair<GeoPoint, Double> {
        var acc = 0.0
        for (i in 0 until pts.size - 1) {
            val s = distM(pts[i], pts[i + 1])
            if (acc + s >= d) {
                val t  = (d - acc) / s
                val pt = GeoPoint(
                    pts[i].latitude  + t * (pts[i + 1].latitude  - pts[i].latitude),
                    pts[i].longitude + t * (pts[i + 1].longitude - pts[i].longitude),
                )
                return pt to bearing(pts[i], pts[i + 1])
            }
            acc += s
        }
        val n = pts.size - 1
        return pts[n] to bearing(pts[maxOf(0, n - 1)], pts[n])
    }

    private fun offsetPath(pts: List<GeoPoint>, distMt: Double, side: Int): List<GeoPoint> =
        pts.mapIndexed { i, p ->
            val brg = when {
                i == 0            -> bearing(pts[0], pts[1])
                i == pts.size - 1 -> bearing(pts[i - 1], pts[i])
                else              -> bearing(pts[i - 1], pts[i + 1])
            }
            destPoint(p, (brg + 90.0 * side + 360) % 360, distMt)
        }

    private fun centroid(pts: List<GeoPoint>) =
        GeoPoint(pts.sumOf { it.latitude } / pts.size, pts.sumOf { it.longitude } / pts.size)

    // Strip user notes if they're just a repeat of the type name (e.g. "PHASE LINE")
    private fun tgName(notes: String, type: String): String {
        val n = notes.trim().ifEmpty { return "" }
        val norm = { s: String -> s.uppercase().replace(Regex("[^A-Z0-9]"), "") }
        return if (norm(n) == norm(type)) "" else n
    }

    // ── OSMdroid overlay factories ────────────────────────────────────────────

    private fun mkLine(
        map: MapView, pts: List<GeoPoint>, color: Int, strokePx: Float,
        dashOnPx: Float = 0f, dashOffPx: Float = 0f,
    ): Polyline = Polyline(map).apply {
        setPoints(pts)
        outlinePaint.color       = color
        outlinePaint.strokeWidth = strokePx
        outlinePaint.isAntiAlias = true
        outlinePaint.strokeCap   = Paint.Cap.ROUND
        outlinePaint.strokeJoin  = Paint.Join.ROUND
        if (dashOnPx > 0f)
            outlinePaint.pathEffect = android.graphics.DashPathEffect(floatArrayOf(dashOnPx, dashOffPx), 0f)
    }

    private fun mkPoly(map: MapView, pts: List<GeoPoint>, color: Int, strokePx: Float,
                       fillAlpha: Int = 0x12, dashOnPx: Float = 0f, dashOffPx: Float = 0f): Polygon =
        Polygon(map).apply {
            points                   = pts
            outlinePaint.color       = color
            outlinePaint.strokeWidth = strokePx
            outlinePaint.isAntiAlias = true
            if (dashOnPx > 0f)
                outlinePaint.pathEffect = android.graphics.DashPathEffect(floatArrayOf(dashOnPx, dashOffPx), 0f)
            fillPaint.color = (color and 0x00FFFFFF) or (fillAlpha shl 24)
        }

    private fun textMarker(map: MapView, res: Resources, position: GeoPoint, text: String, color: Int): Marker {
        val dp    = res.displayMetrics.density
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            textSize       = 10 * dp
            isFakeBoldText = true
            typeface       = android.graphics.Typeface.MONOSPACE
            letterSpacing  = 0.05f
            this.color     = color
        }
        val tw = paint.measureText(text)
        val w  = (tw + 14 * dp).toInt().coerceAtLeast(1)
        val h  = (16 * dp).toInt().coerceAtLeast(1)
        val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val c   = Canvas(bmp)
        Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = Color.argb(210, 13, 17, 23); style = Paint.Style.FILL }
            .also { c.drawRoundRect(RectF(0f, 0f, w.toFloat(), h.toFloat()), 3 * dp, 3 * dp, it) }
        Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = color; style = Paint.Style.STROKE; strokeWidth = dp }
            .also { c.drawRoundRect(RectF(.5f * dp, .5f * dp, w - .5f * dp, h - .5f * dp), 3 * dp, 3 * dp, it) }
        paint.textAlign = Paint.Align.CENTER
        val fm = paint.fontMetrics
        c.drawText(text, w / 2f, h / 2f - (fm.ascent + fm.descent) / 2f, paint)
        return Marker(map).apply {
            this.position = position
            icon = BitmapDrawable(res, bmp)
            setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
        }
    }

    // ── Renderers ─────────────────────────────────────────────────────────────

    private fun buildWideArrow(
        map: MapView, pts: List<GeoPoint>, color: Int, w: Float,
        len: Double, brg: Double, tip: GeoPoint,
    ): List<Overlay> {
        val halfW   = min(max(len * 0.06, 120.0), 900.0)
        val headLen = halfW * 3
        val base    = destPoint(tip, (brg + 180) % 360, headLen)
        val shaft   = pts.dropLast(1) + listOf(base)
        val left    = offsetPath(shaft, halfW, -1)
        val right   = offsetPath(shaft, halfW, +1)
        val wingL   = destPoint(base, (brg - 90 + 360) % 360, halfW * 2)
        val wingR   = destPoint(base, (brg + 90) % 360,        halfW * 2)
        val outline = left + listOf(wingL, tip, wingR) + right.reversed()
        return listOf(
            Polygon(map).apply {
                points                   = outline
                outlinePaint.color       = color
                outlinePaint.strokeWidth = w
                outlinePaint.isAntiAlias = true
                fillPaint.color          = Color.TRANSPARENT
            },
        )
    }

    private fun buildArrow(
        map: MapView, pts: List<GeoPoint>, color: Int, w: Float, dp: Float,
        head: Double, brg: Double, tip: GeoPoint, dashOnDp: Float, dashOffDp: Float,
    ): List<Overlay> {
        val wingL = destPoint(tip, (brg + 148 + 360) % 360, head * 0.85)
        val wingR = destPoint(tip, (brg - 148 + 360) % 360, head * 0.85)
        return listOf(
            mkLine(map, pts, color, w, dashOnDp * dp, dashOffDp * dp),
            mkLine(map, listOf(wingL, tip, wingR), color, w),
        )
    }

    private fun buildDefense(
        map: MapView, pts: List<GeoPoint>, color: Int, w: Float, dp: Float, len: Double,
    ): List<Overlay> {
        val overlays = mutableListOf<Overlay>(mkLine(map, pts, color, w))
        val nTicks   = max(4, min(20, (len / 400).roundToInt()))
        val spacing  = len / (nTicks + 1)
        val tLen     = spacing * 0.55
        val tickW    = (w - dp).coerceAtLeast(dp)
        for (k in 1..nTicks) {
            val (pt, b) = ptAtDist(pts, k * spacing)
            overlays.add(mkLine(map, listOf(pt, destPoint(pt, (b + 90 + 360) % 360, tLen)), color, tickW))
        }
        return overlays
    }

    private fun buildBlockBar(
        map: MapView, pts: List<GeoPoint>, color: Int, w: Float,
        head: Double, brg: Double, tip: GeoPoint,
    ): List<Overlay> {
        val a1 = destPoint(tip, (brg + 90 + 360) % 360, head * 0.55)
        val a2 = destPoint(tip, (brg - 90 + 360) % 360, head * 0.55)
        return listOf(mkLine(map, pts, color, w), mkLine(map, listOf(a1, a2), color, w + 1f))
    }

    private fun buildHorseshoe(
        map: MapView, pts: List<GeoPoint>, color: Int, w: Float,
        head: Double, brg: Double, tip: GeoPoint,
    ): List<Overlay> {
        val arcPts = (-90..90 step 15).map { a ->
            destPoint(tip, (brg + a + 360) % 360, head * 0.8)
        }
        return listOf(mkLine(map, pts, color, w), mkLine(map, arcPts, color, w))
    }

    private fun buildScallop(
        map: MapView, res: Resources, pts: List<GeoPoint>,
        color: Int, w: Float, len: Double, tag: String,
    ): List<Overlay> {
        val radius = min(max(len * 0.15, 200.0), 3000.0) * 0.35
        val out    = mutableListOf<GeoPoint>()
        for (i in 0 until pts.size - 1) {
            val a = pts[i]; val b = pts[i + 1]
            val segLen = distM(a, b)
            val segBrg = bearing(a, b)
            val n      = max(1, (segLen / (radius * 2)).roundToInt())
            for (k in 0 until n) {
                val t0  = k.toDouble() / n;  val t1 = (k + 1).toDouble() / n
                val s   = GeoPoint(a.latitude + (b.latitude - a.latitude) * t0,
                                   a.longitude + (b.longitude - a.longitude) * t0)
                val e   = GeoPoint(a.latitude + (b.latitude - a.latitude) * t1,
                                   a.longitude + (b.longitude - a.longitude) * t1)
                val r   = distM(s, e) / 2
                val mid = GeoPoint((s.latitude + e.latitude) / 2, (s.longitude + e.longitude) / 2)
                for (deg in 0..180 step 15) {
                    out.add(destPoint(mid, (segBrg + 180 - deg + 360) % 360, r))
                }
            }
        }
        val overlays = mutableListOf<Overlay>(mkLine(map, out, color, w))
        if (tag.isNotEmpty()) {
            overlays.add(textMarker(map, res, pts.first(), tag, color))
            overlays.add(textMarker(map, res, pts.last(),  tag, color))
        }
        return overlays
    }

    private fun buildLineLabel(
        map: MapView, res: Resources, pts: List<GeoPoint>,
        color: Int, w: Float, dp: Float, spec: TgSpec, notes: String, type: String,
    ): List<Overlay> {
        val overlays = mutableListOf<Overlay>(
            mkLine(map, pts, color, w, spec.dashOnDp * dp, spec.dashOffDp * dp),
        )
        val name  = tgName(notes, type)
        val label = spec.tag + if (name.isNotEmpty()) " $name" else ""
        if (label.isNotBlank()) {
            overlays.add(textMarker(map, res, pts.first(), label, color))
            overlays.add(textMarker(map, res, pts.last(),  label, color))
        }
        return overlays
    }

    private fun buildBoundary(
        map: MapView, res: Resources, pts: List<GeoPoint>,
        color: Int, w: Float, dp: Float, notes: String,
    ): List<Overlay> {
        val overlays = mutableListOf<Overlay>(mkLine(map, pts, color, w, 6 * dp, 4 * dp))
        listOf(pts.first(), pts[pts.size / 2], pts.last()).forEach {
            overlays.add(textMarker(map, res, it, "✕", color))
        }
        val name = tgName(notes, "BOUNDARY")
        if (name.isNotEmpty()) overlays.add(textMarker(map, res, pts.first(), name, color))
        return overlays
    }

    private fun buildArea(
        map: MapView, res: Resources, pts: List<GeoPoint>,
        color: Int, w: Float, dp: Float, tag: String, dashed: Boolean,
    ): List<Overlay> {
        val overlays = mutableListOf<Overlay>(
            mkPoly(map, pts, color, w, fillAlpha = 0x12,
                   dashOnPx = if (dashed) 7 * dp else 0f,
                   dashOffPx = if (dashed) 5 * dp else 0f),
        )
        if (tag.isNotEmpty()) overlays.add(textMarker(map, res, centroid(pts), tag, color))
        return overlays
    }

    private fun buildHatch(
        map: MapView, res: Resources, pts: List<GeoPoint>,
        color: Int, w: Float, dp: Float, tag: String,
    ): List<Overlay> {
        val overlays = mutableListOf<Overlay>(mkPoly(map, pts, color, w, fillAlpha = 0))
        // Diagonal scanline hatch (same algorithm as front _addHatch)
        val minLat = pts.minOf { it.latitude };  val maxLat = pts.maxOf { it.latitude }
        val minLon = pts.minOf { it.longitude }; val maxLon = pts.maxOf { it.longitude }
        val H  = maxLat - minLat
        val W  = if ((maxLon - minLon) == 0.0) 1e-6 else maxLon - minLon
        val slope = H / W
        val dc    = if (H != 0.0) H / 9.0 else 0.0005
        val cMin  = minLat - slope * maxLon; val cMax = maxLat - slope * minLon
        var c = cMin
        while (c <= cMax) {
            val xs = mutableListOf<Pair<Double, Double>>()
            for (i in pts.indices) {
                val p1 = pts[i]; val p2 = pts[(i + 1) % pts.size]
                val x1 = p1.longitude; val y1 = p1.latitude
                val x2 = p2.longitude; val y2 = p2.latitude
                val A = (y2 - y1) - slope * (x2 - x1)
                val B = y1 - slope * x1 - c
                if (abs(A) < 1e-12) continue
                val t = -B / A
                if (t in 0.0..1.0) xs.add(Pair(x1 + t * (x2 - x1), y1 + t * (y2 - y1)))
            }
            xs.sortBy { it.first }
            var j = 0
            while (j + 1 < xs.size) {
                overlays.add(
                    mkLine(map,
                           listOf(GeoPoint(xs[j].second, xs[j].first),
                                  GeoPoint(xs[j + 1].second, xs[j + 1].first)),
                           color, w * 0.6f)
                )
                j += 2
            }
            c += dc
        }
        if (tag.isNotEmpty()) overlays.add(textMarker(map, res, centroid(pts), tag, color))
        return overlays
    }
}
