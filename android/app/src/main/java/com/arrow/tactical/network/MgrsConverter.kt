package com.arrow.tactical.network

import kotlin.math.*

/**
 * Military Grid Reference System (MGRS) ↔ WGS-84 lat/lon conversion.
 *
 * Implements DMATM 8358.1 on the WGS-84 ellipsoid.
 * Supports the full 80°S – 84°N range.
 */
object MgrsConverter {

    // WGS-84 ellipsoid
    private const val A   = 6378137.0
    private const val F   = 1.0 / 298.257223563
    private const val E2  = 2 * F - F * F
    private const val E4  = E2 * E2
    private const val E6  = E4 * E2
    private const val EP2 = E2 / (1.0 - E2)
    private const val K0  = 0.9996

    private const val LAT_BANDS = "CDEFGHJKLMNPQRSTUVWX"

    // 100 km column letters per zone set (6 sets cycling every 6 zones)
    private val SET_COLS = arrayOf("ABCDEFGH", "JKLMNPQR", "STUVWXYZ")

    // 100 km row letters for odd/even zones (20 letters, repeating)
    private const val ROW_ODD  = "ABCDEFGHJKLMNPQRSTUV"
    private const val ROW_EVEN = "FGHJKLMNPQRSTUVABCDE"

    // ── Public API ─────────────────────────────────────────────────────────

    /** Encode WGS-84 lat/lon to MGRS string.  [accuracy] = digits per component (5 = 1 m). */
    fun encode(lat: Double, lon: Double, accuracy: Int = 5): String {
        require(lat in -80.0..84.0) { "Latitude $lat outside MGRS range" }

        val zone = utmZone(lat, lon)
        val band = latBand(lat)
        val (easting, northing) = latLonToUtm(lat, lon, zone)

        val set = (zone - 1) % 3
        val col = SET_COLS[set][(floor(easting / 100_000).toInt() - 1).coerceIn(0, 7)]
        val row = (if (zone % 2 == 1) ROW_ODD else ROW_EVEN)[(floor(northing / 100_000).toInt() % 20)]

        val eStr = (easting  % 100_000).toInt().toString().padStart(5, '0').take(accuracy)
        val nStr = (northing % 100_000).toInt().toString().padStart(5, '0').take(accuracy)

        return "$zone$band$col$row $eStr$nStr"
    }

    /** Decode an MGRS string to WGS-84 (lat, lon). */
    fun decode(mgrs: String): Pair<Double, Double> {
        val s = mgrs.replace(" ", "").uppercase()

        // Parse zone number (1-2 digits)
        var i = 0
        while (i < s.length && s[i].isDigit()) i++
        val zone = s.substring(0, i).toInt()
        val band = s[i++]

        val sq1 = s[i++]  // column letter
        val sq2 = s[i++]  // row letter

        val numDigits = s.length - i
        val half = numDigits / 2
        val eStr = s.substring(i, i + half).padEnd(5, '0')
        val nStr = s.substring(i + half).padEnd(5, '0')

        // Recover 100 km easting
        val set = (zone - 1) % 3
        val colIdx = SET_COLS[set].indexOf(sq1).also { check(it >= 0) { "Bad column letter $sq1" } }
        val e100 = (colIdx + 1) * 100_000.0

        // Recover 100 km northing (row letters repeat every 2 000 000 m)
        val rowLetters = if (zone % 2 == 1) ROW_ODD else ROW_EVEN
        val rowIdx = rowLetters.indexOf(sq2).also { check(it >= 0) { "Bad row letter $sq2" } }
        val n100Base = rowIdx * 100_000.0

        // Snap to the closest valid 2 000 000 m band for this latitude band
        val approxN = bandMinNorthing(band)
        var n100 = n100Base
        while (n100 < approxN - 100_000) n100 += 2_000_000.0
        if (n100 - approxN > 1_000_000) n100 -= 2_000_000.0

        val easting  = e100 + eStr.toDouble()
        val northing = n100 + nStr.toDouble()

        return utmToLatLon(zone, band >= 'N', easting, northing)
    }

    // ── UTM ────────────────────────────────────────────────────────────────

    private fun latLonToUtm(lat: Double, lon: Double, zone: Int): Pair<Double, Double> {
        val latR = Math.toRadians(lat)
        val lonR = Math.toRadians(lon)
        val lon0R = Math.toRadians(((zone - 1) * 6 - 180 + 3).toDouble())

        val n = A / sqrt(1.0 - E2 * sin(latR).pow(2))
        val t = tan(latR).pow(2)
        val c = EP2 * cos(latR).pow(2)
        val a = cos(latR) * (lonR - lon0R)

        val m = A * (
            (1.0 - E2 / 4.0 - 3 * E4 / 64.0 - 5 * E6 / 256.0) * latR
            - (3.0 * E2 / 8.0 + 3 * E4 / 32.0 + 45 * E6 / 1024.0) * sin(2 * latR)
            + (15.0 * E4 / 256.0 + 45 * E6 / 1024.0) * sin(4 * latR)
            - (35.0 * E6 / 3072.0) * sin(6 * latR)
        )

        val easting = K0 * n * (
            a + (1 - t + c) * a.pow(3) / 6.0
            + (5 - 18 * t + t * t + 72 * c - 58 * EP2) * a.pow(5) / 120.0
        ) + 500_000.0

        var northing = K0 * (
            m + n * tan(latR) * (
                a.pow(2) / 2.0
                + (5 - t + 9 * c + 4 * c * c) * a.pow(4) / 24.0
                + (61 - 58 * t + t * t + 600 * c - 330 * EP2) * a.pow(6) / 720.0
            )
        )
        if (lat < 0) northing += 10_000_000.0

        return easting to northing
    }

    private fun utmToLatLon(zone: Int, northern: Boolean, easting: Double, northing: Double): Pair<Double, Double> {
        val x   = easting - 500_000.0
        val y   = if (northern) northing else northing - 10_000_000.0
        val lon0 = Math.toRadians(((zone - 1) * 6 - 180 + 3).toDouble())

        val e1 = (1 - sqrt(1 - E2)) / (1 + sqrt(1 - E2))
        val m  = y / K0
        val mu = m / (A * (1 - E2 / 4 - 3 * E4 / 64 - 5 * E6 / 256))

        val latR = mu +
            (3 * e1 / 2 - 27 * e1.pow(3) / 32) * sin(2 * mu) +
            (21 * e1.pow(2) / 16 - 55 * e1.pow(4) / 32) * sin(4 * mu) +
            (151 * e1.pow(3) / 96) * sin(6 * mu) +
            (1097 * e1.pow(4) / 512) * sin(8 * mu)

        val n1 = A / sqrt(1 - E2 * sin(latR).pow(2))
        val t1 = tan(latR).pow(2)
        val c1 = EP2 * cos(latR).pow(2)
        val r1 = A * (1 - E2) / (1 - E2 * sin(latR).pow(2)).pow(1.5)
        val d  = x / (n1 * K0)

        val lat = latR - (n1 * tan(latR) / r1) * (
            d.pow(2) / 2.0
            - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * EP2) * d.pow(4) / 24.0
            + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * EP2 - 3 * c1 * c1) * d.pow(6) / 720.0
        )
        val lon = lon0 + (
            d - (1 + 2 * t1 + c1) * d.pow(3) / 6.0
            + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * EP2 + 24 * t1 * t1) * d.pow(5) / 120.0
        ) / cos(latR)

        return Math.toDegrees(lat) to Math.toDegrees(lon)
    }

    // ── Helpers ────────────────────────────────────────────────────────────

    private fun utmZone(lat: Double, lon: Double): Int {
        // Special zones for Norway / Svalbard
        if (lat in 56.0..64.0 && lon in 3.0..12.0) return 32
        if (lat in 72.0..84.0) return when {
            lon < 9  -> 31; lon < 21 -> 33; lon < 33 -> 35; lon < 42 -> 37
            else     -> ((lon + 180) / 6).toInt() + 1
        }
        return ((lon + 180) / 6).toInt() + 1
    }

    private fun latBand(lat: Double): Char =
        LAT_BANDS[((lat + 80) / 8).toInt().coerceIn(0, 19)]

    private fun bandMinNorthing(band: Char): Double {
        val idx = LAT_BANDS.indexOf(band)
        // Approximate minimum northing for this latitude band
        val minLat = idx * 8.0 - 80.0
        return if (minLat >= 0) minLat * 110_574 else (minLat * 110_574 + 10_000_000)
    }
}
