package com.arrow.tactical.auth

import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.CompanyDto
import com.arrow.tactical.network.MfaVerifyIn
import com.arrow.tactical.network.OperatorDto
import com.arrow.tactical.network.PlatoonDto
import com.arrow.tactical.network.RegisterIn
import com.arrow.tactical.network.SectionDto
import com.arrow.tactical.network.TeamDto
import com.arrow.tactical.network.TokenDto
import com.arrow.tactical.settings.SettingsRepository
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

class AuthRepository(
    private val api: ApiClient,
    private val tokenStore: TokenStore,
    private val profileStore: ProfileStore,
    private val settingsRepo: SettingsRepository,
) {
    private val json: Json = api.json

    suspend fun login(callsign: String, password: String): Result<TokenDto> = runCatching {
        val r = api.postForm("/auth/login", mapOf("username" to callsign, "password" to password))
        require(r.ok) { "login failed: ${r.code} ${r.body}" }
        val token = json.decodeFromString<TokenDto>(r.body)
        if (!token.mfaRequired && token.accessToken != null) {
            tokenStore.save(token.accessToken, token.role)
            api.setToken(token.accessToken)
            refreshProfile()
        }
        token
    }

    suspend fun verifyMfa(mfaSession: String, code: String): Result<TokenDto> = runCatching {
        val body = json.encodeToString(MfaVerifyIn(mfaSession = mfaSession, code = code))
        val r = api.postJson("/auth/mfa/verify", body)
        require(r.ok) { "MFA verification failed: ${r.code} ${r.body}" }
        val token = json.decodeFromString<TokenDto>(r.body)
        if (token.accessToken != null) {
            tokenStore.save(token.accessToken, token.role)
            api.setToken(token.accessToken)
            refreshProfile()
        }
        token
    }

    suspend fun logout(): Result<Unit> = runCatching {
        api.postJson("/auth/logout", "{}")
        api.setToken(null)
        tokenStore.clear()
        profileStore.clear()
    }

    suspend fun register(payload: RegisterIn): Result<TokenDto> = runCatching {
        val r = api.postJson("/auth/register", json.encodeToString(payload))
        require(r.ok) { "register failed: ${r.code} ${r.body}" }
        val token = json.decodeFromString<TokenDto>(r.body)
        if (token.accessToken != null) {
            tokenStore.save(token.accessToken, token.role)
            api.setToken(token.accessToken)
            refreshProfile()
        }
        token
    }

    suspend fun me(): Result<OperatorDto> = runCatching {
        val r = api.get("/auth/me")
        require(r.ok) { "me failed: ${r.code}" }
        json.decodeFromString<OperatorDto>(r.body)
    }

    /** Fetch the full operator profile and resolve hierarchy names, then persist both. */
    suspend fun refreshProfile() {
        val meResult = me().getOrNull() ?: return

        var teamName: String? = null
        var sectionName: String? = null
        var platoonName: String? = null
        var companyName: String? = null

        val teamId = meResult.teamId
        if (teamId != null) {
            runCatching {
                val teams    = json.decodeFromString<List<TeamDto>>(api.get("/teams").body)
                val sections = json.decodeFromString<List<SectionDto>>(api.get("/sections").body)
                val platoons = json.decodeFromString<List<PlatoonDto>>(api.get("/platoons").body)
                val companies = json.decodeFromString<List<CompanyDto>>(api.get("/companies").body)

                val team    = teams.find { it.id == teamId }
                val section = team?.let { sections.find { s -> s.id == it.sectionId } }
                val platoon = section?.let { platoons.find { p -> p.id == it.platoonId } }
                val company = platoon?.let { companies.find { c -> c.id == it.companyId } }

                teamName    = team?.name
                sectionName = section?.name
                platoonName = platoon?.name
                companyName = company?.name
            }
        }

        var missionName: String? = null
        val missionId = meResult.missionId
        if (missionId != null) {
            runCatching {
                // Reuse the already-parsed MissionDto from the existing DTO
                val r = api.get("/missions/$missionId")
                if (r.ok) {
                    val mission = json.decodeFromString<com.arrow.tactical.network.MissionDto>(r.body)
                    missionName = mission.name
                }
            }
        }

        val profile = OperatorProfile(
            id          = meResult.id,
            callsign    = meResult.callsign,
            rank        = meResult.rank,
            role        = meResult.role,
            teamRole    = meResult.teamRole,
            teamId      = meResult.teamId,
            teamName    = teamName,
            sectionName = sectionName,
            platoonName = platoonName,
            companyName = companyName,
            missionId   = meResult.missionId,
            missionName = missionName,
        )
        profileStore.save(profile)
        // Keep callsign in sync so tracking service picks it up
        settingsRepo.update(callsign = meResult.callsign)
    }
}
