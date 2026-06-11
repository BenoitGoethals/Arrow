package com.arrow.tactical.kml

import android.graphics.Color as AndroidColor
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Overlay
import org.osmdroid.views.overlay.Polygon
import org.osmdroid.views.overlay.Polyline

/**
 * Build a flat list of OSMdroid overlays from a parsed KML layer.
 *
 * The list is intentionally not added to the [MapView] here — the caller owns
 * the lifecycle (add/remove on visibility toggle) and the z-order relative to
 * the other tactical overlays.
 */
/** Sentinel attached to every KML overlay so the tactical-marker wipe in
 *  [com.arrow.tactical.map.ui.MapScreen] knows to leave them alone. */
const val KML_OVERLAY_TAG: String = "arrow.kml-overlay"

fun isKmlOverlay(o: Overlay): Boolean = when (o) {
    is Marker   -> o.relatedObject == KML_OVERLAY_TAG
    is Polyline -> o.relatedObject == KML_OVERLAY_TAG
    is Polygon  -> o.relatedObject == KML_OVERLAY_TAG
    else        -> false
}

fun buildKmlOverlays(map: MapView, features: List<KmlFeature>): List<Overlay> {
    val out = ArrayList<Overlay>(features.size)
    val defaultColor = AndroidColor.parseColor("#34D399")  // teal

    for (f in features) {
        val stroke = parseHex(f.strokeColor) ?: defaultColor
        // Apply ~25% alpha for polygon fills — matches the web client's
        // fillOpacity=0.18 so a layer looks recognisable across both viewers.
        val fill   = withAlpha(parseHex(f.fillColor) ?: stroke, 0x40)
        val width  = (f.strokeWidth ?: 2.0).toFloat().coerceAtLeast(1f)

        when (f.type) {
            KmlFeature.Type.POINT -> {
                val (lat, lon) = f.coords[0]
                val marker = Marker(map).apply {
                    position = GeoPoint(lat, lon)
                    title    = f.name.ifBlank { "KML point" }
                    snippet  = f.description.take(280)
                    // OSMdroid's default marker icon is a fine pin for KML POIs;
                    // a custom drawable per layer would need style→bitmap caching.
                    setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
                    relatedObject = KML_OVERLAY_TAG
                    // CRITICAL: don't swallow the tap. A KML marker that consumes
                    // taps blocks the MapEventsOverlay's singleTapConfirmed —
                    // which means the operator's radial menu never opens when
                    // they tap near a placemark. Returning false from the click
                    // listener lets the tap propagate; the info window is then
                    // suppressed too, which is fine because the operator can
                    // still long-press the marker to inspect it via OSMdroid's
                    // standard handling, and the radial menu wins on a tap.
                    setOnMarkerClickListener { _, _ -> false }
                }
                out += marker
            }
            KmlFeature.Type.LINE -> {
                val poly = Polyline(map).apply {
                    setPoints(f.coords.map { GeoPoint(it[0], it[1]) })
                    outlinePaint.color       = stroke
                    outlinePaint.strokeWidth = width * 2f
                    title = f.name
                    if (f.description.isNotBlank()) snippet = f.description.take(280)
                    relatedObject = KML_OVERLAY_TAG
                }
                out += poly
            }
            KmlFeature.Type.POLYGON -> {
                val poly = Polygon(map).apply {
                    points = f.coords.map { GeoPoint(it[0], it[1]) }
                    outlinePaint.color       = stroke
                    outlinePaint.strokeWidth = width * 2f
                    fillPaint.color          = fill
                    title = f.name
                    if (f.description.isNotBlank()) snippet = f.description.take(280)
                    relatedObject = KML_OVERLAY_TAG
                }
                out += poly
            }
        }
    }
    return out
}

private fun parseHex(s: String?): Int? {
    if (s.isNullOrBlank()) return null
    return runCatching { AndroidColor.parseColor(s) }.getOrNull()
}

private fun withAlpha(color: Int, alpha: Int): Int =
    (color and 0x00FFFFFF) or ((alpha and 0xFF) shl 24)
