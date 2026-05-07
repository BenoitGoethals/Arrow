package com.arrow.tactical.network

import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * CoT XML builder / parser for Arrow ↔ backend communication.
 *
 * CoT type mapping (MIL-STD-2525C):
 *   a-f-G-U-C      friendly ground unit combat      (OPERATOR)
 *   a-f-G-U-C-O    friendly ground unit officer     (BATTLE_CAPTAIN / ADMIN)
 *   a-h-G-U-C-I    hostile ground infantry
 *   a-h-G-U-C-A    hostile ground armour
 *   a-h-G-U-C-I-Z  hostile ground mechanised
 *   a-h-G-U-C-F    hostile ground field artillery
 *   a-h-G-U-C-D    hostile ground air-defence
 *   a-h-G-U-C-R    hostile ground recon
 *   a-h-G-E-V      hostile ground vehicle
 *   a-h-G-U-C-I-S  hostile ground sniper
 *   a-u-G          unknown ground
 *   a-n-G-I-N      neutral infrastructure / POI
 */
object CotProtocol {

    private val FMT: DateTimeFormatter =
        DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSSSSS'Z'")
            .withZone(ZoneOffset.UTC)

    // ── CoT type ↔ role ──────────────────────────────────────────────────────

    fun roleToCotType(role: String): String = when (role) {
        "BATTLE_CAPTAIN", "ADMIN" -> "a-f-G-U-C-O"
        else                      -> "a-f-G-U-C"
    }

    // ── SIDC ↔ CoT type ──────────────────────────────────────────────────────

    private val SIDC_TO_COT = mapOf(
        "SFGPUCI-----" to "a-f-G-U-C-I",
        "SFGPUCI----E" to "a-f-G-U-C-O",
        "SHGPUCI-----" to "a-h-G-U-C-I",
        "SHGPUCA-----" to "a-h-G-U-C-A",
        "SHGPUCIZ----" to "a-h-G-U-C-I-Z",
        "SHGPUCF-----" to "a-h-G-U-C-F",
        "SHGPUCD-----" to "a-h-G-U-C-D",
        "SHGPUCR-----" to "a-h-G-U-C-R",
        "SHGPEV------" to "a-h-G-E-V",
        "SHGPUCIS----" to "a-h-G-U-C-I-S",
        "SUGPU-------" to "a-u-G",
        "SNGPI-------" to "a-n-G-I-N",
    )

    private val COT_TO_SIDC: Map<String, String> = SIDC_TO_COT.entries
        .associate { (k, v) -> v to k }

    fun sidcToCotType(sidc: String): String =
        SIDC_TO_COT[sidc.uppercase()] ?: "a-u-G"

    fun cotTypeToSidc(cotType: String): String =
        COT_TO_SIDC[cotType] ?: "SUGPU-------"

    // ── XML builder ──────────────────────────────────────────────────────────

    /**
     * Build a CoT 2.0 position event as UTF-8 XML.
     *
     * @param callsign  operator callsign (used as uid suffix and contact)
     * @param role      Arrow role string → mapped to CoT affiliation type
     * @param lat       WGS-84 latitude
     * @param lon       WGS-84 longitude
     * @param hae       height above ellipsoid in metres
     * @param speed     ground speed m/s
     * @param course    true bearing degrees
     * @param team      team name for TAK group element
     */
    fun buildPositionEvent(
        callsign: String,
        role:     String,
        lat:      Double,
        lon:      Double,
        hae:      Double  = 0.0,
        speed:    Double  = 0.0,
        course:   Double  = 0.0,
        team:     String  = "",
    ): String {
        val cotType = roleToCotType(role)
        val now     = Instant.now()
        val stale   = now.plusSeconds(90)
        val ts      = FMT.format(now)
        val ss      = FMT.format(stale)
        val uid     = "ARROW.$callsign"

        return buildString {
            append("<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n")
            append("<event version='2.0'")
            append(" uid='${esc(uid)}'")
            append(" type='${esc(cotType)}'")
            append(" time='$ts'")
            append(" start='$ts'")
            append(" stale='$ss'")
            append(" how='m-g'>\n")
            append("  <point")
            append(" lat='${"%.7f".format(lat)}'")
            append(" lon='${"%.7f".format(lon)}'")
            append(" hae='${"%.1f".format(hae)}'")
            append(" ce='999999.0' le='999999.0'/>\n")
            append("  <detail>\n")
            append("    <uid Droid='${esc(callsign)}'/>\n")
            append("    <contact callsign='${esc(callsign)}'/>\n")
            append("    <track speed='${"%.2f".format(speed)}' course='${"%.1f".format(course)}'/>\n")
            if (team.isNotBlank()) {
                append("    <__group role='${esc(role)}' name='${esc(team)}'/>\n")
            }
            append("    <takv os='${android.os.Build.VERSION.SDK_INT}'")
            append(" version='1.0.0'")
            append(" device='${esc(android.os.Build.MODEL)}'")
            append(" platform='ARROW'/>\n")
            append("  </detail>\n")
            append("</event>")
        }
    }

    // ── XML parser (for CoT events from WebSocket cot_xml field) ─────────────

    data class ParsedCot(
        val uid:      String,
        val cotType:  String,
        val lat:      Double,
        val lon:      Double,
        val hae:      Double,
        val callsign: String,
        val speed:    Double,
        val course:   Double,
    )

    fun parseCotXml(xml: String): ParsedCot? = runCatching {
        val factory = javax.xml.parsers.DocumentBuilderFactory.newInstance()
        val doc     = factory.newDocumentBuilder()
            .parse(xml.byteInputStream(Charsets.UTF_8))
        val root    = doc.documentElement

        fun attr(el: org.w3c.dom.Element?, name: String, default: String = "") =
            el?.getAttribute(name)?.takeIf { it.isNotEmpty() } ?: default

        val point  = doc.getElementsByTagName("point").item(0) as? org.w3c.dom.Element
        val uid_el = doc.getElementsByTagName("uid").item(0)   as? org.w3c.dom.Element
        val contact= doc.getElementsByTagName("contact").item(0) as? org.w3c.dom.Element
        val track  = doc.getElementsByTagName("track").item(0) as? org.w3c.dom.Element

        val callsign = attr(contact, "callsign").ifEmpty { attr(uid_el, "Droid") }

        ParsedCot(
            uid      = root.getAttribute("uid"),
            cotType  = root.getAttribute("type"),
            lat      = attr(point, "lat", "0").toDouble(),
            lon      = attr(point, "lon", "0").toDouble(),
            hae      = attr(point, "hae", "0").toDouble(),
            callsign = callsign,
            speed    = attr(track, "speed",  "0").toDouble(),
            course   = attr(track, "course", "0").toDouble(),
        )
    }.getOrNull()

    // ── Helpers ───────────────────────────────────────────────────────────────

    private fun esc(s: String): String = s
        .replace("&",  "&amp;")
        .replace("'",  "&apos;")
        .replace("\"", "&quot;")
        .replace("<",  "&lt;")
        .replace(">",  "&gt;")
}
