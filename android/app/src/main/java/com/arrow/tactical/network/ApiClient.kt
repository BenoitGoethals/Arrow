package com.arrow.tactical.network

import com.arrow.tactical.auth.TokenStore
import com.arrow.tactical.settings.SettingsRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.logging.HttpLoggingInterceptor
import java.util.concurrent.TimeUnit

/** Wraps an HTTP response with the body already buffered on an IO thread. */
data class ApiResponse(val code: Int, val body: String) {
    val ok: Boolean get() = code in 200..299
}

class ApiClient(
    private val settings: SettingsRepository,
    private val tokenStore: TokenStore,
) {
    val json: Json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
    }

    // Token cache — updated via a long-lived coroutine so the OkHttp interceptor
    // never needs runBlocking (which can deadlock on main thread or starve IO pool).
    @Volatile private var cachedToken: String? = null

    init {
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            tokenStore.tokenFlow.collect { cachedToken = it }
        }
    }

    private val jsonMedia = "application/json; charset=utf-8".toMediaType()
    private val formMedia  = "application/x-www-form-urlencoded".toMediaType()

    val httpClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .addInterceptor(HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BASIC })
        .addInterceptor { chain ->
            val token = cachedToken
            val req = if (token.isNullOrBlank()) chain.request()
            else chain.request().newBuilder().header("Authorization", "Bearer $token").build()
            val response = chain.proceed(req)
            // Token was sent but backend rejected it — expired or revoked. Clear it so
            // the nav graph detects the missing token and redirects to login automatically.
            if (response.code == 401 && !token.isNullOrBlank()) {
                CoroutineScope(SupervisorJob() + Dispatchers.IO).launch { tokenStore.clear() }
            }
            response
        }
        .build()

    private suspend fun baseUrl(): String = settings.currentServerUrl()

    // All public methods do the full request + body-read inside withContext(Dispatchers.IO)
    // so callers on Dispatchers.Main never touch the socket.

    suspend fun get(path: String): ApiResponse = withContext(Dispatchers.IO) {
        httpClient.newCall(Request.Builder().url(baseUrl() + path).get().build())
            .execute().use { ApiResponse(it.code, it.body?.string().orEmpty()) }
    }

    suspend fun delete(path: String): ApiResponse = withContext(Dispatchers.IO) {
        httpClient.newCall(Request.Builder().url(baseUrl() + path).delete().build())
            .execute().use { ApiResponse(it.code, it.body?.string().orEmpty()) }
    }

    suspend fun postJson(path: String, body: String): ApiResponse = withContext(Dispatchers.IO) {
        httpClient.newCall(
            Request.Builder().url(baseUrl() + path)
                .post(body.toRequestBody(jsonMedia)).build()
        ).execute().use { ApiResponse(it.code, it.body?.string().orEmpty()) }
    }

    suspend fun patchJson(path: String, body: String): ApiResponse = withContext(Dispatchers.IO) {
        httpClient.newCall(
            Request.Builder().url(baseUrl() + path)
                .patch(body.toRequestBody(jsonMedia)).build()
        ).execute().use { ApiResponse(it.code, it.body?.string().orEmpty()) }
    }

    suspend fun postForm(path: String, form: Map<String, String>): ApiResponse = withContext(Dispatchers.IO) {
        val encoded = form.entries.joinToString("&") {
            "${java.net.URLEncoder.encode(it.key, "UTF-8")}=${java.net.URLEncoder.encode(it.value, "UTF-8")}"
        }
        httpClient.newCall(
            Request.Builder().url(baseUrl() + path)
                .post(encoded.toRequestBody(formMedia)).build()
        ).execute().use { ApiResponse(it.code, it.body?.string().orEmpty()) }
    }

    suspend fun postXml(path: String, xml: String): ApiResponse = withContext(Dispatchers.IO) {
        val xmlMedia = "application/xml; charset=utf-8".toMediaType()
        httpClient.newCall(
            Request.Builder().url(baseUrl() + path)
                .post(xml.toRequestBody(xmlMedia)).build()
        ).execute().use { ApiResponse(it.code, it.body?.string().orEmpty()) }
    }

    suspend fun postMultipart(path: String, body: MultipartBody): ApiResponse = withContext(Dispatchers.IO) {
        httpClient.newCall(
            Request.Builder().url(baseUrl() + path).post(body).build()
        ).execute().use { ApiResponse(it.code, it.body?.string().orEmpty()) }
    }

    fun emptyBody(): RequestBody = "".toRequestBody(jsonMedia)
}
