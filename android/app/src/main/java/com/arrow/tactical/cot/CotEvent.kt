package com.arrow.tactical.cot

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * Minimal Cursor-on-Target XML serialiser. Mirrors backend.cot.cot.CotEvent so events
 * created on-device can be sent to the backend or any TAK-compatible endpoint.
 */
data class CotEvent(
    val uid: String,
    val type: String,           // e.g. "a-f-G-U-C" (friendly ground unit combat)
    val lat: Double,
    val lon: Double,
    val hae: Double = 0.0,
    val ce: Double = 9_999_999.0,
    val le: Double = 9_999_999.0,
    val callsign: String = "",
    val staleSeconds: Int = 60,
) {
    fun toXml(now: Date = Date()): String {
        val isoFmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }
        val start = isoFmt.format(now)
        val stale = isoFmt.format(Date(now.time + staleSeconds * 1000L))

        val detail = if (callsign.isNotEmpty()) {
            "<detail><contact callsign=\"${esc(callsign)}\"/></detail>"
        } else ""

        return """<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="${esc(uid)}" type="${esc(type)}" time="$start" start="$start" stale="$stale" how="m-g">
  <point lat="${"%.7f".format(Locale.US, lat)}" lon="${"%.7f".format(Locale.US, lon)}" hae="$hae" ce="$ce" le="$le"/>
  $detail
</event>""".trimIndent()
    }

    private fun esc(s: String) = s.replace("&", "&amp;").replace("\"", "&quot;").replace("<", "&lt;")
}
