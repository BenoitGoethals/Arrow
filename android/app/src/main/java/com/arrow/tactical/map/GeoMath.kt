package com.arrow.tactical.map

import org.osmdroid.util.GeoPoint
import kotlin.math.asin
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Small geodesy helpers used by the map's measurement tool. Spherical earth model
 * (R = 6 371 km) — accurate to within ~0.3 % at tactical distances, no extra deps.
 */
object GeoMath {
    private const val EARTH_RADIUS_M = 6_371_000.0

    /** Great-circle distance in metres between [a] and [b] (haversine formula). */
    fun distanceMeters(a: GeoPoint, b: GeoPoint): Double {
        val phi1 = Math.toRadians(a.latitude)
        val phi2 = Math.toRadians(b.latitude)
        val dPhi = Math.toRadians(b.latitude - a.latitude)
        val dLam = Math.toRadians(b.longitude - a.longitude)
        val h = sin(dPhi / 2).pow(2) + cos(phi1) * cos(phi2) * sin(dLam / 2).pow(2)
        return 2 * EARTH_RADIUS_M * asin(sqrt(h.coerceIn(0.0, 1.0)))
    }

    /**
     * Initial bearing (forward azimuth) from [a] toward [b], expressed in degrees
     * in the range [0, 360). 0 = north, 90 = east, etc.
     */
    fun bearingDegrees(a: GeoPoint, b: GeoPoint): Double {
        val phi1 = Math.toRadians(a.latitude)
        val phi2 = Math.toRadians(b.latitude)
        val dLam = Math.toRadians(b.longitude - a.longitude)
        val y = sin(dLam) * cos(phi2)
        val x = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(dLam)
        val theta = atan2(y, x)
        return (Math.toDegrees(theta) + 360.0) % 360.0
    }

    /** NATO mils — 6400 per full circle. Used on artillery / mortar fire-control. */
    fun degreesToMils(deg: Double): Double = deg * 6400.0 / 360.0

    /** Human-readable distance with adaptive unit (m / km, sane precision). */
    fun formatDistance(m: Double): String = when {
        m < 1_000  -> "%.0f m".format(m)
        m < 10_000 -> "%.2f km".format(m / 1000.0)
        else       -> "%.1f km".format(m / 1000.0)
    }
}
