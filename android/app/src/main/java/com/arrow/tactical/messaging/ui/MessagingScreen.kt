package com.arrow.tactical.messaging.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.media3.common.MediaItem
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import coil.ImageLoader
import coil.compose.AsyncImage
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.network.ChatRoomDto
import com.arrow.tactical.network.MessageDto
import com.arrow.tactical.network.OperatorDto
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.jsonPrimitive

private sealed class Recipient(val label: String) {
    data object Broadcast : Recipient("📢 Broadcast (everyone)")
    data class Room(val room: ChatRoomDto) : Recipient("# ${room.name}")
    data class Direct(val op: OperatorDto) : Recipient("→ ${op.callsign} (${op.rank})")
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MessagingScreen(container: AppContainer) {
    val context = LocalContext.current
    var messages  by remember { mutableStateOf<List<MessageDto>>(emptyList()) }
    var operators by remember { mutableStateOf<List<OperatorDto>>(emptyList()) }
    var rooms     by remember { mutableStateOf<List<ChatRoomDto>>(emptyList()) }
    var draft     by remember { mutableStateOf("") }
    var recipient by remember { mutableStateOf<Recipient>(Recipient.Broadcast) }
    var menuOpen  by remember { mutableStateOf(false) }
    var showRoomManager by remember { mutableStateOf(false) }
    var meId      by remember { mutableStateOf<Int?>(null) }

    // Media (photo or video) attachment state
    var pendingPhotoId   by remember { mutableStateOf<Int?>(null) }
    var pendingMediaUri  by remember { mutableStateOf<android.net.Uri?>(null) }
    var pendingMediaMime by remember { mutableStateOf<String?>(null) }
    var uploadingMedia   by remember { mutableStateOf(false) }

    // Video playback dialog
    var videoPlayUrl by remember { mutableStateOf<String?>(null) }
    var videoToken   by remember { mutableStateOf("") }

    val scope     = rememberCoroutineScope()
    val listState = rememberLazyListState()

    // Accepts both images and videos via OpenDocument
    val mediaLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        val mime = context.contentResolver.getType(uri) ?: "image/jpeg"
        pendingMediaUri  = uri
        pendingMediaMime = mime
        scope.launch {
            uploadingMedia = true
            container.photoRepository.upload(context, uri)
                .onSuccess  { pendingPhotoId = it }
                .onFailure  { pendingPhotoId = null; pendingMediaUri = null }
            uploadingMedia = false
        }
    }

    suspend fun refreshMessages() {
        container.messageRepository.list().onSuccess { messages = it.sortedBy { m -> m.id } }
    }
    suspend fun refreshRooms() {
        container.messageRepository.listRooms().onSuccess { rooms = it }
    }

    LaunchedEffect(Unit) {
        container.authRepository.me().onSuccess { meId = it.id }
        container.tacticalRepository.listOperators().onSuccess { operators = it }
        refreshRooms()
        refreshMessages()
        videoToken = container.tokenStore.current() ?: ""
    }

    // Keep the selected room object fresh; drop selection if the room is gone.
    LaunchedEffect(rooms) {
        val r = recipient
        if (r is Recipient.Room) {
            val updated = rooms.find { it.id == r.room.id }
            recipient = if (updated != null) Recipient.Room(updated) else Recipient.Broadcast
        }
    }

    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex)
    }

    LaunchedEffect(Unit) {
        while (true) { refreshMessages(); refreshRooms(); delay(4_000) }
    }

    // Real-time reception, matching the web client: JDSS/ATAK-bridged chat and
    // chatroom lifecycle events both arrive on the `chat` WS channel, so refresh
    // messages + rooms the instant one lands (the poll above is the fallback).
    LaunchedEffect(Unit) {
        while (true) {
            try {
                container.wsClient.events().collect { event ->
                    if (event["channel"]?.jsonPrimitive?.content == "chat") {
                        refreshMessages()
                        refreshRooms()
                    }
                }
            } catch (_: Exception) {
                // Socket dropped — back off, then the 4 s poll covers the gap.
            }
            delay(3_000)
        }
    }

    val baseUrl = remember { mutableStateOf("") }
    LaunchedEffect(Unit) { baseUrl.value = container.settingsRepository.currentServerUrl() }

    // Video player dialog
    videoPlayUrl?.let { url ->
        VideoPlayerDialog(
            url   = url,
            token = videoToken,
            onDismiss = { videoPlayUrl = null },
        )
    }

    if (showRoomManager) {
        RoomManagerDialog(
            rooms     = rooms,
            operators = operators,
            onDismiss = { showRoomManager = false },
            onCreate  = { name -> scope.launch { container.messageRepository.createRoom(name); refreshRooms() } },
            onDelete  = { rid  -> scope.launch { container.messageRepository.deleteRoom(rid); refreshRooms() } },
            onToggleMember = { rid, opId, add ->
                scope.launch {
                    if (add) container.messageRepository.addMember(rid, opId)
                    else     container.messageRepository.removeMember(rid, opId)
                    refreshRooms()
                }
            },
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Messaging") },
                actions = {
                    Box {
                        TextButton(onClick = { menuOpen = true }) {
                            Text(recipient.label, maxLines = 1)
                            Icon(Icons.Filled.ArrowDropDown, null)
                        }
                        DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                            DropdownMenuItem(
                                text = { Text(Recipient.Broadcast.label) },
                                onClick = { recipient = Recipient.Broadcast; menuOpen = false },
                            )
                            HorizontalDivider()
                            Text(
                                "Chat rooms",
                                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                                style = MaterialTheme.typography.labelSmall,
                            )
                            rooms.forEach { room ->
                                DropdownMenuItem(
                                    text = {
                                        Row(
                                            verticalAlignment = Alignment.CenterVertically,
                                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                                        ) {
                                            Text("# ${room.name}  (${room.memberIds.size})")
                                            // Mark ATAK-imported rooms; native rooms stay unmarked.
                                            if (room.origin.uppercase() == "ATAK") SourceBadge(room.origin)
                                        }
                                    },
                                    onClick = { recipient = Recipient.Room(room); menuOpen = false },
                                )
                            }
                            DropdownMenuItem(
                                text = { Text("⚙ Manage rooms…") },
                                onClick = { showRoomManager = true; menuOpen = false },
                            )
                            HorizontalDivider()
                            Text(
                                "Direct →",
                                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                                style = MaterialTheme.typography.labelSmall,
                            )
                            operators
                                .filter { it.id != meId }
                                .sortedBy { it.callsign }
                                .forEach { op ->
                                    DropdownMenuItem(
                                        text = { Text("${op.callsign}  ·  ${op.role}") },
                                        onClick = { recipient = Recipient.Direct(op); menuOpen = false },
                                    )
                                }
                        }
                    }
                },
            )
        },
    ) { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxSize()) {
            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f).padding(horizontal = 12.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
                contentPadding = PaddingValues(vertical = 12.dp),
            ) {
                items(messages) { m ->
                    MessageBubble(
                        message     = m,
                        isMine      = m.senderId == meId,
                        baseUrl     = baseUrl.value,
                        imageLoader = container.imageLoader,
                        onPlayVideo = { url -> videoPlayUrl = url },
                    )
                }
            }

            HorizontalDivider()

            // Pending media preview strip
            if (pendingMediaUri != null) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 8.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    if (uploadingMedia) {
                        CircularProgressIndicator(Modifier.size(40.dp))
                        Text("Uploading…", style = MaterialTheme.typography.bodySmall)
                    } else {
                        val isVideo = pendingMediaMime?.startsWith("video/") == true
                        if (isVideo) {
                            Icon(
                                Icons.Filled.PlayCircle,
                                contentDescription = null,
                                modifier = Modifier.size(48.dp),
                                tint = MaterialTheme.colorScheme.primary,
                            )
                        } else {
                            AsyncImage(
                                model = pendingMediaUri,
                                contentDescription = "Attached photo",
                                modifier = Modifier
                                    .size(64.dp)
                                    .clip(RoundedCornerShape(8.dp)),
                                contentScale = ContentScale.Crop,
                            )
                        }
                        Text(
                            when {
                                pendingPhotoId == null -> "Upload failed"
                                isVideo -> "Video ready"
                                else -> "Photo ready"
                            },
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.weight(1f),
                        )
                    }
                    IconButton(onClick = {
                        pendingMediaUri  = null
                        pendingPhotoId   = null
                        pendingMediaMime = null
                    }) {
                        Icon(Icons.Filled.Close, contentDescription = "Remove")
                    }
                }
            }

            Composer(
                draft          = draft,
                onDraftChange  = { draft = it },
                canSend        = draft.isNotBlank() || pendingPhotoId != null,
                uploadingMedia = uploadingMedia,
                placeholder    = "Send to ${recipient.label.removePrefix("📢 ").removePrefix("⭐ ").removePrefix("→ ")}",
                onPickMedia    = { mediaLauncher.launch(arrayOf("image/*", "video/*")) },
                onSend         = {
                    val text    = draft.trim()
                    val photoId = pendingPhotoId
                    if (text.isBlank() && photoId == null) return@Composer
                    draft = ""
                    pendingPhotoId   = null
                    pendingMediaUri  = null
                    pendingMediaMime = null
                    scope.launch {
                        when (val r = recipient) {
                            Recipient.Broadcast ->
                                container.messageRepository.send(text, type = "BROADCAST", photoId = photoId)
                            is Recipient.Room ->
                                container.messageRepository.send(text, chatroomId = r.room.id, type = "ROOM", photoId = photoId)
                            is Recipient.Direct ->
                                container.messageRepository.send(text, receiverId = r.op.id, type = "DIRECT", photoId = photoId)
                        }
                        refreshMessages()
                    }
                },
            )
        }
    }
}

// Origin marker on each message: ARROW (native) / JDSS (coalition) / TAK (ATAK CoT).
@Composable
private fun SourceBadge(source: String) {
    val s = source.uppercase()
    val label = if (s == "ATAK") "TAK" else s
    val color = when (s) {
        "JDSS" -> Color(0xFF78350F)
        "ATAK" -> Color(0xFF0C4A6E)
        else   -> Color(0xFF14532D)
    }
    Surface(color = color, shape = MaterialTheme.shapes.small) {
        Text(
            text       = label,
            style      = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Bold,
            color      = Color.White,
            modifier   = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
        )
    }
}

@Composable
private fun MessageBubble(
    message: MessageDto,
    isMine: Boolean,
    baseUrl: String,
    imageLoader: ImageLoader,
    onPlayVideo: (String) -> Unit,
) {
    val align = if (isMine) Alignment.End else Alignment.Start
    val bg = when {
        isMine -> MaterialTheme.colorScheme.primary
        message.messageType == "BROADCAST" -> MaterialTheme.colorScheme.tertiaryContainer
        message.messageType == "ROOM"      -> MaterialTheme.colorScheme.secondaryContainer
        else   -> MaterialTheme.colorScheme.surfaceVariant
    }
    val fg = when {
        isMine -> MaterialTheme.colorScheme.onPrimary
        else   -> MaterialTheme.colorScheme.onSurface
    }

    Column(modifier = Modifier.fillMaxWidth(), horizontalAlignment = align) {
        val tag = when (message.messageType) {
            "BROADCAST" -> "BROADCAST"
            "ROOM"      -> "ROOM"
            else        -> "DIRECT"
        }
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            modifier = Modifier.padding(horizontal = 8.dp),
        ) {
            Text(
                text  = "from #${message.senderId} · $tag",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            SourceBadge(message.source)
        }
        Box(
            modifier = Modifier
                .padding(top = 2.dp)
                .clip(RoundedCornerShape(14.dp))
                .background(bg)
                .padding(horizontal = 12.dp, vertical = 8.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                if (message.content.isNotBlank()) {
                    Text(
                        text       = message.content,
                        color      = fg,
                        fontWeight = if (isMine) FontWeight.Medium else FontWeight.Normal,
                    )
                }
                if (message.photoId != null && baseUrl.isNotBlank()) {
                    val mediaUrl = "$baseUrl/photos/${message.photoId}"
                    if (message.photoMimeType?.startsWith("video/") == true) {
                        Surface(
                            onClick = { onPlayVideo(mediaUrl) },
                            shape = RoundedCornerShape(8.dp),
                            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                        ) {
                            Row(
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                Icon(
                                    Icons.Filled.PlayCircle,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.primary,
                                )
                                Text(
                                    "Video — tap to play",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = fg,
                                )
                            }
                        }
                    } else {
                        AsyncImage(
                            model              = mediaUrl,
                            contentDescription = "Photo",
                            imageLoader        = imageLoader,
                            modifier           = Modifier
                                .widthIn(max = 240.dp)
                                .clip(RoundedCornerShape(8.dp)),
                            contentScale       = ContentScale.FillWidth,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun Composer(
    draft: String,
    onDraftChange: (String) -> Unit,
    canSend: Boolean,
    uploadingMedia: Boolean,
    placeholder: String,
    onPickMedia: () -> Unit,
    onSend: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .imePadding()
            .padding(8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        IconButton(onClick = onPickMedia, enabled = !uploadingMedia) {
            Icon(Icons.Filled.AttachFile, contentDescription = "Attach photo or video")
        }
        OutlinedTextField(
            value         = draft,
            onValueChange = onDraftChange,
            placeholder   = { Text(placeholder, maxLines = 1) },
            modifier      = Modifier.weight(1f),
            maxLines      = 4,
        )
        FilledIconButton(enabled = canSend && !uploadingMedia, onClick = onSend) {
            Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Send")
        }
    }
}

@Composable
fun VideoPlayerDialog(url: String, token: String, onDismiss: () -> Unit) {
    val context = LocalContext.current
    val player = remember(url) {
        val dsf = DefaultHttpDataSource.Factory()
            .setDefaultRequestProperties(mapOf("Authorization" to "Bearer $token"))
        ExoPlayer.Builder(context)
            .setMediaSourceFactory(DefaultMediaSourceFactory(dsf))
            .build()
            .apply {
                setMediaItem(MediaItem.fromUri(url))
                prepare()
                playWhenReady = true
            }
    }
    DisposableEffect(player) { onDispose { player.release() } }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false, dismissOnBackPress = true),
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black),
        ) {
            AndroidView(
                factory = { ctx ->
                    PlayerView(ctx).apply { this.player = player }
                },
                modifier = Modifier.fillMaxSize(),
            )
            IconButton(
                onClick = onDismiss,
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(8.dp),
            ) {
                Icon(Icons.Filled.Close, contentDescription = "Close", tint = Color.White)
            }
        }
    }
}

@Composable
private fun RoomManagerDialog(
    rooms: List<ChatRoomDto>,
    operators: List<OperatorDto>,
    onDismiss: () -> Unit,
    onCreate: (String) -> Unit,
    onDelete: (Int) -> Unit,
    onToggleMember: (Int, Int, Boolean) -> Unit,
) {
    var selectedId by remember(rooms) { mutableStateOf(rooms.firstOrNull()?.id) }
    var newName by remember { mutableStateOf("") }
    val selected = rooms.find { it.id == selectedId }
    val memberIds = selected?.memberIds?.toSet() ?: emptySet()

    Dialog(onDismissRequest = onDismiss) {
        Card(shape = RoundedCornerShape(12.dp)) {
            Column(Modifier.padding(16.dp).fillMaxWidth()) {
                Text("Chat Rooms", style = MaterialTheme.typography.titleMedium,
                     fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(10.dp))

                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        value = newName, onValueChange = { newName = it },
                        label = { Text("New room") }, singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    Spacer(Modifier.width(8.dp))
                    Button(onClick = {
                        if (newName.isNotBlank()) { onCreate(newName.trim()); newName = "" }
                    }) { Text("Create") }
                }

                Spacer(Modifier.height(12.dp))
                if (rooms.isEmpty()) {
                    Text("No rooms yet", style = MaterialTheme.typography.bodySmall)
                } else {
                    Text("Room", style = MaterialTheme.typography.labelSmall)
                    rooms.forEach { r ->
                        Row(verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.fillMaxWidth()) {
                            RadioButton(selected = r.id == selectedId,
                                        onClick = { selectedId = r.id })
                            Text("# ${r.name}", modifier = Modifier.weight(1f))
                            if (r.id == selectedId) {
                                TextButton(onClick = { onDelete(r.id) }) { Text("Delete") }
                            }
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    Text("Members of # ${selected?.name ?: ""}",
                         style = MaterialTheme.typography.labelSmall)
                    LazyColumn(modifier = Modifier.heightIn(max = 240.dp)) {
                        items(operators) { op ->
                            Row(verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.fillMaxWidth()) {
                                Checkbox(
                                    checked = op.id in memberIds,
                                    onCheckedChange = { checked ->
                                        selected?.let { onToggleMember(it.id, op.id, checked) }
                                    },
                                )
                                Text("${op.callsign}  ·  ${op.role}")
                            }
                        }
                    }
                }

                Spacer(Modifier.height(8.dp))
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    TextButton(onClick = onDismiss) { Text("Close") }
                }
            }
        }
    }
}
