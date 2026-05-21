package com.arrow.tactical.kml

import com.arrow.tactical.network.ApiClient
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** Summary returned by GET /kml-layers. */
@Serializable
data class KmlLayerDto(
    val id: Int,
    val name: String,
    val description: String = "",
    val visible: Boolean = true,
    @SerialName("uploaded_by") val uploadedBy: Int = 0,
    @SerialName("uploaded_at") val uploadedAt: String = "",
    @SerialName("feature_count") val featureCount: Int = 0,
    /** Server returns [min_lon, min_lat, max_lon, max_lat]. May be null. */
    val bbox: List<Double>? = null,
)

/** Normalised feature pulled out of the server's JSON envelope. */
data class KmlFeature(
    val type: Type,
    val name: String,
    val description: String,
    /** Web ``#rrggbb`` or null when the source KML had no style. */
    val strokeColor: String?,
    val fillColor:   String?,
    val strokeWidth: Double?,
    /** POINT → 1 vertex; LINE/POLYGON → many. Always (lat, lon). */
    val coords: List<DoubleArray>,
) {
    enum class Type { POINT, LINE, POLYGON }
}

class KmlLayerRepository(private val api: ApiClient) {

    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }

    suspend fun list(): Result<List<KmlLayerDto>> = runCatching {
        val r = api.get("/kml-layers")
        if (!r.ok) error("HTTP ${r.code}")
        json.decodeFromString<List<KmlLayerDto>>(r.body)
    }

    /** Fetches one layer and unpacks its features. */
    suspend fun features(layerId: Int): Result<List<KmlFeature>> = runCatching {
        val r = api.get("/kml-layers/$layerId")
        if (!r.ok) error("HTTP ${r.code}")
        val obj = json.parseToJsonElement(r.body).jsonObject
        val arr = obj["features"]?.jsonArray ?: JsonArray(emptyList())
        arr.mapNotNull { e -> parseFeature(e.jsonObject) }
    }

    suspend fun setVisible(layerId: Int, visible: Boolean): Result<Unit> = runCatching {
        val r = api.patchJson("/kml-layers/$layerId", """{"visible":$visible}""")
        if (!r.ok) error("HTTP ${r.code}")
    }

    /** One-shot decoding of {type, name, description, style, coords}. */
    private fun parseFeature(o: JsonObject): KmlFeature? {
        val type = when (o["type"]?.jsonPrimitive?.contentOrNull?.uppercase()) {
            "POINT"   -> KmlFeature.Type.POINT
            "LINE"    -> KmlFeature.Type.LINE
            "POLYGON" -> KmlFeature.Type.POLYGON
            else      -> return null
        }
        val name = o["name"]?.jsonPrimitive?.contentOrNull.orEmpty()
        val desc = o["description"]?.jsonPrimitive?.contentOrNull.orEmpty()

        val style = o["style"]?.jsonObject
        val stroke = style?.get("stroke")?.jsonPrimitive?.contentOrNull
        val fill   = style?.get("fill")?.jsonPrimitive?.contentOrNull
        val width  = style?.get("width")?.jsonPrimitive?.doubleOrNull

        val coords: List<DoubleArray> = when (type) {
            KmlFeature.Type.POINT -> {
                val arr = o["coords"]?.jsonArray ?: return null
                if (arr.size < 2) return null
                listOf(doubleArrayOf(
                    (arr[0] as? JsonPrimitive)?.doubleOrNull ?: return null,
                    (arr[1] as? JsonPrimitive)?.doubleOrNull ?: return null,
                ))
            }
            else -> {
                val arr = o["coords"]?.jsonArray ?: return null
                arr.mapNotNull { e ->
                    val pair = e.jsonArray
                    if (pair.size < 2) return@mapNotNull null
                    val lat = (pair[0] as? JsonPrimitive)?.doubleOrNull ?: return@mapNotNull null
                    val lon = (pair[1] as? JsonPrimitive)?.doubleOrNull ?: return@mapNotNull null
                    doubleArrayOf(lat, lon)
                }
            }
        }
        if (coords.isEmpty()) return null

        return KmlFeature(type, name, desc, stroke, fill, width, coords)
    }
}
