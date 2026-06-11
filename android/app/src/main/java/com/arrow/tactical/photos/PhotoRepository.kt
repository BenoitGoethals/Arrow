package com.arrow.tactical.photos

import android.content.Context
import android.net.Uri
import com.arrow.tactical.network.ApiClient
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.int
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody

class PhotoRepository(private val api: ApiClient) {

    suspend fun upload(context: Context, uri: Uri): Result<Int> = runCatching {
        val cr   = context.contentResolver
        val mime = cr.getType(uri) ?: "image/jpeg"
        val ext  = when (mime) {
            "image/png"       -> "png"
            "image/gif"       -> "gif"
            "image/webp"      -> "webp"
            "video/mp4"       -> "mp4"
            "video/webm"      -> "webm"
            "video/ogg"       -> "ogv"
            "video/quicktime" -> "mov"
            else -> if (mime.startsWith("video/")) "mp4" else "jpg"
        }
        val bytes = cr.openInputStream(uri)?.use { it.readBytes() }
            ?: error("Cannot read file from URI")

        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("file", "media.$ext", bytes.toRequestBody(mime.toMediaTypeOrNull()))
            .build()

        val r = api.postMultipart("/photos", body)
        require(r.ok) { "Media upload failed: ${r.code}" }
        api.json.parseToJsonElement(r.body).jsonObject["id"]!!.jsonPrimitive.int
    }

    fun isVideo(mimeType: String?): Boolean = mimeType?.startsWith("video/") == true

    fun photoUrl(baseUrl: String, photoId: Int): String = "$baseUrl/photos/$photoId"
}
