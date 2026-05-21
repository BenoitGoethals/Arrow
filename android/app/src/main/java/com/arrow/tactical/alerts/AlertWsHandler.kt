package com.arrow.tactical.alerts

import android.content.Context
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.snapshots.SnapshotStateMap
import com.arrow.tactical.network.MgrsConverter
import com.arrow.tactical.network.OperatorDto
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker

/**
 * Dispatch an ``{channel:"alert", event:"triggered"|"ack", data:{...}}`` event.
 *
 * On ``triggered`` for an alert with coordinates:
 *  - drops a [AlertMarker] on the map and tracks it in [alertMarkers];
 *  - animates the camera to the contact at zoom 16;
 *  - shows a snackbar with the alert TYPE + originating callsign + MGRS so
 *    the BC can read the grid straight off the screen.
 *
 * On ``ack`` it removes the marker. Missing/null fields are tolerated — a
 * malformed event is dropped silently rather than crashing the WS loop.
 */
suspend fun handleAlertWsEvent(
    evt: JsonObject,
    map: MapView?,
    ops: List<OperatorDto>,
    alertMarkers: SnapshotStateMap<Int, Marker>,
    snackbarHostState: SnackbarHostState,
    context: Context,
) {
    val event = evt["event"]?.jsonPrimitive?.contentOrNull ?: return
    val data  = evt["data"]?.jsonObject ?: return
    val id    = data["id"]?.jsonPrimitive?.intOrNull ?: return

    if (event == "ack") {
        alertMarkers.remove(id)?.let { m ->
            map?.overlays?.remove(m)
            map?.invalidate()
        }
        return
    }
    if (event != "triggered") return

    val lat = data["latitude"]?.jsonPrimitive?.doubleOrNull
    val lon = data["longitude"]?.jsonPrimitive?.doubleOrNull
    val type = data["type"]?.jsonPrimitive?.contentOrNull ?: "ALERT"
    val opId = data["operator_id"]?.jsonPrimitive?.intOrNull
    val callsign = ops.firstOrNull { it.id == opId }?.callsign ?: "op#${opId ?: "?"}"

    val mgrs = if (lat != null && lon != null) {
        runCatching { MgrsConverter.encode(lat, lon) }.getOrNull() ?: "—"
    } else "—"

    // Drop / replace the marker first so the snackbar always shows after the
    // pin lands (rough ordering — Compose recomposition is async but cheap).
    if (lat != null && lon != null && map != null) {
        alertMarkers.remove(id)?.let { map.overlays.remove(it) }
        val marker = AlertMarker.build(
            map = map, res = context.resources,
            lat = lat, lon = lon,
            type = type,
            title  = "⚠ $type — $callsign",
            snippet = "Grid: $mgrs",
        )
        map.overlays.add(marker)
        alertMarkers[id] = marker
        // Force-pan to the contact at a useful tactical zoom. We pick 16 —
        // close enough to read terrain features but still shows the adjacent
        // grid square so the BC keeps spatial context.
        map.controller.animateTo(GeoPoint(lat, lon), 16.0, null)
        marker.showInfoWindow()
        map.invalidate()
    }

    // Snackbar — read the grid aloud or radio it in without leaving the map.
    val msg = if (lat != null && lon != null) "$type · $callsign · $mgrs"
              else                            "$type · $callsign · (no position)"
    snackbarHostState.showSnackbar(message = msg, withDismissAction = true)
}
