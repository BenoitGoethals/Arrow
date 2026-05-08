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

@Serializable
data class RegisterIn(
    val callsign: String,
    val password: String,
    val rank: String = "OR-1",
    val role: String = "OPERATOR",
)
