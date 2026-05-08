package com.arrow.tactical.firemission

import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.FireMissionDto
import com.arrow.tactical.network.FireMissionIn
import com.arrow.tactical.network.MortarPlanIn
import com.arrow.tactical.network.MortarPlanResult
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

    /** Compute firing solutions for 1..4 mortars without persisting. */
    suspend fun solveMortar(plan: MortarPlanIn): Result<MortarPlanResult> = runCatching {
        val r = api.postJson("/fire-missions/solve", api.json.encodeToString(plan))
        require(r.ok) { "solve failed: ${r.code} ${r.body}" }
        api.json.decodeFromString<MortarPlanResult>(r.body)
    }

    /** Persist a mortar plan as a fire mission and broadcast it. */
    suspend fun submitMortar(plan: MortarPlanIn): Result<FireMissionDto> = runCatching {
        val r = api.postJson("/fire-missions/mortar", api.json.encodeToString(plan))
        require(r.ok) { "mortar submit failed: ${r.code} ${r.body}" }
        api.json.decodeFromString<FireMissionDto>(r.body)
    }
}
