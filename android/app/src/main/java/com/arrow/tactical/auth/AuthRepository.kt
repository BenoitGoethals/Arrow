package com.arrow.tactical.auth

import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.MfaVerifyIn
import com.arrow.tactical.network.OperatorDto
import com.arrow.tactical.network.RegisterIn
import com.arrow.tactical.network.TokenDto
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

class AuthRepository(
    private val api: ApiClient,
    private val tokenStore: TokenStore,
) {
    private val json: Json = api.json

    suspend fun login(callsign: String, password: String): Result<TokenDto> = runCatching {
        val r = api.postForm("/auth/login", mapOf("username" to callsign, "password" to password))
        require(r.ok) { "login failed: ${r.code} ${r.body}" }
        val token = json.decodeFromString<TokenDto>(r.body)
        // If MFA is required the access_token is null — caller handles the second step
        if (!token.mfaRequired && token.accessToken != null) {
            tokenStore.save(token.accessToken, token.role)
        }
        token
    }

    suspend fun verifyMfa(mfaSession: String, code: String): Result<TokenDto> = runCatching {
        val body = json.encodeToString(MfaVerifyIn(mfaSession = mfaSession, code = code))
        val r = api.postJson("/auth/mfa/verify", body)
        require(r.ok) { "MFA verification failed: ${r.code} ${r.body}" }
        val token = json.decodeFromString<TokenDto>(r.body)
        if (token.accessToken != null) tokenStore.save(token.accessToken, token.role)
        token
    }

    suspend fun logout(): Result<Unit> = runCatching {
        api.postJson("/auth/logout", "{}")
        tokenStore.clear()
    }

    suspend fun register(payload: RegisterIn): Result<TokenDto> = runCatching {
        val r = api.postJson("/auth/register", json.encodeToString(payload))
        require(r.ok) { "register failed: ${r.code} ${r.body}" }
        val token = json.decodeFromString<TokenDto>(r.body)
        if (token.accessToken != null) tokenStore.save(token.accessToken, token.role)
        token
    }

    suspend fun me(): Result<OperatorDto> = runCatching {
        val r = api.get("/auth/me")
        require(r.ok) { "me failed: ${r.code}" }
        json.decodeFromString<OperatorDto>(r.body)
    }
}
