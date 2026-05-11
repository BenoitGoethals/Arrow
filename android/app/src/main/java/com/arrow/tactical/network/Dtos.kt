package com.arrow.tactical.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

@Serializable
data class TokenDto(
    @SerialName("access_token") val accessToken: String? = null,
    @SerialName("token_type")   val tokenType: String = "bearer",
    val role: String = "",
    @SerialName("mfa_required") val mfaRequired: Boolean = false,
    @SerialName("mfa_session")  val mfaSession: String? = null,
)

@Serializable
data class MfaVerifyIn(
    @SerialName("mfa_session") val mfaSession: String,
    val code: String,
)

@Serializable
data class OperatorDto(
    val id: Int,
    val callsign: String,
    val rank: String,
    val status: String,
    val role: String,
    @SerialName("team_id") val teamId: Int? = null,
    val latitude: Double? = null,
    val longitude: Double? = null,
    val altitude: Double? = null,
    val online: Boolean = false,   // computed by backend: status=ONLINE + last_seen ≤ 90s
)

@Serializable
data class PositionPayload(
    val latitude: Double,
    val longitude: Double,
    val altitude: Double? = null,
)

@Serializable
data class TacticalObjectDto(
    val id: Int,
    val type: String,
    @SerialName("symbol_code") val symbolCode: String = "",
    @SerialName("created_by") val createdBy: Int,
    val latitude: Double,
    val longitude: Double,
    val notes: String = "",
    val visibility: String = "COMPANY",
    @SerialName("photo_id") val photoId: Int? = null,
    // Tactical control graphics: heading clockwise from north (0..360) for
    // oriented point symbols; full geometry JSON for lines/polygons; NATO
    // echelon designator (TM/SEC/PL/COY/BN/BDE) for size annotation.
    val rotation: Double = 0.0,
    val geometry: String = "",
    val echelon: String = "",
    // NATO affiliation drives the TG colour (FRIENDLY/ENEMY/UNKNOWN).
    val affiliation: String = "FRIENDLY",
)

@Serializable
data class TacticalObjectIn(
    val type: String,
    @SerialName("symbol_code") val symbolCode: String = "",
    val latitude: Double,
    val longitude: Double,
    val notes: String = "",
    val visibility: String = "COMPANY",
    @SerialName("photo_id") val photoId: Int? = null,
    val affiliation: String = "FRIENDLY",
)

@Serializable
data class AlertIn(
    val type: String,
    val latitude: Double? = null,
    val longitude: Double? = null,
)

@Serializable
data class AlertDto(
    val id: Int,
    val type: String,
    @SerialName("operator_id") val operatorId: Int,
    val latitude: Double? = null,
    val longitude: Double? = null,
    val status: String,
)

@Serializable
data class MessageIn(
    @SerialName("receiver_id") val receiverId: Int? = null,
    @SerialName("group_id") val groupId: String? = null,
    val content: String,
    @SerialName("message_type") val messageType: String = "DIRECT",
    @SerialName("photo_id") val photoId: Int? = null,
)

@Serializable
data class MessageDto(
    val id: Int,
    @SerialName("sender_id") val senderId: Int,
    @SerialName("receiver_id") val receiverId: Int? = null,
    @SerialName("group_id") val groupId: String? = null,
    val content: String,
    @SerialName("message_type") val messageType: String,
    @SerialName("photo_id") val photoId: Int? = null,)

@Serializable
data class ReportIn(
    val type: String,
    val payload: JsonObject,
)

@Serializable
data class ReportDto(
    val id: Int,
    @SerialName("operator_id") val operatorId: Int,
    val type: String,
    val payload: String,          // JSON-encoded on server, parsed as-needed client-side
    val timestamp: String? = null,
    val status: String = "RECEIVED",
    @SerialName("reviewer_note") val reviewerNote: String = "",
)

@Serializable
data class FireMissionIn(
    val latitude:     Double,
    val longitude:    Double,
    val altitude:     Double  = 0.0,
    val direction:    Double,
    @SerialName("mission_type") val missionType: String,
    val ammunition:   String,
    val quantity:     Int    = 1,
    val description:  String = "",
)

@Serializable
data class FireMissionDto(
    val id:             Int,
    @SerialName("operator_id")     val operatorId:    Int,
    val latitude:       Double,
    val longitude:      Double,
    val altitude:       Double,
    val direction:      Double,
    @SerialName("mission_type")    val missionType:   String,
    val ammunition:     String,
    val quantity:       Int,
    val description:    String,
    val status:         String,
    @SerialName("fdc_operator_id") val fdcOperatorId: Int? = null,
    val timestamp:      String? = null,
    val notes:          String  = "",
)

// ── L16 81mm mortar plan ─────────────────────────────────────────────────────

@Serializable
data class GunIn(
    val callsign:           String = "",
    val latitude:           Double,
    val longitude:          Double,
    val altitude:           Double = 0.0,
    @SerialName("reference_az_mils") val referenceAzMils: Double = 0.0,
)

@Serializable
data class MortarPlanIn(
    val guns:           List<GunIn>,
    val pattern:        String,
    val target:         JsonObject,
    @SerialName("rounds_per_gun") val roundsPerGun:   Int    = 1,
    @SerialName("target_alt_m")   val targetAltM:     Double = 0.0,
    val ammunition:     String = "HE",
    @SerialName("charge_override") val chargeOverride: Int? = null,
    val description:    String = "",
)

@Serializable
data class FiringSolutionDto(
    val charge:    Int,
    @SerialName("qe_mils")   val qeMils:   Int,
    @SerialName("defl_mils") val deflMils: Int,
    @SerialName("tof_s")     val tofS:     Double,
    @SerialName("mv_ms")     val mvMs:     Double,
    @SerialName("range_m")   val rangeM:   Double,
    @SerialName("azimuth_mils") val azimuthMils: Int,
    val impact:    LatLon,
    val error:     String? = null,
)

@Serializable
data class LatLon(val latitude: Double, val longitude: Double)

@Serializable
data class GunSolutionDto(
    @SerialName("gun_idx")   val gunIdx:   Int,
    val callsign:  String,
    val latitude:  Double,
    val longitude: Double,
    val altitude:  Double = 0.0,
    @SerialName("reference_az_mils") val referenceAzMils: Double = 0.0,
    val solutions: List<FiringSolutionDto>,
)

@Serializable
data class MortarPlanResult(
    val guns:    List<GunSolutionDto>,
    val impacts: List<LatLon>,
    val summary: JsonObject,
)


// ── OPORD ────────────────────────────────────────────────────────────────────

@Serializable
data class OpordSnapshotDto(
    val id: Int,
    val label: String = "",
    val bbox: List<Double> = emptyList(),
    val center: List<Double> = emptyList(),
    val zoom: Double = 0.0,
    @SerialName("photo_id") val photoId: Int,
    val annotations: String = "",
)

@Serializable
data class OpordDto(
    val id: Int,
    val title: String,
    @SerialName("opord_number") val opordNumber: String = "",
    val dtg: String = "",
    @SerialName("time_zone") val timeZone: String = "ZULU",
    val classification: String = "UNCLASSIFIED",
    val references: String = "",
    @SerialName("task_organization") val taskOrganization: String = "",
    val situation: JsonObject = JsonObject(emptyMap()),
    val mission: String = "",
    val execution: JsonObject = JsonObject(emptyMap()),
    val sustainment: JsonObject = JsonObject(emptyMap()),
    @SerialName("command_signal") val commandSignal: JsonObject = JsonObject(emptyMap()),
    @SerialName("map_snapshots") val mapSnapshots: List<OpordSnapshotDto> = emptyList(),
    val status: String = "DRAFT",
    @SerialName("author_id") val authorId: Int = 0,
    @SerialName("recipient_ids") val recipientIds: List<Int> = emptyList(),
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
)

@Serializable
data class RegisterIn(
    val callsign: String,
    val password: String,
    val rank: String = "OR-1",
    val role: String = "OPERATOR",
)
