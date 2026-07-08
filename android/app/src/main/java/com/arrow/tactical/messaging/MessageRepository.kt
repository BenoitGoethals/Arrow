package com.arrow.tactical.messaging

import com.arrow.tactical.auth.TokenStore
import com.arrow.tactical.data.local.AppDatabase
import com.arrow.tactical.data.local.entity.CachedMessageEntity
import com.arrow.tactical.data.local.entity.PendingActionEntity
import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.ChatRoomDto
import com.arrow.tactical.network.ChatRoomIn
import com.arrow.tactical.network.ChatRoomMemberIn
import com.arrow.tactical.network.MessageDto
import com.arrow.tactical.network.MessageIn
import com.arrow.tactical.sync.ConnectivityObserver
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.encodeToString

class MessageRepository(
    private val api: ApiClient,
    private val db: AppDatabase,
    private val tokenStore: TokenStore,
    private val connectivity: ConnectivityObserver,
) {
    /** Observe all messages from the local cache — works offline and as a guest. */
    fun observeMessages(): Flow<List<MessageDto>> =
        db.cachedMessageDao().observeAll().map { list -> list.map { it.toDto() } }

    /**
     * Send a message.
     *
     * - Guest: saved locally only (local ID, never sent).
     * - Authenticated + online: sent immediately; local record updated with server ID.
     * - Authenticated + offline: saved locally + queued for sync.
     */
    suspend fun send(
        content: String,
        receiverId: Int? = null,
        groupId: String? = null,
        chatroomId: Int? = null,
        type: String = if (chatroomId != null) "ROOM" else if (receiverId != null) "DIRECT" else "BROADCAST",
        photoId: Int? = null,
    ): Result<MessageDto> = runCatching {
        val localId = -System.currentTimeMillis()  // negative = not yet on server
        val payload = MessageIn(receiverId = receiverId, groupId = groupId, chatroomId = chatroomId,
            content = content, messageType = type, photoId = photoId)
        val payloadJson = api.json.encodeToString(payload)

        // Always persist locally first
        db.cachedMessageDao().insert(
            CachedMessageEntity(
                id = localId, content = content, senderCallsign = "me",
                messageType = type, receiverId = receiverId, groupId = groupId,
                syncStatus = "pending",
            )
        )

        val token = tokenStore.current()
        if (token.isNullOrBlank()) {
            // Guest: local only, no sync needed
            return@runCatching localDto(localId, content, type, receiverId, groupId)
        }

        if (connectivity.hasActiveConnection()) {
            val r = api.postJson("/messages", payloadJson)
            if (r.ok) {
                val dto = api.json.decodeFromString<MessageDto>(r.body)
                db.cachedMessageDao().markSynced(localId, dto.id.toLong())
                return@runCatching dto
            }
        }

        // Offline — enqueue
        db.pendingActionDao().insert(
            PendingActionEntity(actionType = "POST_JSON", endpoint = "/messages", payload = payloadJson)
        )
        localDto(localId, content, type, receiverId, groupId)
    }

    suspend fun list(): Result<List<MessageDto>> = runCatching {
        val token = tokenStore.current()
        if (token.isNullOrBlank() || !connectivity.hasActiveConnection()) {
            return@runCatching db.cachedMessageDao().getLatest().map { it.toDto() }
        }
        val r = api.get("/messages")
        if (!r.ok) return@runCatching db.cachedMessageDao().getLatest().map { it.toDto() }
        val messages = api.json.decodeFromString<List<MessageDto>>(r.body)
        db.cachedMessageDao().upsertAll(messages.map { it.toEntity() })
        messages
    }

    private fun localDto(localId: Long, content: String, type: String, receiverId: Int?, groupId: String?) =
        MessageDto(id = localId.toInt(), senderId = -1, receiverId = receiverId,
            groupId = groupId, content = content, messageType = type)

    // ── Chat rooms ──────────────────────────────────────────────────────────
    suspend fun listRooms(): Result<List<ChatRoomDto>> = runCatching {
        val r = api.get("/chatrooms")
        if (!r.ok) error("rooms ${r.code}")
        api.json.decodeFromString<List<ChatRoomDto>>(r.body)
    }

    suspend fun createRoom(name: String): Result<ChatRoomDto> = runCatching {
        val r = api.postJson("/chatrooms", api.json.encodeToString(ChatRoomIn(name = name)))
        if (!r.ok) error("create ${r.code}")
        api.json.decodeFromString<ChatRoomDto>(r.body)
    }

    suspend fun addMember(roomId: Int, operatorId: Int): Result<ChatRoomDto> = runCatching {
        val r = api.postJson("/chatrooms/$roomId/members",
            api.json.encodeToString(ChatRoomMemberIn(operatorId = operatorId)))
        if (!r.ok) error("add ${r.code}")
        api.json.decodeFromString<ChatRoomDto>(r.body)
    }

    suspend fun removeMember(roomId: Int, operatorId: Int): Result<Unit> = runCatching {
        val r = api.delete("/chatrooms/$roomId/members/$operatorId")
        if (!r.ok) error("remove ${r.code}")
    }

    suspend fun deleteRoom(roomId: Int): Result<Unit> = runCatching {
        val r = api.delete("/chatrooms/$roomId")
        if (!r.ok && r.code != 204) error("delete ${r.code}")
    }
}

private fun CachedMessageEntity.toDto() = MessageDto(
    id = id.toInt(), senderId = -1, receiverId = receiverId,
    groupId = groupId, content = content, messageType = messageType,
    source = source,
)

private fun MessageDto.toEntity() = CachedMessageEntity(
    id = id.toLong(), content = content,
    senderCallsign = senderId.toString(), messageType = messageType,
    receiverId = receiverId, groupId = groupId, syncStatus = "synced",
    source = source,
)
