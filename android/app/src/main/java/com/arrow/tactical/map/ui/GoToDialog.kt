package com.arrow.tactical.map.ui

import android.location.Geocoder
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.arrow.tactical.network.MgrsConverter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.osmdroid.util.GeoPoint

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GoToDialog(
    onDismiss: () -> Unit,
    onNavigate: (GeoPoint, String) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val keyboard = LocalSoftwareKeyboardController.current

    var query by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }

    fun resolve() {
        val q = query.trim()
        if (q.isBlank()) return
        error = null

        // 1. Try MGRS
        val mgrsResult = runCatching { MgrsConverter.decode(q) }
        if (mgrsResult.isSuccess) {
            val (lat, lon) = mgrsResult.getOrThrow()
            keyboard?.hide()
            onNavigate(GeoPoint(lat, lon), "MGRS: ${q.uppercase()}")
            return
        }

        // 2. Try decimal lat/lon ("50.85, 4.35" or "50.85 4.35")
        val latLon = parseLatLon(q)
        if (latLon != null) {
            keyboard?.hide()
            onNavigate(GeoPoint(latLon.first, latLon.second),
                       "%.5f, %.5f".format(latLon.first, latLon.second))
            return
        }

        // 3. Geocode via Android Geocoder (network-dependent)
        loading = true
        scope.launch {
            try {
                @Suppress("DEPRECATION")
                val results = withContext(Dispatchers.IO) {
                    Geocoder(context).getFromLocationName(q, 1)
                }
                if (!results.isNullOrEmpty()) {
                    val r = results[0]
                    keyboard?.hide()
                    onNavigate(GeoPoint(r.latitude, r.longitude),
                               r.getAddressLine(0) ?: q)
                } else {
                    error = "Location not found"
                }
            } catch (e: Exception) {
                error = "Geocoding failed — check network"
            } finally {
                loading = false
            }
        }
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        containerColor = Color(0xFF0F2540),
        contentColor = Color(0xFFE2E8F0),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp)
                .padding(bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = "Go To Location",
                    fontSize = 18.sp,
                    fontWeight = FontWeight.Bold,
                    color = Color(0xFFE2E8F0),
                    modifier = Modifier.weight(1f),
                )
                IconButton(onClick = onDismiss) {
                    Icon(Icons.Filled.Close, contentDescription = "Close",
                         tint = Color(0xFF94A3B8))
                }
            }

            Text(
                text = "MGRS · lat, lon · address",
                fontSize = 12.sp,
                color = Color(0xFF64748B),
            )

            OutlinedTextField(
                value = query,
                onValueChange = { query = it; error = null },
                modifier = Modifier.fillMaxWidth(),
                placeholder = {
                    Text(
                        text = "31UED48251223  ·  50.85, 4.35  ·  Brussels",
                        color = Color(0xFF475569),
                        fontFamily = FontFamily.Monospace,
                        fontSize = 13.sp,
                    )
                },
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { resolve() }),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor      = Color(0xFF34D399),
                    unfocusedBorderColor    = Color(0xFF2A3142),
                    focusedTextColor        = Color(0xFFE2E8F0),
                    unfocusedTextColor      = Color(0xFFE2E8F0),
                    cursorColor             = Color(0xFF34D399),
                    focusedContainerColor   = Color(0xFF0D1B2A),
                    unfocusedContainerColor = Color(0xFF0D1B2A),
                    errorBorderColor        = Color(0xFFF87171),
                ),
                trailingIcon = if (loading) ({
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        color = Color(0xFF34D399),
                        strokeWidth = 2.dp,
                    )
                }) else null,
                isError = error != null,
                supportingText = error?.let { msg -> { Text(msg, color = Color(0xFFF87171)) } },
            )

            Button(
                onClick = { resolve() },
                enabled = query.isNotBlank() && !loading,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(
                    containerColor         = Color(0xFF0F6B50),
                    contentColor           = Color.White,
                    disabledContainerColor = Color(0xFF1A2233),
                    disabledContentColor   = Color(0xFF475569),
                ),
            ) {
                Icon(Icons.Filled.Search, contentDescription = null,
                     modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Text("Go To", fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

private fun parseLatLon(s: String): Pair<Double, Double>? {
    val parts = s.replace(Regex("[°'\"NSEW]"), " ").trim()
        .split(Regex("[,\\s]+"))
        .filter { it.isNotBlank() }
    if (parts.size < 2) return null
    val a = parts[0].toDoubleOrNull() ?: return null
    val b = parts[1].toDoubleOrNull() ?: return null
    if (a !in -90.0..90.0 || b !in -180.0..180.0) return null
    return a to b
}
