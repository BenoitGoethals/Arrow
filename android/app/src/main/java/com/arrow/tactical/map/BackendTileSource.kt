package com.arrow.tactical.map

import org.osmdroid.tileprovider.tilesource.OnlineTileSourceBase
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.MapTileIndex

/**
 * OSMdroid tile source that fetches tiles from the Arrow backend's
 * /map/tiles/{name}/{z}/{x}/{y}.{ext} endpoint.
 *
 * Auth: the backend accepts the JWT either via an Authorization header or a
 * `?token=` query parameter. OSMdroid downloads tiles with its own internal
 * HTTP stack (not OkHttp), so the easiest portable approach is the query
 * parameter — same pattern the websocket endpoint uses.
 *
 * One instance per (backend URL + map name) pair. The JWT is baked into the
 * tile URL, so rebuild the source if the token rotates — the MapScreen's
 * LaunchedEffect already does this whenever the selected source changes.
 */
class BackendTileSource(
    private val sourceName: String,
    title: String,
    minZoom: Int,
    maxZoom: Int,
    format: String,                // "png" | "jpg" | "jpeg" | "webp"
    private val baseUrl: String,   // e.g. "http://10.0.2.2:6001"
    private val token: String,
) : OnlineTileSourceBase(
    /* aName            = */ title,
    /* aZoomMinLevel    = */ minZoom,
    /* aZoomMaxLevel    = */ maxZoom,
    /* aTileSizePixels  = */ 256,
    /* aImageFilenameEnding = */ ".$format",
    /* aBaseUrl         = */ arrayOf("$baseUrl/map/tiles/$sourceName/"),
) {
    private val ext: String = if (format.equals("jpeg", true)) "jpg" else format.lowercase()

    override fun getTileURLString(pMapTileIndex: Long): String {
        val z = MapTileIndex.getZoom(pMapTileIndex)
        val x = MapTileIndex.getX(pMapTileIndex)
        val y = MapTileIndex.getY(pMapTileIndex)
        val trimmedBase = baseUrl.trimEnd('/')
        return "$trimmedBase/map/tiles/$sourceName/$z/$x/$y.$ext?token=$token"
    }

    companion object {
        /** Built-in OSM fallback, used when the backend has no MBTiles or is unreachable. */
        val OSM_DEFAULT get() = TileSourceFactory.MAPNIK
    }
}
