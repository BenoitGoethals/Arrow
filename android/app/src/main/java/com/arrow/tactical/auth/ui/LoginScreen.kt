package com.arrow.tactical.auth.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.arrow.tactical.auth.AuthRepository
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.network.RegisterIn
import com.arrow.tactical.settings.SettingsRepository
import kotlinx.coroutines.launch

@Composable
fun LoginScreen(
    authRepository: AuthRepository,
    onAuthenticated: () -> Unit,
    onOpenSettings: () -> Unit = {},
    settingsRepository: SettingsRepository? = null,
) {
    var callsign by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var registering by remember { mutableStateOf(false) }
    var role by remember { mutableStateOf("OPERATOR") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var serverShown by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    val server by (settingsRepository?.serverUrl?.collectAsState(initial = SettingsRepository.DEFAULT_SERVER)
        ?: remember { mutableStateOf(SettingsRepository.DEFAULT_SERVER) })
    var serverDraft by remember(server) { mutableStateOf(server) }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp).verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(48.dp))
        Text("ARROW", style = MaterialTheme.typography.headlineLarge)
        Text("Tactical Operator Client", style = MaterialTheme.typography.bodyMedium)
        Spacer(Modifier.height(24.dp))

        OutlinedTextField(
            value = callsign,
            onValueChange = { callsign = it },
            label = { Text("Callsign") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = password,
            onValueChange = { password = it },
            label = { Text("Password") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth(),
        )

        if (registering) {
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = role,
                onValueChange = { role = it.uppercase() },
                label = { Text("Role (OPERATOR / BATTLE_CAPTAIN / ADMIN)") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }

        Spacer(Modifier.height(16.dp))
        Button(
            enabled = !busy && callsign.isNotBlank() && password.isNotBlank(),
            onClick = {
                error = null; busy = true
                scope.launch {
                    val res = if (registering) {
                        authRepository.register(RegisterIn(callsign.trim(), password, role = role))
                    } else {
                        authRepository.login(callsign.trim(), password)
                    }
                    busy = false
                    res.onSuccess { onAuthenticated() }
                        .onFailure { error = it.message }
                }
            },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(if (registering) "Register & sign in" else "Sign in")
        }

        TextButton(onClick = { registering = !registering }) {
            Text(if (registering) "Back to sign-in" else "Register a new operator")
        }

        TextButton(onClick = { serverShown = !serverShown }) {
            Text(if (serverShown) "Hide server settings" else "Server: $server")
        }
        if (serverShown && settingsRepository != null) {
            OutlinedTextField(
                value = serverDraft,
                onValueChange = { serverDraft = it },
                label = { Text("Backend URL") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            TextButton(
                onClick = { scope.launch { settingsRepository.update(serverUrl = serverDraft) } },
            ) { Text("Save server URL") }
        }

        error?.let {
            Spacer(Modifier.height(8.dp))
            Text(it, color = MaterialTheme.colorScheme.error)
        }
    }
}
