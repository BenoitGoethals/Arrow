package com.arrow.tactical.opord

import android.content.Context
import androidx.core.content.FileProvider
import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.OpordDto
import okhttp3.Request
import java.io.File

class OpordRepository(
    private val api: ApiClient,
    private val settingsBaseUrl: suspend () -> String,
) {
    suspend fun list(): Result<List<OpordDto>> = runCatching {
        val r = api.get("/opord")
        require(r.ok) { "HTTP ${r.code} from ${settingsBaseUrl()}/opord — ${r.body.take(120)}" }
        api.json.decodeFromString<List<OpordDto>>(r.body)
    }

    suspend fun get(id: Int): Result<OpordDto> = runCatching {
        val r = api.get("/opord/$id")
        require(r.ok) { "get opord failed: ${r.code}" }
        api.json.decodeFromString<OpordDto>(r.body)
    }

    /**
     * Download the rendered PDF and return a content:// Uri so the system
     * PDF viewer can open it. Auth header is added via the OkHttp interceptor
     * so the JWT travels with the request transparently.
     */
    suspend fun downloadPdf(context: Context, id: Int): android.net.Uri {
        val base = settingsBaseUrl()
        val req = Request.Builder().url("$base/opord/$id/pdf").get().build()
        val cacheDir = File(context.cacheDir, "opord").apply { mkdirs() }
        val out = File(cacheDir, "opord-$id.pdf")
        api.httpClient.newCall(req).execute().use { resp ->
            require(resp.isSuccessful) { "PDF fetch failed: ${resp.code}" }
            out.outputStream().use { resp.body!!.byteStream().copyTo(it) }
        }
        return FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", out)
    }
}
