package com.arrow.tactical.map

import android.content.Context
import com.arrow.tactical.auth.TokenStore
import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.settings.SettingsRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.Request
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Backend-driven catalogue of base map sources. Mirrors `backend.map.router.MapSource`.
 *
 * `urlTemplate` is either:
 *  - an absolute URL (built-in OSM) → used verbatim by Leaflet, ignored on Android
 *    in favour of [BackendTileSource.OSM_DEFAULT]; OR
 *  - a backend path "/map/tiles/{name}/{z}/{x}/{y}.{ext}" → consumed by
 *    [BackendTileSource] using `name` and `format`.
 */
@Serializable
data class MapSourceDto(
    val name: String,
    val title: String,
    val type: String,
    val format: String,
    val min_zoom: Int,
    val max_zoom: Int,
    val bounds: List<Double>? = null,
    val center: List<Double>? = null,
    val attribution: String? = null,
    val url_template: String,
    val is_default: Boolean = false,
    val size_bytes: Long? = null,
    val downloadable: Boolean = false,
)

/**
 * Progress callback invoked on the calling coroutine's dispatcher.
 * @param bytesRead total bytes written so far
 * @param totalBytes total expected bytes, or -1 if Content-Length wasn't sent
 */
typealias DownloadProgress = (bytesRead: Long, totalBytes: Long) -> Unit

class MapSourceRepository(
    private val api: ApiClient,
    private val context: Context,
    private val tokenStore: TokenStore,
    private val settings: SettingsRepository,
) {

    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }

    /** Where downloaded .mbtiles archives live on the device. */
    fun localDir(): File {
        val dir = File(context.getExternalFilesDir(null), "maps")
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    fun localFile(name: String): File? {
        val f = File(localDir(), "$name.mbtiles")
        return if (f.exists() && f.length() > 0) f else null
    }

    fun listLocal(): List<String> =
        localDir().listFiles { _, n -> n.endsWith(".mbtiles") }
            ?.map { it.nameWithoutExtension }
            ?.sorted()
            ?: emptyList()

    fun deleteLocal(name: String): Boolean = File(localDir(), "$name.mbtiles").delete()

    /** Fetch the source list. Returns an empty list on any failure — callers fall back to OSM. */
    suspend fun list(): List<MapSourceDto> = runCatching {
        val resp = api.get("/map/sources")
        if (!resp.ok) return emptyList()
        json.decodeFromString<List<MapSourceDto>>(resp.body)
    }.getOrDefault(emptyList())

    /**
     * Download an MBTiles archive from the backend to the device.
     *
     * Writes to a `.part` sibling and atomically renames on success so a killed
     * download (force-close, oom-kill) never leaves a corrupt file masquerading
     * as a complete one. Uses OkHttp's streaming `byteStream()` so files of any
     * size are written without buffering in memory.
     */
    suspend fun download(name: String, onProgress: DownloadProgress = { _, _ -> }): Result<File> =
        withContext(Dispatchers.IO) {
            runCatching {
                val token = tokenStore.current().orEmpty()
                if (token.isBlank()) error("Not signed in")
                val base = settings.currentServerUrl().trimEnd('/')
                val url  = "$base/map/sources/$name/download?token=$token"
                val req  = Request.Builder().url(url).get().build()
                // Clone the shared client with a disabled read timeout — a
                // multi-GB transfer over a slow link easily exceeds the 30 s
                // default and would abort halfway through.
                val downloadClient = api.httpClient.newBuilder()
                    .readTimeout(0, TimeUnit.SECONDS)
                    .callTimeout(0, TimeUnit.SECONDS)
                    .build()
                downloadClient.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) throw IOException("HTTP ${resp.code}")
                    val body  = resp.body ?: throw IOException("Empty body")
                    val total = body.contentLength()   // -1 if unknown
                    val finalFile = File(localDir(), "$name.mbtiles")
                    val partFile  = File(localDir(), "$name.mbtiles.part")
                    body.byteStream().use { input ->
                        partFile.outputStream().use { output ->
                            val buf = ByteArray(64 * 1024)
                            var written = 0L
                            while (true) {
                                val n = input.read(buf)
                                if (n < 0) break
                                output.write(buf, 0, n)
                                written += n
                                onProgress(written, total)
                            }
                        }
                    }
                    if (!partFile.renameTo(finalFile)) {
                        partFile.delete()
                        throw IOException("Rename .part -> .mbtiles failed")
                    }
                    finalFile
                }
            }
        }
}
