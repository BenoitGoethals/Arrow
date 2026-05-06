package com.arrow.tactical.settings

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "arrow_settings")

class SettingsRepository(private val context: Context) {

    private val keyServerUrl = stringPreferencesKey("server_url")
    private val keyCallsign = stringPreferencesKey("callsign")
    private val keyTeam = stringPreferencesKey("team")

    val serverUrl: Flow<String> = context.dataStore.data.map { it[keyServerUrl] ?: DEFAULT_SERVER }
    val callsign: Flow<String> = context.dataStore.data.map { it[keyCallsign] ?: "" }
    val team: Flow<String> = context.dataStore.data.map { it[keyTeam] ?: "" }

    suspend fun currentServerUrl(): String = serverUrl.first()

    suspend fun update(serverUrl: String? = null, callsign: String? = null, team: String? = null) {
        context.dataStore.edit { prefs ->
            serverUrl?.let { prefs[keyServerUrl] = it.trimEnd('/') }
            callsign?.let { prefs[keyCallsign] = it }
            team?.let { prefs[keyTeam] = it }
        }
    }

    companion object {
        // Use 10.0.2.2 for Android emulator → host machine.
        const val DEFAULT_SERVER = "http://10.0.2.2:6001"
    }
}
