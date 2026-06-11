package com.arrow.tactical.admin

import android.os.Process
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

data class LogEntry(
    val timestamp: String,
    val level:     String,   // V/D/I/W/E/A/F
    val tag:       String,
    val message:   String,
) {
    val isError: Boolean get() = level == "E" || level == "A" || level == "F"
}

/**
 * Reads the device logcat scoped to this app's PID.
 *
 * On Android, an app can read its own log lines without the privileged
 * `READ_LOGS` permission, so a one-shot `logcat -d` for the current PID
 * gives us the full in-memory ring buffer the system holds for us.
 */
class LogRepository {

    /** The full uncaught-exception trail is captured by [installCrashHandler]; logcat
     *  reads the rest. */
    suspend fun fetch(): List<LogEntry> = withContext(Dispatchers.IO) {
        val pid = Process.myPid()
        try {
            val proc = ProcessBuilder("logcat", "-d", "-v", "threadtime")
                .redirectErrorStream(true)
                .start()
            val text = proc.inputStream.bufferedReader().use { it.readText() }
            proc.waitFor()
            parse(text, pid)
        } catch (e: Exception) {
            listOf(
                LogEntry(
                    timestamp = "—",
                    level     = "E",
                    tag       = "LogRepository",
                    message   = "logcat read failed: ${e.message}",
                )
            )
        }
    }

    /** Clear logcat's in-memory ring buffer. May fail silently on hardened devices. */
    suspend fun clear() = withContext(Dispatchers.IO) {
        runCatching {
            ProcessBuilder("logcat", "-c").start().waitFor()
        }
        Unit
    }

    // threadtime example:
    // 11-09 13:02:05.723  4231  4231 W TAG     : message body
    private val LINE = Regex(
        """^(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+(\d+)\s+\d+\s+([VDIWEAF])\s+([^:]+):\s?(.*)$"""
    )

    private fun parse(text: String, ownPid: Int): List<LogEntry> {
        val out = ArrayList<LogEntry>(256)
        for (line in text.lineSequence()) {
            val m = LINE.matchEntire(line) ?: continue
            val (ts, pidStr, lvl, tag, msg) = m.destructured
            if (pidStr.toIntOrNull() != ownPid) continue
            out += LogEntry(ts, lvl, tag.trim(), msg)
        }
        // Most-recent first
        out.reverse()
        return out
    }

    companion object {
        /** Re-route uncaught exceptions to logcat so the admin viewer captures crashes. */
        fun installCrashHandler() {
            val prev = Thread.getDefaultUncaughtExceptionHandler()
            Thread.setDefaultUncaughtExceptionHandler { t, e ->
                Log.e("ARROW_CRASH", "Uncaught in ${t.name}", e)
                prev?.uncaughtException(t, e)
            }
        }
    }
}
