package com.arrow.tactical.settings

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.GlobalScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

private val Context.dataStore by preferencesDataStore(name = "arrow_settings")

class SettingsRepository(private val context: Context) {

    private val keyServerUrl    = stringPreferencesKey("server_url")
    private val keyCallsign     = stringPreferencesKey("callsign")
    private val keyTeam         = stringPreferencesKey("team")
    private val keyBasemap      = stringPreferencesKey("basemap")
    private val keyActiveMission = intPreferencesKey("active_mission_id")

    val serverUrl: Flow<String>  = context.dataStore.data.map { it[keyServerUrl] ?: DEFAULT_SERVER }
    val callsign:  Flow<String>  = context.dataStore.data.map { it[keyCallsign] ?: "" }
    val team:      Flow<String>  = context.dataStore.data.map { it[keyTeam] ?: "" }
    val basemap:   Flow<String?> = context.dataStore.data.map { it[keyBasemap] }

    // Synchronous backing field — MissionRepository reads this at init time
    // before any coroutine can run. Updated by setActiveMissionId().
    var activeMissionId: Int
        get() = _activeMissionId
        set(value) { _activeMissionId = value; _persistMissionId(value) }

    @Volatile private var _activeMissionId: Int = 0

    private fun _persistMissionId(id: Int) {
        kotlinx.coroutines.GlobalScope.launch(kotlinx.coroutines.Dispatchers.IO) {
            context.dataStore.edit { it[keyActiveMission] = id }
        }
    }

    suspend fun currentServerUrl(): String = serverUrl.first()
    suspend fun currentCallsign(): String  = callsign.first()
    suspend fun currentBasemap(): String?  = basemap.first()

    suspend fun loadActiveMissionId(): Int {
        val id = context.dataStore.data.first()[keyActiveMission] ?: 0
        _activeMissionId = id
        return id
    }

    suspend fun update(serverUrl: String? = null, callsign: String? = null, team: String? = null) {
        context.dataStore.edit { prefs ->
            serverUrl?.let { prefs[keyServerUrl] = it.trimEnd('/') }
            callsign?.let { prefs[keyCallsign] = it }
            team?.let { prefs[keyTeam] = it }
        }
    }

    suspend fun setBasemap(name: String) {
        context.dataStore.edit { it[keyBasemap] = name }
    }

    companion object {
        const val DEFAULT_SERVER = "http://192.168.0.240:6001"
    }
}
