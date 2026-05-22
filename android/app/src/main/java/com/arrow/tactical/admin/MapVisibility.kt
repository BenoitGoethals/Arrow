package com.arrow.tactical.admin

import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.preferencesDataStore
import com.arrow.tactical.network.ApiClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

/**
 * Per-device map + notification visibility preferences.
 *
 * Two independent axes:
 *  * Map flags (``tacticalObjects`` … ``overlays``) — gate the tactical-map render.
 *  * Notification flags (``notifChat`` … ``notifStreams``) — gate the toast
 *    cards and Android system notifications.
 *
 * Defaults are all-on so a missing key never silences a critical channel.
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
    @SerialName("notif_chat")          val notifChat:         Boolean = true,
    @SerialName("notif_fire_missions") val notifFireMissions: Boolean = true,
    @SerialName("notif_alerts")        val notifAlerts:       Boolean = true,
    @SerialName("notif_streams")       val notifStreams:      Boolean = true,
    @SerialName("updated_at")          val updatedAt:         String  = "",
)

/** The 12 flags as a stable iterable — used by the settings UI + DataStore IO. */
data class VisibilityFlag(
    val key: String,
    val label: String,
    val description: String,
    val icon: String,
    val isNotificationAxis: Boolean,
    val get: (MapVisibility) -> Boolean,
    val set: (MapVisibility, Boolean) -> MapVisibility,
)

val MAP_FLAGS = listOf(
    VisibilityFlag("tactical_objects", "Tactical objects",
        "Enemies, POIs, objectives, tactical control graphics, FLET, ATK_AXIS, …",
        "🎯", false, { it.tacticalObjects }, { v, b -> v.copy(tacticalObjects = b) }),
    VisibilityFlag("operators", "Operators",
        "Friendly position markers (live tracking).",
        "👥", false, { it.operators }, { v, b -> v.copy(operators = b) }),
    VisibilityFlag("fire_missions", "Fire missions",
        "CFF markers and impact splashes on the map.",
        "💥", false, { it.fireMissions }, { v, b -> v.copy(fireMissions = b) }),
    VisibilityFlag("alerts", "Alerts",
        "TIC / MEDICAL / EVAC / LOST_COMMS marker pulses and auto-zoom.",
        "🚨", false, { it.alerts }, { v, b -> v.copy(alerts = b) }),
    VisibilityFlag("reports", "Reports",
        "SPOT / CBRN report markers (drives the CBRN hazard zones too).",
        "📋", false, { it.reports }, { v, b -> v.copy(reports = b) }),
    VisibilityFlag("cot_tracks", "CoT tracks",
        "Foreign-UID Cursor-on-Target tracks (simulator / ATAK peers).",
        "📡", false, { it.cotTracks }, { v, b -> v.copy(cotTracks = b) }),
    VisibilityFlag("kml_layers", "KML layers",
        "Imported KML/KMZ overlay features (points / lines / polygons).",
        "📂", false, { it.kmlLayers }, { v, b -> v.copy(kmlLayers = b) }),
    VisibilityFlag("overlays", "Saved overlays",
        "Named bundles of TacticalObject ids used as map filters.",
        "📚", false, { it.overlays }, { v, b -> v.copy(overlays = b) }),
)

val NOTIF_FLAGS = listOf(
    VisibilityFlag("notif_chat", "Chat notifications",
        "System notifications for incoming chat messages.",
        "💬", true, { it.notifChat }, { v, b -> v.copy(notifChat = b) }),
    VisibilityFlag("notif_fire_missions", "Fire-mission notifications",
        "FM call-for-fire toast cards (and audio alarm).",
        "🎯", true, { it.notifFireMissions }, { v, b -> v.copy(notifFireMissions = b) }),
    VisibilityFlag("notif_alerts", "TIC / alert notifications",
        "TIC / MEDICAL / EVAC / LOST_COMMS / DRONE_SPOTTED snackbars + voice alarms.",
        "🚨", true, { it.notifAlerts }, { v, b -> v.copy(notifAlerts = b) }),
    VisibilityFlag("notif_streams", "Stream notifications",
        "Live-stream toast notifications (operator goes live / ends stream).",
        "🎥", true, { it.notifStreams }, { v, b -> v.copy(notifStreams = b) }),
)

val ALL_VIS_FLAGS = MAP_FLAGS + NOTIF_FLAGS


/**
 * Per-device preferences for [MapVisibility]. Sourced from DataStore so
 * every operator on this device has their own choices, persisted across
 * restarts. The first time a flag is missing from the store we fall back to
 * the server's (admin-controlled) default via [seedFromServer].
 */
class MapVisibilityRepository(
    private val context: Context,
    private val api: ApiClient,
) {

    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }
    private val _flow = MutableStateFlow(MapVisibility())
    val flow: StateFlow<MapVisibility> = _flow.asStateFlow()
    val current: MapVisibility get() = _flow.value

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    init {
        // Push DataStore changes into the StateFlow.
        scope.launch {
            context.visStore.data.map { it.toMapVisibility() }.collect { v ->
                _flow.value = v
            }
        }
    }

    /** Pull the admin-controlled defaults from the server and seed DataStore
     *  ONLY for keys that have never been written by this operator. Called
     *  from the SettingsScreen "Reset to defaults" button. */
    suspend fun resetToServerDefaults(): Result<MapVisibility> = runCatching {
        val r = api.get("/admin/map-visibility")
        if (!r.ok) error("HTTP ${r.code}")
        val v = json.decodeFromString<MapVisibility>(r.body)
        context.visStore.edit { prefs ->
            for (f in ALL_VIS_FLAGS) {
                prefs[booleanPreferencesKey(f.key)] = f.get(v)
            }
        }
        v
    }

    /** First-run seeding — if no key is set yet, ask the server for defaults. */
    suspend fun seedFromServerIfEmpty() {
        val prefs = context.visStore.data.first()
        val needsSeed = ALL_VIS_FLAGS.none { booleanPreferencesKey(it.key) in prefs }
        if (needsSeed) runCatching { resetToServerDefaults() }
    }

    /** Toggle a single flag on this device. */
    suspend fun setFlag(key: String, value: Boolean) {
        context.visStore.edit { it[booleanPreferencesKey(key)] = value }
    }

    /** Bulk all-on / all-off helper used by the Settings screen. */
    suspend fun setAll(value: Boolean) {
        context.visStore.edit { prefs ->
            for (f in ALL_VIS_FLAGS) prefs[booleanPreferencesKey(f.key)] = value
        }
    }

    /** Back-compat shim for the previous WS-driven design. No-op: changes
     *  are now per-device and don't come from the server. */
    fun applyServerEvent(@Suppress("UNUSED_PARAMETER") evt: JsonObject) {}

    /** Back-compat shim — refresh now just re-emits whatever DataStore has. */
    suspend fun refresh(): Result<MapVisibility> = runCatching {
        seedFromServerIfEmpty()
        _flow.value
    }

    private fun Preferences.toMapVisibility(): MapVisibility {
        var v = MapVisibility()
        for (f in ALL_VIS_FLAGS) {
            val k = booleanPreferencesKey(f.key)
            if (k in this) v = f.set(v, this[k]!!)
        }
        return v
    }
}

private val Context.visStore by preferencesDataStore(name = "arrow_visibility")
