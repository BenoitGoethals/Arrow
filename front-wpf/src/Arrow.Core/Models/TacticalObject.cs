using System.Text.Json.Serialization;

namespace Arrow.Core.Models;

public sealed record TacticalObject
{
    [JsonPropertyName("id")]          public int    Id          { get; init; }
    [JsonPropertyName("type")]        public string Type        { get; init; } = string.Empty;
    [JsonPropertyName("symbol_code")] public string? SymbolCode { get; init; }
    [JsonPropertyName("latitude")]    public double Latitude    { get; init; }
    [JsonPropertyName("longitude")]   public double Longitude   { get; init; }
    [JsonPropertyName("notes")]       public string? Notes      { get; init; }
    [JsonPropertyName("affiliation")] public string Affiliation { get; init; } = "FRIENDLY";
    [JsonPropertyName("rotation")]    public double Rotation    { get; init; }
    [JsonPropertyName("echelon")]     public string? Echelon    { get; init; }
    [JsonPropertyName("geometry")]    public string? Geometry   { get; init; }
    [JsonPropertyName("photo_id")]    public int?   PhotoId     { get; init; }
    [JsonPropertyName("mission_id")]  public int?   MissionId   { get; init; }
    [JsonPropertyName("created_by")]  public int?   CreatedBy   { get; init; }
    [JsonPropertyName("timestamp")]   public DateTime? Timestamp { get; init; }
}

public sealed record TacticalObjectDraft(
    string Type,
    double Latitude,
    double Longitude,
    string? SymbolCode = null,
    string Affiliation = "FRIENDLY",
    string? Notes = null,
    double Rotation = 0,
    string? Echelon = null,
    string? Geometry = null,
    int? PhotoId = null);

public sealed record TacticalObjectPatch(
    double? Latitude = null,
    double? Longitude = null,
    string? Notes = null,
    double? Rotation = null);
