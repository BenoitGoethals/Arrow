package com.arrow.tactical.cas

import com.arrow.tactical.auth.TokenStore
import com.arrow.tactical.network.ApiClient
import com.arrow.tactical.network.CasAssetDto
import com.arrow.tactical.network.CasNineLinerIn
import com.arrow.tactical.network.ReportDto
import com.arrow.tactical.sync.ConnectivityObserver
import kotlinx.serialization.encodeToString

class CasRepository(
    private val api: ApiClient,
    private val tokenStore: TokenStore,
    private val connectivity: ConnectivityObserver,
) {
    suspend fun listAssets(): Result<List<CasAssetDto>> = runCatching {
        val token = tokenStore.current()
        if (token.isNullOrBlank()) return@runCatching emptyList()
        val r = api.get("/cas/assets")
        if (!r.ok) return@runCatching emptyList()
        api.json.decodeFromString(r.body)
    }

    suspend fun submitRequest(body: CasNineLinerIn): Result<ReportDto> = runCatching {
        val token = tokenStore.current()
        if (token.isNullOrBlank()) error("Not authenticated — please log in again")
        if (!connectivity.hasActiveConnection()) error("No network connection")
        val r = api.postJson("/cas/requests", api.json.encodeToString(body))
        if (!r.ok) error("CAS request failed (${r.code}): ${r.body.take(200)}")
        api.json.decodeFromString(r.body)
    }
}
