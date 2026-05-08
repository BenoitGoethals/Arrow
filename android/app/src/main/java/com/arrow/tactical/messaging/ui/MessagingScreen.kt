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
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import coil.ImageLoader
import coil.compose.AsyncImage
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.network.MessageDto
import com.arrow.tactical.network.OperatorDto
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private sealed class Recipient(val label: String) {
    data object Broadcast : Recipient("📢 Broadcast (everyone)")
    data object BattleCaptains : Recipient("⭐ Battle Captains")
    data class Direct(val op: OperatorDto) : Recipient("→ ${op.callsign} (${op.rank})")
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MessagingScreen(container: AppContainer) {
    val context = LocalContext.current
    var messages  by remember { mutableStateOf<List<MessageDto>>(emptyList()) }
    var operators by remember { mutableStateOf<List<OperatorDto>>(emptyList()) }
    var draft     by remember { mutableStateOf("") }
    var recipient by remember { mutableStateOf<Recipient>(Recipient.Broadcast) }
    var menuOpen  by remember { mutableStateOf(false) }
    var meId      by remember { mutableStateOf<Int?>(null) }

    // Photo state
    var pendingPhotoId  by remember { mutableStateOf<Int?>(null) }
    var pendingPhotoUri by remember { mutableStateOf<android.net.Uri?>(null) }
    var uploadingPhoto  by remember { mutableStateOf(false) }

    val scope     = rememberCoroutineScope()
    val listState = rememberLazyListState()

    val galleryLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        pendingPhotoUri = uri
        scope.launch {
            uploadingPhoto = true
            container.photoRepository.upload(context, uri)
                .onSuccess { pendingPhotoId = it }
                .onFailure { pendingPhotoId = null; pendingPhotoUri = null }
            uploadingPhoto = false
        }
    }

    suspend fun refreshMessages() {
        container.messageRepository.list().onSuccess { messages = it.sortedBy { m -> m.id } }
    }

    LaunchedEffect(Unit) {
        container.authRepository.me().onSuccess { meId = it.id }
        container.tacticalRepository.listOperators().onSuccess { operators = it }
        refreshMessages()
    }

    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex)
    }

    LaunchedEffect(Unit) {
        while (true) { refreshMessages(); delay(4_000) }
    }

    val baseUrl = remember { mutableStateOf("") }
    LaunchedEffect(Unit) { baseUrl.value = container.settingsRepository.currentServerUrl() }

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
                            DropdownMenuItem(
                                text = { Text(Recipient.BattleCaptains.label) },
                                onClick = { recipient = Recipient.BattleCaptains; menuOpen = false },
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
                        message      = m,
                        isMine       = m.senderId == meId,
                        baseUrl      = baseUrl.value,
                        imageLoader  = container.imageLoader,
                    )
                }
            }

            HorizontalDivider()

            // Photo preview strip
            if (pendingPhotoUri != null) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 8.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    if (uploadingPhoto) {
                        CircularProgressIndicator(Modifier.size(40.dp))
                        Text("Uploading…", style = MaterialTheme.typography.bodySmall)
                    } else {
                        AsyncImage(
                            model = pendingPhotoUri,
                            contentDescription = "Attached photo",
                            modifier = Modifier
                                .size(64.dp)
                                .clip(RoundedCornerShape(8.dp)),
                            contentScale = ContentScale.Crop,
                        )
                        Text(
                            if (pendingPhotoId != null) "Photo ready" else "Upload failed",
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.weight(1f),
                        )
                    }
                    IconButton(onClick = { pendingPhotoUri = null; pendingPhotoId = null }) {
                        Icon(Icons.Filled.Close, contentDescription = "Remove photo")
                    }
                }
            }

            Composer(
                draft          = draft,
                onDraftChange  = { draft = it },
                canSend        = draft.isNotBlank() || pendingPhotoId != null,
                uploadingPhoto = uploadingPhoto,
                placeholder    = "Send to ${recipient.label.removePrefix("📢 ").removePrefix("⭐ ").removePrefix("→ ")}",
                onPickPhoto    = { galleryLauncher.launch("image/*") },
                onSend         = {
                    val text    = draft.trim()
                    val photoId = pendingPhotoId
                    if (text.isBlank() && photoId == null) return@Composer
                    draft = ""
                    pendingPhotoId  = null
                    pendingPhotoUri = null
                    scope.launch {
                        when (val r = recipient) {
                            Recipient.Broadcast ->
                                container.messageRepository.send(text, type = "BROADCAST", photoId = photoId)
                            Recipient.BattleCaptains ->
                                container.messageRepository.send(text, groupId = "BATTLE_CAPTAINS", type = "GROUP", photoId = photoId)
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

@Composable
private fun MessageBubble(message: MessageDto, isMine: Boolean, baseUrl: String, imageLoader: ImageLoader) {
    val align = if (isMine) Alignment.End else Alignment.Start
    val bg = when {
        isMine -> MaterialTheme.colorScheme.primary
        message.messageType == "BROADCAST" -> MaterialTheme.colorScheme.tertiaryContainer
        message.messageType == "GROUP"     -> MaterialTheme.colorScheme.secondaryContainer
        else   -> MaterialTheme.colorScheme.surfaceVariant
    }
    val fg = when {
        isMine -> MaterialTheme.colorScheme.onPrimary
        else   -> MaterialTheme.colorScheme.onSurface
    }

    Column(modifier = Modifier.fillMaxWidth(), horizontalAlignment = align) {
        val tag = when (message.messageType) {
            "BROADCAST" -> "BROADCAST"
            "GROUP"     -> message.groupId ?: "GROUP"
            else        -> "DIRECT"
        }
        Text(
            text  = "from #${message.senderId} · $tag",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 8.dp),
        )
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
                    AsyncImage(
                        model              = "$baseUrl/photos/${message.photoId}",
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

@Composable
private fun Composer(
    draft: String,
    onDraftChange: (String) -> Unit,
    canSend: Boolean,
    uploadingPhoto: Boolean,
    placeholder: String,
    onPickPhoto: () -> Unit,
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
        IconButton(onClick = onPickPhoto, enabled = !uploadingPhoto) {
            Icon(Icons.Filled.AddPhotoAlternate, contentDescription = "Attach photo")
        }
        OutlinedTextField(
            value         = draft,
            onValueChange = onDraftChange,
            placeholder   = { Text(placeholder, maxLines = 1) },
            modifier      = Modifier.weight(1f),
            maxLines      = 4,
        )
        FilledIconButton(enabled = canSend && !uploadingPhoto, onClick = onSend) {
            Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Send")
        }
    }
}
