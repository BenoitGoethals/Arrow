using System.Text.Json.Serialization;

namespace Arrow.Core.Models;

/// <summary>
/// An Arrow operator (own forces).  Mirrors the server-side OperatorOut schema.
/// </summary>
public sealed record Operator
{
    [JsonPropertyName("id")]         public int     Id          { get; init; }
    [JsonPropertyName("callsign")]   public string  Callsign    { get; init; } = string.Empty;
    [JsonPropertyName("rank")]       public string? Rank        { get; init; }
    [JsonPropertyName("role")]       public string  Role        { get; init; } = "OPERATOR";
    [JsonPropertyName("status")]     public string  Status      { get; init; } = "OFFLINE";
    [JsonPropertyName("ops_status")] public string  OpsStatus   { get; init; } = "OPS";
    [JsonPropertyName("team_id")]    public int?    TeamId      { get; init; }
    [JsonPropertyName("team_role")]  public string? TeamRole    { get; init; }
    [JsonPropertyName("mission_id")] public int?    MissionId   { get; init; }
    [JsonPropertyName("latitude")]   public double? Latitude    { get; init; }
    [JsonPropertyName("longitude")]  public double? Longitude   { get; init; }
    [JsonPropertyName("altitude")]   public double? Altitude    { get; init; }
    [JsonPropertyName("position_source")] public string? PositionSource { get; init; }
    [JsonPropertyName("last_seen")]  public DateTime? LastSeen   { get; init; }
    [JsonPropertyName("online")]     public bool    Online      { get; init; }
}
