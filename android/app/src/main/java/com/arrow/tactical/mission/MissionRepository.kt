package com.arrow.tactical.mission

import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.MissionDto
import com.arrow.tactical.settings.SettingsRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

class MissionRepository(
    private val api: ApiClient,
    private val settings: SettingsRepository,
) {
    // The currently-selected mission for this session.
    // Persisted across restarts via SettingsRepository.
    private val _activeMission = MutableStateFlow<MissionDto?>(null)
    val activeMission: StateFlow<MissionDto?> = _activeMission

    init {
        // Restore persisted mission id — the actual DTO is fetched lazily on
        // the mission-selection screen or on first list call.
        val savedId = settings.activeMissionId
        if (savedId > 0) api.activeMissionId = savedId
    }

    suspend fun listMissions(): Result<List<MissionDto>> = runCatching {
        val r = api.get("/missions")
        require(r.ok) { "HTTP ${r.code}" }
        api.json.decodeFromString<List<MissionDto>>(r.body)
    }

    suspend fun getMission(id: Int): Result<MissionDto> = runCatching {
        val r = api.get("/missions/$id")
        require(r.ok) { "HTTP ${r.code}" }
        api.json.decodeFromString<MissionDto>(r.body)
    }

    suspend fun createMission(
        name: String,
        description: String = "",
        mapCenterLat: Double? = null,
        mapCenterLng: Double? = null,
        mapZoom: Int = 13,
    ): Result<MissionDto> = runCatching {
        val body = buildJsonObject {
            put("name", name)
            put("description", description)
            put("map_zoom", mapZoom)
            if (mapCenterLat != null && mapCenterLng != null) {
                put("map_center_lat", mapCenterLat)
                put("map_center_lng", mapCenterLng)
            }
        }.toString()
        val r = api.postJson("/missions", body)
        require(r.ok) { "HTTP ${r.code}: ${r.body}" }
        api.json.decodeFromString<MissionDto>(r.body)
    }

    suspend fun startMission(id: Int): Result<MissionDto> = runCatching {
        val r = api.postJson("/missions/$id/start", "")
        require(r.ok) { "HTTP ${r.code}" }
        api.json.decodeFromString<MissionDto>(r.body)
    }

    suspend fun endMission(id: Int): Result<MissionDto> = runCatching {
        val r = api.postJson("/missions/$id/end", "")
        require(r.ok) { "HTTP ${r.code}" }
        api.json.decodeFromString<MissionDto>(r.body)
    }

    fun selectMission(mission: MissionDto?) {
        _activeMission.value = mission
        api.activeMissionId  = mission?.id
        settings.activeMissionId = mission?.id ?: 0
    }

    fun clearMission() = selectMission(null)
}
