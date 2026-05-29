package com.arrow.tactical.map

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request

@Serializable
data class RainViewerResponse(
    val radar: RadarData,
    val satellite: SatelliteData,
)

@Serializable
data class RadarData(
    val past: List<RainViewerFrame> = emptyList(),
    val nowcast: List<RainViewerFrame> = emptyList(),
)

@Serializable
data class SatelliteData(
    val infrared: List<RainViewerFrame> = emptyList(),
)

@Serializable
data class RainViewerFrame(val time: Long, val path: String)

data class WeatherFrames(
    val radarFrames: List<RainViewerFrame>,
    val nowcastStartIndex: Int,
    val satFrame: RainViewerFrame?,
)

class WeatherRepository(private val httpClient: OkHttpClient) {
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun fetchFrames(): Result<WeatherFrames> = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder()
                .url("https://api.rainviewer.com/public/weather-maps.json")
                .build()
            val body = httpClient.newCall(req).execute().use { resp ->
                resp.body?.string() ?: error("empty body from RainViewer API")
            }
            val rv = json.decodeFromString<RainViewerResponse>(body)
            val radar = rv.radar.past + rv.radar.nowcast
            WeatherFrames(
                radarFrames = radar,
                nowcastStartIndex = rv.radar.past.size,
                satFrame = rv.satellite.infrared.lastOrNull(),
            )
        }
    }
}
