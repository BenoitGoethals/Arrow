package com.arrow.tactical.auth

import com.arrow.tactical.network.ApiClient
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
        tokenStore.save(token.accessToken, token.role)
        token
    }

    suspend fun register(payload: RegisterIn): Result<TokenDto> = runCatching {
        val r = api.postJson("/auth/register", json.encodeToString(payload))
        require(r.ok) { "register failed: ${r.code} ${r.body}" }
        val token = json.decodeFromString<TokenDto>(r.body)
        tokenStore.save(token.accessToken, token.role)
        token
    }

    suspend fun me(): Result<OperatorDto> = runCatching {
        val r = api.get("/auth/me")
        require(r.ok) { "me failed: ${r.code}" }
        json.decodeFromString<OperatorDto>(r.body)
    }

    suspend fun logout() {
        tokenStore.clear()
    }
}
