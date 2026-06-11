package com.arrow.tactical.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

@Serializable
data class MissionDto(
    val id: Int,
    val name: String,
    val description: String = "",
    val status: String = "PLANNING",   // PLANNING | ACTIVE | ENDED
    @SerialName("created_by")  val createdBy: Int = -1,
    @SerialName("created_at")  val createdAt: String = "",
    @SerialName("started_at")  val startedAt: String? = null,
    @SerialName("ended_at")    val endedAt: String? = null,
    @SerialName("snapshot_at") val snapshotAt: String? = null,
    @SerialName("map_center_lat")  val mapCenterLat: Double? = null,
    @SerialName("map_center_lng")  val mapCenterLng: Double? = null,
    @SerialName("map_zoom")        val mapZoom: Int = 13,
    @SerialName("map_center_mgrs") val mapCenterMgrs: String? = null,
)

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
    @SerialName("team_id")   val teamId: Int? = null,
    @SerialName("team_role") val teamRole: String? = null,
    @SerialName("mission_id") val missionId: Int? = null,
    val latitude: Double? = null,
    val longitude: Double? = null,
    val altitude: Double? = null,
    val online: Boolean = false,   // computed by backend: status=ONLINE + last_seen ≤ 90s
    // Source of the last position fix: "ATAK" (device via CoT TCP), "APP", or null.
    @SerialName("position_source") val positionSource: String? = null,
)

@Serializable
data class TeamDto(
    val id: Int,
    val name: String,
    @SerialName("section_id") val sectionId: Int,
)

@Serializable
data class SectionDto(
    val id: Int,
    val name: String,
    @SerialName("platoon_id") val platoonId: Int,
)

@Serializable
data class PlatoonDto(
    val id: Int,
    val name: String,
    @SerialName("company_id") val companyId: Int,
)

@Serializable
data class CompanyDto(
    val id: Int,
    val name: String,
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
    @SerialName("photo_id") val photoId: Int? = null,
    @SerialName("photo_mime_type") val photoMimeType: String? = null,
)

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

// ── CAS DTOs ──────────────────────────────────────────────────────────────

@Serializable
data class CasAssetDto(
    val id: Int,
    val callsign: String,
    @SerialName("aircraft_type") val aircraftType: String = "",
    val ordnance: String = "",
    val frequency: String = "",
    val status: String = "AVAILABLE",   // AVAILABLE | ON_STATION | TASKED | RTB | UNAVAILABLE
    @SerialName("available_from") val availableFrom: String? = null,
    @SerialName("available_to")   val availableTo: String? = null,
    val notes: String = "",
    @SerialName("mission_id") val missionId: Int? = null,
)

@Serializable
data class CasNineLinerIn(
    // 9-liner lines
    @SerialName("line_1") val line1: String = "",
    @SerialName("line_2") val line2: String = "",
    @SerialName("line_3") val line3: String = "",
    @SerialName("line_4") val line4: String = "",
    @SerialName("line_5_mgrs") val line5Mgrs: String = "",
    @SerialName("line_5_lat")  val line5Lat: Double? = null,
    @SerialName("line_5_lon")  val line5Lon: Double? = null,
    @SerialName("line_6") val line6: String = "",
    @SerialName("line_7") val line7: String = "",
    @SerialName("line_8") val line8: String = "",
    @SerialName("line_9") val line9: String = "",
    // CAS metadata
    val tic: Boolean = false,
    @SerialName("fo_operator_id") val foOperatorId: Int? = null,
    @SerialName("asset_id") val assetId: Int? = null,
)

// ── Strike Package DTOs ────────────────────────────────────────────────────

@Serializable
data class StrikePackageListDto(
    val id: Int,
    val name: String,
    val status: String,
    @SerialName("mission_id") val missionId: Int? = null,
)

@Serializable
data class SpOperator(
    val id: Int,
    val callsign: String,
    val rank: String = "",
    val role: String = "OPERATOR",
    val status: String = "OFFLINE",
    val latitude: Double? = null,
    val longitude: Double? = null,
)

@Serializable
data class SpFireMission(
    val id: Int,
    val latitude: Double,
    val longitude: Double,
    @SerialName("mission_type") val missionType: String,
    val ammunition: String,
    val status: String,
    val quantity: Int = 1,
)

@Serializable
data class SpReport(
    val id: Int,
    val type: String,
    val status: String,
    val payload: JsonObject = JsonObject(emptyMap()),
)

@Serializable
data class SpDrone(
    val callsign: String = "",
    val platform: String = "",
    @SerialName("loiter_lat") val loiterLat: Double? = null,
    @SerialName("loiter_lon") val loiterLon: Double? = null,
    @SerialName("feed_url") val feedUrl: String = "",
    val notes: String = "",
)

@Serializable
data class SpIsr(
    val sensor: String = "",
    val platform: String = "",
    @SerialName("collection_priority") val collectionPriority: String = "MEDIUM",
    val notes: String = "",
)

@Serializable
data class SpCas(
    val aircraft: String = "",
    val callsign: String = "",
    val ordnance: String = "",
    @SerialName("station_time_min") val stationTimeMin: Int = 0,
    val frequency: String = "",
    val notes: String = "",
)

@Serializable
data class SpSniper(
    val callsign: String = "",
    @SerialName("position_lat") val positionLat: Double? = null,
    @SerialName("position_lon") val positionLon: Double? = null,
    @SerialName("sector_of_fire") val sectorOfFire: String = "",
    @SerialName("engagement_criteria") val engagementCriteria: String = "",
)

@Serializable
data class SpEw(
    val system: String = "",
    val callsign: String = "",
    @SerialName("frequency_bands") val frequencyBands: String = "",
    val objective: String = "JAM",
    val notes: String = "",
)

@Serializable
data class SpComms(
    @SerialName("primary_freq") val primaryFreq: String = "",
    @SerialName("alternate_freq") val alternateFreq: String = "",
    val waveform: String = "",
    @SerialName("pace_plan") val pacePlan: String = "",
)

@Serializable
data class SpAssaultPlan(
    val phases: List<SpPhase> = emptyList(),
    @SerialName("breach_points") val breachPoints: List<String> = emptyList(),
    @SerialName("actions_on_objective") val actionsOnObjective: String = "",
    val consolidation: String = "",
)

@Serializable
data class SpPhase(
    val name: String = "",
    val description: String = "",
    val actions: String = "",
)

@Serializable
data class SpExfilRoute(
    val name: String = "",
    val type: String = "GROUND",
    val description: String = "",
    @SerialName("tactical_object_id") val tacticalObjectId: Int? = null,
)

@Serializable
data class SpAssets(
    val drones: List<SpDrone> = emptyList(),
    val isr: List<SpIsr> = emptyList(),
    @SerialName("air_support") val airSupport: List<SpCas> = emptyList(),
    @SerialName("sniper_overwatch") val sniperOverwatch: List<SpSniper> = emptyList(),
    @SerialName("electronic_warfare") val electronicWarfare: List<SpEw> = emptyList(),
    val comms: SpComms = SpComms(),
    @SerialName("assault_plan") val assaultPlan: SpAssaultPlan = SpAssaultPlan(),
    @SerialName("exfil_routes") val exfilRoutes: List<SpExfilRoute> = emptyList(),
)

@Serializable
data class StrikePackageBundleDto(
    val id: Int,
    val name: String,
    val status: String,
    @SerialName("mission_id") val missionId: Int? = null,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
    @SerialName("target_lat") val targetLat: Double? = null,
    @SerialName("target_lon") val targetLon: Double? = null,
    @SerialName("target_description") val targetDescription: String = "",
    val assets: SpAssets = SpAssets(),
    val operators: List<SpOperator> = emptyList(),
    @SerialName("tactical_objects") val tacticalObjects: List<TacticalObjectDto> = emptyList(),
    @SerialName("fire_missions") val fireMissions: List<SpFireMission> = emptyList(),
    val reports: List<SpReport> = emptyList(),
)
