package com.arrow.tactical.offline

import android.content.Context
import java.io.File

/**
 * Offline tile cache lives in the app's external files dir under `osmdroid/tiles`.
 * OSMdroid picks this up automatically once configured at app startup.
 */
object OfflineMaps {
    fun cacheDir(context: Context): File {
        val dir = File(context.getExternalFilesDir(null), "osmdroid/tiles")
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    fun cacheSizeBytes(context: Context): Long =
        cacheDir(context).walkTopDown().filter { it.isFile }.sumOf { it.length() }
}
