package com.arrow.tactical.photos.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import coil.compose.AsyncImage
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.messaging.ui.VideoPlayerDialog
import kotlinx.coroutines.launch
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.contentOrNull

data class MediaItemDto(
    val id: Int,
    val filename: String,
    val originalName: String,
    val mimeType: String,
    val timestamp: String?,
    val messageId: Int?,
    val tacticalObjectId: Int?,
    val reportId: Int?,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MediaGalleryScreen(container: AppContainer) {
    val scope = rememberCoroutineScope()
    var items    by remember { mutableStateOf<List<MediaItemDto>>(emptyList()) }
    var loading  by remember { mutableStateOf(true) }
    var baseUrl  by remember { mutableStateOf("") }
    var token    by remember { mutableStateOf("") }

    // Viewer state
    var viewerImageUrl by remember { mutableStateOf<String?>(null) }
    var viewerVideoUrl by remember { mutableStateOf<String?>(null) }

    suspend fun load() {
        loading = true
        val r = container.apiClient.get("/photos")
        if (r.ok) {
            items = container.apiClient.json
                .parseToJsonElement(r.body)
                .jsonArray
                .map { el ->
                    val obj = el.jsonObject
                    MediaItemDto(
                        id               = obj["id"]!!.jsonPrimitive.int,
                        filename         = obj["filename"]!!.jsonPrimitive.content,
                        originalName     = obj["original_name"]!!.jsonPrimitive.content,
                        mimeType         = obj["mime_type"]!!.jsonPrimitive.content,
                        timestamp        = obj["timestamp"]?.jsonPrimitive?.contentOrNull,
                        messageId        = obj["message_id"]?.jsonPrimitive?.intOrNull,
                        tacticalObjectId = obj["tactical_object_id"]?.jsonPrimitive?.intOrNull,
                        reportId         = obj["report_id"]?.jsonPrimitive?.intOrNull,
                    )
                }
        }
        loading = false
    }

    LaunchedEffect(Unit) {
        baseUrl = container.settingsRepository.currentServerUrl()
        token   = container.tokenStore.current() ?: ""
        load()
    }

    // Full-screen image viewer
    viewerImageUrl?.let { url ->
        Dialog(
            onDismissRequest = { viewerImageUrl = null },
            properties = DialogProperties(usePlatformDefaultWidth = false),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color.Black),
            ) {
                AsyncImage(
                    model              = url,
                    contentDescription = "Full size",
                    imageLoader        = container.imageLoader,
                    modifier           = Modifier.fillMaxSize(),
                    contentScale       = ContentScale.Fit,
                )
                IconButton(
                    onClick = { viewerImageUrl = null },
                    modifier = Modifier.align(Alignment.TopEnd).padding(8.dp),
                ) {
                    Icon(Icons.Filled.Close, contentDescription = "Close", tint = Color.White)
                }
            }
        }
    }

    // Full-screen video viewer
    viewerVideoUrl?.let { url ->
        VideoPlayerDialog(
            url       = url,
            token     = token,
            onDismiss = { viewerVideoUrl = null },
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Media Gallery") },
                actions = {
                    TextButton(onClick = { scope.launch { load() } }) { Text("Refresh") }
                },
            )
        },
    ) { padding ->
        when {
            loading -> Box(
                modifier = Modifier.padding(padding).fillMaxSize(),
                contentAlignment = Alignment.Center,
            ) { CircularProgressIndicator() }

            items.isEmpty() -> Box(
                modifier = Modifier.padding(padding).fillMaxSize(),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "No media yet. Attach photos or videos to messages, reports, or tactical objects.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(24.dp),
                )
            }

            else -> LazyVerticalGrid(
                columns = GridCells.Adaptive(minSize = 160.dp),
                modifier = Modifier.padding(padding).fillMaxSize(),
                contentPadding = PaddingValues(8.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(items, key = { it.id }) { item ->
                    MediaCard(
                        item     = item,
                        baseUrl  = baseUrl,
                        imageLoader = container.imageLoader,
                        onTap    = { mediaUrl, isVideo ->
                            if (isVideo) viewerVideoUrl = mediaUrl
                            else         viewerImageUrl = mediaUrl
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun MediaCard(
    item: MediaItemDto,
    baseUrl: String,
    imageLoader: coil.ImageLoader,
    onTap: (url: String, isVideo: Boolean) -> Unit,
) {
    val isVideo = item.mimeType.startsWith("video/")
    val url     = "$baseUrl/photos/${item.id}"

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .aspectRatio(1f)
            .clickable { onTap(url, isVideo) },
        shape = RoundedCornerShape(8.dp),
    ) {
        Box(modifier = Modifier.fillMaxSize()) {
            if (isVideo) {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(MaterialTheme.colorScheme.surfaceVariant),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        Icons.Filled.PlayCircle,
                        contentDescription = "Video",
                        modifier = Modifier.size(48.dp),
                        tint = MaterialTheme.colorScheme.primary,
                    )
                }
            } else {
                AsyncImage(
                    model              = url,
                    contentDescription = item.originalName,
                    imageLoader        = imageLoader,
                    modifier           = Modifier.fillMaxSize(),
                    contentScale       = ContentScale.Crop,
                )
            }

            // Filename label at bottom
            Box(
                modifier = Modifier
                    .align(Alignment.BottomStart)
                    .fillMaxWidth()
                    .background(Color.Black.copy(alpha = 0.55f))
                    .padding(horizontal = 6.dp, vertical = 3.dp),
            ) {
                Text(
                    text     = item.originalName.ifBlank { item.filename },
                    style    = MaterialTheme.typography.labelSmall,
                    color    = Color.White,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}
