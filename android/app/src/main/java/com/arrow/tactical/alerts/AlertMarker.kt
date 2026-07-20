package com.arrow.tactical.alerts

import android.content.res.Resources
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.drawable.BitmapDrawable
import android.graphics.drawable.Drawable
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker

/**
 * Builds a visually loud Marker for an incoming alert (TIC, MEDICAL, …).
 *
 * Drawn as a coloured disc with a white ring + bold central dot so it pops
 * out against both light and dark base tiles. The disc colour follows the
 * NATO doctrinal convention used elsewhere in the app (TIC = red).
 *
 * Caller is responsible for adding the returned Marker to ``map.overlays``
 * and removing it once the alert is acknowledged.
 */
object AlertMarker {

    fun colourForType(type: String): Int = when (type.uppercase()) {
        "TIC"            -> 0xFFDC2626.toInt()
        "MEDICAL"        -> 0xFF16A34A.toInt()
        "MEDEVAC"        -> 0xFF22C55E.toInt()
        "EVAC"           -> 0xFFF59E0B.toInt()
        "LOST_COMMS"     -> 0xFF6366F1.toInt()
        "DRONE_SPOTTED"  -> 0xFFD2A8FF.toInt()   // received-only — matches web #d2a8ff
        "ATAK_EMERGENCY" -> 0xFFDC2626.toInt()   // received-only — high-urgency like TIC
        else             -> 0xFFDC2626.toInt()
    }

    // Glyph drawn centred on the disc, or null for the default white pip.
    // MEDEVAC / EVAC / MEDICAL get 🚁; DRONE_SPOTTED gets 🛸; ATAK_EMERGENCY ⚠.
    private fun glyphForType(type: String): String? = when (type.uppercase()) {
        "MEDEVAC", "EVAC", "MEDICAL" -> "🚁"
        "DRONE_SPOTTED"              -> "🛸"
        "ATAK_EMERGENCY"             -> "⚠"
        else                         -> null
    }

    fun build(
        map: MapView,
        res: Resources,
        lat: Double,
        lon: Double,
        type: String,
        title: String,
        snippet: String,
    ): Marker = Marker(map).apply {
        position = GeoPoint(lat, lon)
        this.title    = title
        this.snippet  = snippet
        icon          = circleIcon(res, colourForType(type), glyphForType(type))
        setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
        // Tagged so we can tell our alert markers apart from the tactical
        // ones the main render loop wipes/rebuilds. The radial-menu fix on
        // KML markers already uses ``relatedObject`` for the same reason.
        relatedObject = TAG
        // Don't consume the tap — operators must still be able to drop a
        // radial menu near a TIC location to spot enemy / fire / report.
        setOnMarkerClickListener { m, _ ->
            m.showInfoWindow()
            false
        }
    }

    fun isAlertMarker(o: Any?): Boolean =
        o is Marker && o.relatedObject == TAG

    private const val TAG = "arrow.alert-marker"

    private fun circleIcon(res: Resources, color: Int, glyph: String? = null): Drawable {
        val density = res.displayMetrics.density
        val sizePx  = (40f * density).toInt().coerceAtLeast(40)
        val bmp = Bitmap.createBitmap(sizePx, sizePx, Bitmap.Config.ARGB_8888)
        val cnv = Canvas(bmp)
        val p   = Paint(Paint.ANTI_ALIAS_FLAG)
        val cx  = sizePx / 2f
        val cy  = sizePx / 2f
        // Outer halo — translucent ring so it bleeds into the surrounding map.
        p.color = (color and 0x00FFFFFF) or 0x55000000
        p.style = Paint.Style.FILL
        cnv.drawCircle(cx, cy, sizePx * 0.46f, p)
        // Solid coloured disc.
        p.color = color
        p.style = Paint.Style.FILL
        cnv.drawCircle(cx, cy, sizePx * 0.34f, p)
        // White ring.
        p.color = 0xFFFFFFFF.toInt()
        p.style = Paint.Style.STROKE
        p.strokeWidth = density * 2.2f
        cnv.drawCircle(cx, cy, sizePx * 0.34f, p)
        if (glyph != null) {
            // Type glyph (🚁 / 🛸 / ⚠) centred on the disc.
            val tp = Paint(Paint.ANTI_ALIAS_FLAG)
            tp.textSize  = sizePx * 0.42f
            tp.textAlign = Paint.Align.CENTER
            val fm = tp.fontMetrics
            cnv.drawText(glyph, cx, cy - (fm.ascent + fm.descent) / 2f, tp)
        } else {
            // Central white pip.
            p.color = 0xFFFFFFFF.toInt()
            p.style = Paint.Style.FILL
            cnv.drawCircle(cx, cy, sizePx * 0.08f, p)
        }
        return BitmapDrawable(res, bmp)
    }
}
