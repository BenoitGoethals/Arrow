package com.arrow.tactical.map

import android.content.Context
import android.graphics.Canvas
import org.osmdroid.tileprovider.MapTileProviderBase
import org.osmdroid.tileprovider.tilesource.XYTileSource
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.TilesOverlay

// RainViewer only serves real tiles at zoom 0-7.
// maxZoomLevel=7 stops OSMdroid requesting zoom 8+ which returns an error image.
// The standard XYTileSource URL mechanism generates the correct URL without any override:
//   getBaseUrl() + z + "/" + x + "/" + y + imageFilenameEnding
//   → https://tilecache.rainviewer.com{path}/256/{z}/{x}/{y}/1/1_0.png
class RainViewerTileSource(
    framePath: String,
    isSatellite: Boolean = false,
) : XYTileSource(
    "RV${Math.abs(framePath.hashCode())}",
    0, 7, 256,
    if (isSatellite) "/0/0_0.png" else "/1/1_0.png",
    arrayOf("https://tilecache.rainviewer.com$framePath/256/"),
)

/** TilesOverlay with configurable alpha so weather layers can be made semi-transparent. */
class WeatherTilesOverlay(
    provider: MapTileProviderBase,
    context: Context,
    var overlayAlpha: Float = 0.7f,
) : TilesOverlay(provider, context) {

    override fun draw(c: Canvas, osmv: MapView, shadow: Boolean) {
        if (shadow) return
        val alpha = (overlayAlpha * 255).toInt().coerceIn(0, 255)
        val count = c.saveLayerAlpha(0f, 0f, c.width.toFloat(), c.height.toFloat(), alpha)
        super.draw(c, osmv, shadow)
        c.restoreToCount(count)
    }
}
