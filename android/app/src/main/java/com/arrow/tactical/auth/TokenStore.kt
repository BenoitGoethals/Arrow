package com.arrow.tactical.auth

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.tokenDataStore by preferencesDataStore(name = "arrow_auth")

class TokenStore(private val context: Context) {
    private val keyToken = stringPreferencesKey("jwt")
    private val keyRole = stringPreferencesKey("role")

    val tokenFlow: Flow<String?> = context.tokenDataStore.data.map { it[keyToken] }
    val roleFlow: Flow<String?> = context.tokenDataStore.data.map { it[keyRole] }

    suspend fun current(): String? = tokenFlow.first()
    suspend fun currentRole(): String? = roleFlow.first()

    suspend fun save(token: String, role: String) {
        context.tokenDataStore.edit {
            it[keyToken] = token
            it[keyRole] = role
        }
    }

    suspend fun clear() {
        context.tokenDataStore.edit {
            it.remove(keyToken)
            it.remove(keyRole)
        }
    }
}
