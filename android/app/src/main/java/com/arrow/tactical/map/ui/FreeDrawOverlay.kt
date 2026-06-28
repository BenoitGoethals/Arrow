package com.arrow.tactical.map.ui

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.drawable.BitmapDrawable
import android.view.MotionEvent
import com.arrow.tactical.network.TacticalObjectDto
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Overlay
import org.osmdroid.views.overlay.Polyline

/**
 * OSMdroid overlay that turns finger drags into a free-draw stroke. While this
 * overlay is on the map it consumes touch events (so the map doesn't pan), draws
 * a live preview polyline, and on release hands the captured [GeoPoint] path back
 * via [onStroke]. The host removes the overlay to leave draw mode.
 */
class FreeDrawOverlay(
    private val strokeColor: Int,
    private val widthDp: Float,
    private val onStroke: (List<GeoPoint>) -> Unit,
) : Overlay() {

    private val points = ArrayList<GeoPoint>()
    private var preview: Polyline? = null

    override fun onTouchEvent(event: MotionEvent, mapView: MapView): Boolean {
        val proj = mapView.projection
        val gp = proj.fromPixels(event.x.toInt(), event.y.toInt()) as GeoPoint
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                points.clear()
                points.add(gp)
                preview = Polyline(mapView).apply {
                    outlinePaint.color = strokeColor
                    outlinePaint.strokeWidth =
                        widthDp * mapView.resources.displayMetrics.density
                    outlinePaint.isAntiAlias = true
                    setPoints(points)
                    mapView.overlays.add(this)
                }
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                points.add(gp)
                preview?.setPoints(ArrayList(points))
                mapView.invalidate()
                return true
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                preview?.let { mapView.overlays.remove(it) }
                preview = null
                mapView.invalidate()
                val captured = ArrayList(points)
                points.clear()
                if (event.actionMasked == MotionEvent.ACTION_UP && captured.size >= 2) {
                    onStroke(captured)
                }
                return true
            }
        }
        return false
    }
}

/** Build the FREEDRAW_LINE geometry/notes JSON the backend expects. */
fun freeDrawLineGeometry(points: List<GeoPoint>): String =
    buildString {
        append("{\"type\":\"line\",\"coords\":[")
        append(points.joinToString(",") { "[${it.latitude},${it.longitude}]" })
        append("]}")
    }

fun freeDrawNotes(colorHex: String, thick: Int): String =
    "{\"color\":\"$colorHex\",\"thick\":$thick}"

fun isFreeDraw(type: String): Boolean =
    type == "FREEDRAW_LINE" || type == "FREEDRAW_TEXT"

private fun parseCoords(geometry: String): List<GeoPoint>? = runCatching {
    val arr = Json.parseToJsonElement(geometry).jsonObject["coords"]?.jsonArray ?: return null
    arr.map {
        val ll = it.jsonArray
        GeoPoint(ll[0].jsonPrimitive.content.toDouble(), ll[1].jsonPrimitive.content.toDouble())
    }
}.getOrNull()

/** Render one FREEDRAW_LINE / FREEDRAW_TEXT object (from any client) onto the map. */
fun renderFreeDraw(map: MapView, g: TacticalObjectDto) {
    val notes = runCatching { Json.parseToJsonElement(g.notes).jsonObject }.getOrNull()
    val colorStr = notes?.get("color")?.jsonPrimitive?.content ?: "#EF4444"
    val color = runCatching { Color.parseColor(colorStr) }.getOrDefault(Color.RED)
    val density = map.resources.displayMetrics.density
    if (g.type == "FREEDRAW_LINE") {
        val coords = parseCoords(g.geometry) ?: return
        if (coords.size < 2) return
        val thick = notes?.get("thick")?.jsonPrimitive?.content?.toFloatOrNull() ?: 2f
        Polyline(map).apply {
            setPoints(coords)
            outlinePaint.color = color
            outlinePaint.strokeWidth = thick * density
            outlinePaint.isAntiAlias = true
            map.overlays.add(this)
        }
    } else {
        val text = notes?.get("text")?.jsonPrimitive?.content ?: return
        val pt = parseCoords(g.geometry)?.firstOrNull() ?: GeoPoint(g.latitude, g.longitude)
        Marker(map).apply {
            position = pt
            icon = textLabelDrawable(map, text, color, density)
            setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
            title = text
            map.overlays.add(this)
        }
    }
}

private fun textLabelDrawable(map: MapView, text: String, color: Int, density: Float): BitmapDrawable {
    val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        this.color = color
        textSize = 13f * density
        isFakeBoldText = true
    }
    val shadow = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        this.color = Color.BLACK
        textSize = 13f * density
        isFakeBoldText = true
        setShadowLayer(3f, 0f, 0f, Color.BLACK)
    }
    val pad = 4f * density
    val w = (paint.measureText(text) + pad * 2).toInt().coerceAtLeast(1)
    val h = (paint.textSize + pad * 2).toInt().coerceAtLeast(1)
    val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
    val canvas = Canvas(bmp)
    val baseline = h - pad
    canvas.drawText(text, pad, baseline, shadow)
    canvas.drawText(text, pad, baseline, paint)
    return BitmapDrawable(map.resources, bmp)
}
