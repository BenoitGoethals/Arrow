package com.arrow.tactical.cbrn

import android.content.res.Resources
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color as AColor
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.graphics.drawable.BitmapDrawable
import android.graphics.drawable.Drawable
import com.arrow.tactical.network.ReportDto
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Polygon
import kotlin.math.PI
import kotlin.math.asin
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin

/** Parsed CBRN payload mirroring backend/reports/cbrn.py. */
data class CbrnPayload(
    val msgType: String,
    val agentCategory: String?,       // "C" | "B" | "R" | "N" | null
    val agent: String,
    val serial: String,
    val dtg: String,
    val delivery: String,
    val sourceFile: String,
    val latitude: Double?,
    val longitude: Double?,
    val windDirection: Double?,       // meteorological (FROM), degrees
    val windSpeed: Double?,           // km/h
    val zoneInnerM: Int,
    val zoneDownwindM: Int,
    val zoneDownwindAngleDeg: Double,
)

private val cbrnJson = Json { ignoreUnknownKeys = true; isLenient = true }

fun parseCbrnPayload(raw: String): CbrnPayload? = runCatching {
    val o = cbrnJson.parseToJsonElement(raw).jsonObject
    fun str(k: String) = o[k]?.jsonPrimitive?.contentOrNull.orEmpty()
    fun dbl(k: String) = o[k]?.jsonPrimitive?.doubleOrNull
    fun int(k: String) = o[k]?.jsonPrimitive?.intOrNull ?: 0
    CbrnPayload(
        msgType         = str("msg_type").ifBlank { "CBRN_1" },
        agentCategory   = str("agent_category").ifBlank { null }?.uppercase(),
        agent           = str("agent"),
        serial          = str("serial"),
        dtg             = str("dtg"),
        delivery        = str("delivery"),
        sourceFile      = str("source_file"),
        latitude        = dbl("latitude"),
        longitude       = dbl("longitude"),
        windDirection   = dbl("wind_direction"),
        windSpeed       = dbl("wind_speed"),
        zoneInnerM      = int("zone_inner_m"),
        zoneDownwindM   = int("zone_downwind_m"),
        zoneDownwindAngleDeg = dbl("zone_downwind_angle_deg") ?: 30.0,
    )
}.getOrNull()

/** Build the parsed list of CBRN reports from a /reports response. */
fun cbrnReportsFrom(reports: List<ReportDto>): List<Pair<Int, CbrnPayload>> =
    reports.asSequence()
        .filter { it.type.startsWith("CBRN_") }
        .mapNotNull { r -> parseCbrnPayload(r.payload)?.let { r.id to it } }
        .filter { it.second.latitude != null && it.second.longitude != null }
        .toList()

// ── Styling (matches web/templates/map.html) ───────────────────────────────
private data class CbrnStyle(
    val fill: Int, val text: Int, val border: Int, val zone: Int, val legend: String,
)
private val styleC = CbrnStyle(0xFFFBBF24.toInt(), 0xFF0D1117.toInt(), 0xFF0D1117.toInt(), 0xFFFBBF24.toInt(), "GAS")
private val styleB = CbrnStyle(0xFF1D4ED8.toInt(), 0xFFFFFFFF.toInt(), 0xFF0D1117.toInt(), 0xFF3B82F6.toInt(), "BIO")
private val styleR = CbrnStyle(0xFFFFFFFF.toInt(), 0xFF0D1117.toInt(), 0xFF0D1117.toInt(), 0xFFF97316.toInt(), "ATOM")
private val styleN = CbrnStyle(0xFFFFFFFF.toInt(), 0xFF0D1117.toInt(), 0xFF0D1117.toInt(), 0xFFEF4444.toInt(), "ATOM")
private val styleUnknown = CbrnStyle(0xFF94A3B8.toInt(), 0xFF0D1117.toInt(), 0xFF0D1117.toInt(), 0xFF94A3B8.toInt(), "?")

private fun styleOf(cat: String?): CbrnStyle = when (cat?.uppercase()) {
    "C" -> styleC; "B" -> styleB; "R" -> styleR; "N" -> styleN; else -> styleUnknown
}

fun categoryLabel(cat: String?): String = when (cat?.uppercase()) {
    "C" -> "CHEM"; "B" -> "BIO"; "R" -> "RAD"; "N" -> "NUC"; else -> "CBRN"
}

/**
 * NATO CBRN ground-marking triangle icon (point-up), with a small radiation
 * trefoil for R/N and a mushroom-cloud accent for N. Matches the web map.
 */
fun cbrnIcon(res: Resources, cat: String?): Drawable {
    val s = styleOf(cat)
    val density = res.displayMetrics.density
    val size = (48f * density).toInt()
    val bmp = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
    val c = Canvas(bmp)
    val sx = size / 48f // 1 svg unit = sx pixels

    // Mushroom-cloud accent (nuclear only)
    if (cat?.uppercase() == "N") {
        val ink = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = s.border; alpha = 230
        }
        c.drawOval(
            (22 - 6) * sx, (4 - 2.3f) * sx, (22 + 6) * sx, (4 + 2.3f) * sx, ink
        )
        c.drawRect((22 - 1) * sx, (4 + 1.5f) * sx, (22 + 1) * sx, (4 + 5f) * sx, ink)
    }

    // Equilateral isoceles triangle (24,8) (44,42) (4,42)
    val tri = Path().apply {
        moveTo(24 * sx, 8 * sx); lineTo(44 * sx, 42 * sx); lineTo(4 * sx, 42 * sx); close()
    }
    val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = s.fill; style = Paint.Style.FILL }
    val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = s.border; style = Paint.Style.STROKE
        strokeWidth = 2.5f * sx; strokeJoin = Paint.Join.ROUND
    }
    c.drawPath(tri, fill)
    c.drawPath(tri, stroke)

    // Legend text
    val txt = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = s.text
        textAlign = Paint.Align.CENTER
        textSize = 9f * sx
        isFakeBoldText = true
        typeface = android.graphics.Typeface.DEFAULT_BOLD
    }
    c.drawText(s.legend, 24 * sx, 34 * sx, txt)

    // Trefoil for R / N — small disc top-right
    if (cat?.uppercase() == "R" || cat?.uppercase() == "N") {
        val cx = 34f * sx; val cy = 12f * sx
        val white = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = AColor.WHITE }
        val ink = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = s.border }
        val out = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = s.border; style = Paint.Style.STROKE; strokeWidth = 1f * sx
        }
        c.drawCircle(cx, cy, 6f * sx, white)
        c.drawCircle(cx, cy, 6f * sx, out)
        c.drawCircle(cx, cy, 1.6f * sx, ink)
        for (deg in intArrayOf(0, 120, 240)) {
            c.save()
            c.rotate(deg.toFloat(), cx, cy)
            val blade = Path().apply {
                moveTo(cx, cy)
                lineTo(cx + 4.5f * sx, cy - 2.5f * sx)
                // approximate the small arc with a straight line — visually identical at this size
                lineTo(cx + 4.5f * sx, cy + 2.5f * sx)
                close()
            }
            c.drawPath(blade, ink)
            c.restore()
        }
    }

    return BitmapDrawable(res, bmp)
}

// ── Geo helpers ────────────────────────────────────────────────────────────
private const val EARTH_M = 6371000.0

private fun destPoint(lat: Double, lon: Double, brgDeg: Double, distM: Double): GeoPoint {
    val br = Math.toRadians(brgDeg)
    val phi1 = Math.toRadians(lat); val lam1 = Math.toRadians(lon)
    val dr = distM / EARTH_M
    val phi2 = asin(sin(phi1) * cos(dr) + cos(phi1) * sin(dr) * cos(br))
    val lam2 = lam1 + atan2(
        sin(br) * sin(dr) * cos(phi1),
        cos(dr) - sin(phi1) * sin(phi2),
    )
    val lonDeg = ((Math.toDegrees(lam2) + 540.0) % 360.0) - 180.0
    return GeoPoint(Math.toDegrees(phi2), lonDeg)
}

private fun circleRing(lat: Double, lon: Double, radiusM: Double, steps: Int = 48): List<GeoPoint> {
    val pts = ArrayList<GeoPoint>(steps + 1)
    for (i in 0..steps) {
        val brg = 360.0 * i / steps
        pts += destPoint(lat, lon, brg, radiusM)
    }
    return pts
}

private fun downwindSector(
    lat: Double, lon: Double, downwindBrg: Double, distM: Double, halfAngleDeg: Double,
): List<GeoPoint> {
    val pts = ArrayList<GeoPoint>()
    pts += GeoPoint(lat, lon)
    val n = 12
    for (i in 0..n) {
        val brg = downwindBrg - halfAngleDeg + (2.0 * halfAngleDeg * i / n)
        pts += destPoint(lat, lon, brg, distM)
    }
    pts += GeoPoint(lat, lon)
    return pts
}

/**
 * Add the marker + Zone I (immediate hazard circle) + Zone II (downwind sector)
 * overlays for one CBRN report. Returns the list of overlays so the caller can
 * include them in the map's overlay list and remove them on refresh.
 */
fun buildCbrnOverlays(
    map: MapView,
    res: Resources,
    payload: CbrnPayload,
): List<org.osmdroid.views.overlay.Overlay> {
    val lat = payload.latitude ?: return emptyList()
    val lon = payload.longitude ?: return emptyList()
    val style = styleOf(payload.agentCategory)
    val zoneColor = style.zone
    val dp = res.displayMetrics.density
    val result = mutableListOf<org.osmdroid.views.overlay.Overlay>()

    // Zone I — immediate hazard (dashed outlined disc)
    if (payload.zoneInnerM > 0) {
        val poly = Polygon(map).apply {
            points = circleRing(lat, lon, payload.zoneInnerM.toDouble())
            fillPaint.color = (zoneColor and 0x00FFFFFF) or 0x2E000000  // ~18% alpha
            outlinePaint.color = zoneColor
            outlinePaint.strokeWidth = 2f * dp
            outlinePaint.pathEffect = DashPathEffect(floatArrayOf(6f * dp, 6f * dp), 0f)
            title   = "Zone I — ${categoryLabel(payload.agentCategory)} immediate hazard"
            snippet = "%.1f km".format(payload.zoneInnerM / 1000.0)
        }
        result += poly
    }

    // Zone II — downwind sector (only if wind known)
    val wind = payload.windDirection
    if (wind != null && payload.zoneDownwindM > 0) {
        val downwindBrg = (wind + 180.0) % 360.0
        val sector = Polygon(map).apply {
            points = downwindSector(lat, lon, downwindBrg, payload.zoneDownwindM.toDouble(),
                                    payload.zoneDownwindAngleDeg)
            fillPaint.color = (zoneColor and 0x00FFFFFF) or 0x1F000000  // ~12% alpha
            outlinePaint.color = zoneColor
            outlinePaint.strokeWidth = 1.5f * dp
            title   = "Zone II — downwind hazard"
            snippet = "%.0f km @ %.0f°".format(payload.zoneDownwindM / 1000.0, downwindBrg)
        }
        result += sector
    }

    // Marker — triangle ground-marking sign
    val marker = Marker(map).apply {
        position = GeoPoint(lat, lon)
        icon = cbrnIcon(res, payload.agentCategory)
        // iconAnchor 24,42 in a 48-tall icon → bottom-center
        setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
        title    = "☢ ${payload.msgType} — ${categoryLabel(payload.agentCategory)}"
        snippet  = buildString {
            if (payload.serial.isNotBlank())   append("Serial ").append(payload.serial).append("  ")
            if (payload.dtg.isNotBlank())      append(payload.dtg).append("  ")
            if (payload.agent.isNotBlank())    append("\nAgent: ").append(payload.agent)
            if (payload.delivery.isNotBlank()) append("\nDelivery: ").append(payload.delivery)
            if (wind != null) append("\nWind: %.0f° / %s km/h".format(wind,
                payload.windSpeed?.let { "%.0f".format(it) } ?: "—"))
            append("\nZone I: ").append(payload.zoneInnerM / 1000).append(" km")
            append("  Zone II: ").append(payload.zoneDownwindM / 1000).append(" km")
            if (payload.sourceFile.isNotBlank())
                append("\nSource: ").append(payload.sourceFile)
        }
    }
    result += marker
    return result
}
