package com.arrow.tactical.auth

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.profileDataStore by preferencesDataStore(name = "arrow_profile")

data class OperatorProfile(
    val id: Int = 0,
    val callsign: String = "",
    val rank: String = "",
    val role: String = "",
    val teamRole: String? = null,
    val teamId: Int? = null,
    val teamName: String? = null,
    val sectionName: String? = null,
    val platoonName: String? = null,
    val companyName: String? = null,
    val missionId: Int? = null,
    val missionName: String? = null,
    val clearance: Int = 0,
)

class ProfileStore(private val context: Context) {

    private val kId          = intPreferencesKey("op_id")
    private val kCallsign    = stringPreferencesKey("op_callsign")
    private val kRank        = stringPreferencesKey("op_rank")
    private val kRole        = stringPreferencesKey("op_role")
    private val kTeamRole    = stringPreferencesKey("op_team_role")
    private val kTeamId      = intPreferencesKey("op_team_id")
    private val kTeamName    = stringPreferencesKey("op_team_name")
    private val kSectionName = stringPreferencesKey("op_section_name")
    private val kPlatoonName = stringPreferencesKey("op_platoon_name")
    private val kCompanyName = stringPreferencesKey("op_company_name")
    private val kMissionId   = intPreferencesKey("op_mission_id")
    private val kMissionName = stringPreferencesKey("op_mission_name")
    private val kClearance   = intPreferencesKey("op_clearance")

    val profile: Flow<OperatorProfile?> = context.profileDataStore.data.map { p ->
        val callsign = p[kCallsign] ?: return@map null
        OperatorProfile(
            id          = p[kId] ?: 0,
            callsign    = callsign,
            rank        = p[kRank] ?: "",
            role        = p[kRole] ?: "",
            teamRole    = p[kTeamRole],
            teamId      = p[kTeamId],
            teamName    = p[kTeamName],
            sectionName = p[kSectionName],
            platoonName = p[kPlatoonName],
            companyName = p[kCompanyName],
            missionId   = p[kMissionId],
            missionName = p[kMissionName],
            clearance   = p[kClearance] ?: 0,
        )
    }

    suspend fun current(): OperatorProfile? = profile.first()

    suspend fun save(p: OperatorProfile) {
        context.profileDataStore.edit { prefs ->
            prefs[kId]       = p.id
            prefs[kCallsign] = p.callsign
            prefs[kRank]     = p.rank
            prefs[kRole]     = p.role
            if (p.teamRole    != null) prefs[kTeamRole]    = p.teamRole    else prefs.remove(kTeamRole)
            if (p.teamId      != null) prefs[kTeamId]      = p.teamId      else prefs.remove(kTeamId)
            if (p.teamName    != null) prefs[kTeamName]    = p.teamName    else prefs.remove(kTeamName)
            if (p.sectionName != null) prefs[kSectionName] = p.sectionName else prefs.remove(kSectionName)
            if (p.platoonName != null) prefs[kPlatoonName] = p.platoonName else prefs.remove(kPlatoonName)
            if (p.companyName != null) prefs[kCompanyName] = p.companyName else prefs.remove(kCompanyName)
            if (p.missionId   != null) prefs[kMissionId]   = p.missionId   else prefs.remove(kMissionId)
            if (p.missionName != null) prefs[kMissionName] = p.missionName else prefs.remove(kMissionName)
            prefs[kClearance] = p.clearance
        }
    }

    suspend fun clear() {
        context.profileDataStore.edit { it.clear() }
    }
}
