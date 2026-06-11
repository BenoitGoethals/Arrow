package com.arrow.tactical.map

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.drawable.BitmapDrawable
import android.graphics.drawable.Drawable
import android.util.Base64
import android.util.LruCache
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.core.graphics.drawable.toDrawable
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicLong

/**
 * Renders MIL-STD-2525C / APP-6 symbols by hosting the **same** milsymbol.js
 * the web map uses inside a hidden WebView and snapshotting each render to a
 * Bitmap. Results are cached so repeated requests for the same SIDC are free.
 *
 * Construction must happen on the main thread (WebView requirement). The
 * `symbol(...)` suspend function is thread-safe — it hops back to the main
 * thread to talk to the WebView, then resumes the caller with the cached
 * Drawable.
 *
 * Pixel parity with the Leaflet map: we pass the same `size` option as
 * web/templates/map.html (28 for operators, 30 for hostiles).
 */
class MilsymRenderer(private val context: Context) {

    private val cache = LruCache<String, Result>(1024)
    private val ready = CompletableDeferred<Unit>()
    private val pending = HashMap<String, CompletableDeferred<Result>>()
    private val tokens = AtomicLong(0)

    data class Result(val drawable: Drawable, val anchorX: Float, val anchorY: Float)

    @get:SuppressLint("SetJavaScriptEnabled")
    private val webView: WebView by lazy {
        val wv = WebView(context.applicationContext)
        wv.settings.javaScriptEnabled = true
        wv.settings.allowFileAccess = true
        wv.settings.allowContentAccess = true
        wv.webViewClient = WebViewClient()
        wv.addJavascriptInterface(Bridge(), "AndroidBridge")
        wv.loadUrl("file:///android_asset/milsymbol/render.html")
        wv
    }

    /**
     * Render `sidc` to a Drawable using milsymbol.js. `options` is forwarded
     * verbatim to `new ms.Symbol(sidc, options)` — see milsymbol docs.
     *
     * Returns null if the WebView never finishes loading (e.g. missing asset).
     */
    suspend fun symbol(sidc: String, options: Map<String, Any?> = emptyMap()): Result? {
        val key = cacheKey(sidc, options)
        cache[key]?.let { return it }

        // Trigger WebView init on the main thread (also satisfies the
        // "WebView must be created on UI thread" constraint).
        withContext(Dispatchers.Main) { webView }   // touch the lazy

        // Wait for the page to call AndroidBridge.onReady()
        ready.await()

        val deferred = CompletableDeferred<Result>()
        val token = "t${tokens.incrementAndGet()}"
        synchronized(pending) { pending[token] = deferred }

        val optsJson = JSONObject(options).toString()
        withContext(Dispatchers.Main) {
            val safeSidc = sidc.replace("\\", "\\\\").replace("'", "\\'")
            val safeOpts = optsJson.replace("\\", "\\\\").replace("'", "\\'")
            webView.evaluateJavascript(
                "window.renderSymbol('$token','$safeSidc','$safeOpts');", null,
            )
        }
        return runCatching { deferred.await() }
            .onSuccess { cache.put(key, it) }
            .getOrNull()
    }

    private fun cacheKey(sidc: String, options: Map<String, Any?>): String =
        if (options.isEmpty()) sidc
        else "$sidc|" + options.entries.asSequence().sortedBy { it.key }
            .joinToString(",") { "${it.key}=${it.value}" }

    private fun complete(token: String, result: Result) {
        val d = synchronized(pending) { pending.remove(token) } ?: return
        d.complete(result)
    }

    private fun fail(token: String, message: String) {
        val d = synchronized(pending) { pending.remove(token) } ?: return
        d.completeExceptionally(IllegalStateException(message))
    }

    private inner class Bridge {
        @JavascriptInterface
        fun onReady() {
            if (!ready.isCompleted) ready.complete(Unit)
        }

        @JavascriptInterface
        fun onSymbol(token: String, dataUrl: String, w: Int, h: Int, ax: Float, ay: Float) {
            val comma = dataUrl.indexOf(',')
            if (comma < 0) { fail(token, "no comma in data URL"); return }
            val b64 = dataUrl.substring(comma + 1)
            val bytes = runCatching { Base64.decode(b64, Base64.DEFAULT) }.getOrNull()
                ?: run { fail(token, "base64 decode failed"); return }
            val bmp: Bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                ?: run { fail(token, "PNG decode failed"); return }
            val anchorX = (ax / w.coerceAtLeast(1).toFloat()).coerceIn(0f, 1f)
            val anchorY = (ay / h.coerceAtLeast(1).toFloat()).coerceIn(0f, 1f)
            complete(
                token,
                Result(
                    bmp.toDrawable(context.resources),
                    anchorX,
                    anchorY,
                ),
            )
        }

        @JavascriptInterface
        fun onError(token: String, message: String) {
            fail(token, message)
        }
    }
}
