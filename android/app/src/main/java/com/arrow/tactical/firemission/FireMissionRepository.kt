package com.arrow.tactical.firemission

import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.FireMissionDto
import com.arrow.tactical.network.FireMissionIn
import kotlinx.serialization.encodeToString

class FireMissionRepository(private val api: ApiClient) {

    suspend fun submit(payload: FireMissionIn): Result<FireMissionDto> = runCatching {
        val r = api.postJson("/fire-missions", api.json.encodeToString(payload))
        require(r.ok) { "fire mission failed: ${r.code} ${r.body}" }
        api.json.decodeFromString<FireMissionDto>(r.body)
    }

    suspend fun list(): Result<List<FireMissionDto>> = runCatching {
        val r = api.get("/fire-missions")
        require(r.ok) { "list failed: ${r.code}" }
        api.json.decodeFromString<List<FireMissionDto>>(r.body)
    }
}
