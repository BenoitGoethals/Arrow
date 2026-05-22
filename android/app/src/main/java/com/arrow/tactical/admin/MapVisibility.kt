package com.arrow.tactical.admin

import com.arrow.tactical.network.ApiClient
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * Mirrors the server's ``MapVisibility`` row exactly (see
 * ``backend/storage/models.py``). Two independent axes:
 *
 *  * Map flags (``tacticalObjects`` … ``overlays``) — gate what's drawn on
 *    the tactical map canvas.
 *  * Notification flags (``notifChat`` … ``notifStreams``) — gate the
 *    right-side toast / system-notification stack.
 *
 * Defaults are all-on so a suppressed value can never lock an operator out
 * of a critical channel before the initial GET resolves.
 */
@Serializable
data class MapVisibility(
    @SerialName("tactical_objects") val tacticalObjects: Boolean = true,
    @SerialName("operators")        val operators:       Boolean = true,
    @SerialName("fire_missions")    val fireMissions:    Boolean = true,
    @SerialName("alerts")           val alerts:          Boolean = true,
    @SerialName("reports")          val reports:         Boolean = true,
    @SerialName("cot_tracks")       val cotTracks:       Boolean = true,
    @SerialName("kml_layers")       val kmlLayers:       Boolean = true,
    @SerialName("overlays")         val overlays:        Boolean = true,
    // Notification axis
    @SerialName("notif_chat")          val notifChat:         Boolean = true,
    @SerialName("notif_fire_missions") val notifFireMissions: Boolean = true,
    @SerialName("notif_alerts")        val notifAlerts:       Boolean = true,
    @SerialName("notif_streams")       val notifStreams:      Boolean = true,
    @SerialName("updated_at")          val updatedAt:         String  = "",
)

/**
 * Holds the singleton [MapVisibility] config. Refreshed by HTTP on init and
 * whenever the WS dispatcher in MapScreen forwards a ``map-visibility``
 * event via [applyServerEvent]. Every consumer collects [flow] so the
 * downstream UI / notification logic reacts instantly to admin changes.
 */
class MapVisibilityRepository(private val api: ApiClient) {

    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }
    private val _flow = MutableStateFlow(MapVisibility())
    val flow: StateFlow<MapVisibility> = _flow.asStateFlow()
    val current: MapVisibility get() = _flow.value

    /** Pull the latest config from the server. Errors leave defaults in place. */
    suspend fun refresh(): Result<MapVisibility> = runCatching {
        val r = api.get("/admin/map-visibility")
        if (!r.ok) error("HTTP ${r.code}")
        val v = json.decodeFromString<MapVisibility>(r.body)
        _flow.value = v
        v
    }

    /** Apply a ``{channel:'map-visibility', event:'updated', data:{...}}``
     *  event from the WS bridge — only the fields present in ``data`` are
     *  merged so a partial broadcast doesn't wipe other flags. */
    fun applyServerEvent(evt: JsonObject) {
        val data = evt["data"]?.jsonObject ?: return
        _flow.update { cur ->
            fun b(k: String, fallback: Boolean) =
                data[k]?.jsonPrimitive?.booleanOrNull ?: fallback
            cur.copy(
                tacticalObjects   = b("tactical_objects",     cur.tacticalObjects),
                operators         = b("operators",            cur.operators),
                fireMissions      = b("fire_missions",        cur.fireMissions),
                alerts            = b("alerts",               cur.alerts),
                reports           = b("reports",              cur.reports),
                cotTracks         = b("cot_tracks",           cur.cotTracks),
                kmlLayers         = b("kml_layers",           cur.kmlLayers),
                overlays          = b("overlays",             cur.overlays),
                notifChat         = b("notif_chat",           cur.notifChat),
                notifFireMissions = b("notif_fire_missions",  cur.notifFireMissions),
                notifAlerts       = b("notif_alerts",         cur.notifAlerts),
                notifStreams      = b("notif_streams",        cur.notifStreams),
                updatedAt         = data["updated_at"]?.jsonPrimitive?.content
                                    ?: cur.updatedAt,
            )
        }
    }
}
