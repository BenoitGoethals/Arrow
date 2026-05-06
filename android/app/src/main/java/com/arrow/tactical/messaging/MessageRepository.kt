package com.arrow.tactical.messaging

import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.MessageDto
import com.arrow.tactical.network.MessageIn
import kotlinx.serialization.encodeToString

class MessageRepository(private val api: ApiClient) {

    suspend fun send(
        content: String,
        receiverId: Int? = null,
        groupId: String? = null,
        type: String = if (receiverId != null) "DIRECT" else "BROADCAST",
        photoId: Int? = null,
    ): Result<MessageDto> = runCatching {
        val payload = MessageIn(
            receiverId = receiverId, groupId = groupId,
            content = content, messageType = type, photoId = photoId,
        )
        val r = api.postJson("/messages", api.json.encodeToString(payload))
        require(r.ok) { "send failed: ${r.code}" }
        api.json.decodeFromString<MessageDto>(r.body)
    }

    suspend fun list(): Result<List<MessageDto>> = runCatching {
        val r = api.get("/messages")
        require(r.ok) { "list failed: ${r.code}" }
        api.json.decodeFromString<List<MessageDto>>(r.body)
    }
}
