package com.arrow.tactical.map

import android.content.Context
import android.graphics.Canvas
import org.osmdroid.tileprovider.MapTileProviderBase
import org.osmdroid.tileprovider.tilesource.XYTileSource
import org.osmdroid.util.MapTileIndex
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.TilesOverlay

class RainViewerTileSource(
    private val framePath: String,
    private val isSatellite: Boolean = false,
) : XYTileSource(
    "RV${framePath.hashCode()}",
    0, 18, 256, ".png", emptyArray(),
) {
    override fun getTileURLString(pMapTileIndex: Long): String {
        val z = MapTileIndex.getZoom(pMapTileIndex)
        val x = MapTileIndex.getX(pMapTileIndex)
        val y = MapTileIndex.getY(pMapTileIndex)
        return if (isSatellite)
            "https://tilecache.rainviewer.com$framePath/256/$z/$x/$y/0/0_0.png"
        else
            "https://tilecache.rainviewer.com$framePath/256/$z/$x/$y/1/1_0.png"
    }
}

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
