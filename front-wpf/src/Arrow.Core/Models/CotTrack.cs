using System.Text.Json.Serialization;

namespace Arrow.Core.Models;

public sealed record CotTrack
{
    [JsonPropertyName("id")]        public int     Id        { get; init; }
    [JsonPropertyName("cot_uid")]   public string  CotUid    { get; init; } = string.Empty;
    [JsonPropertyName("cot_type")]  public string  CotType   { get; init; } = string.Empty;
    [JsonPropertyName("sidc")]      public string? Sidc      { get; init; }
    [JsonPropertyName("callsign")]  public string  Callsign  { get; init; } = string.Empty;
    [JsonPropertyName("latitude")]  public double  Latitude  { get; init; }
    [JsonPropertyName("longitude")] public double  Longitude { get; init; }
    [JsonPropertyName("hae")]       public double  Hae       { get; init; }
    [JsonPropertyName("speed")]     public double  Speed     { get; init; }
    [JsonPropertyName("course")]    public double  Course    { get; init; }
    [JsonPropertyName("team")]      public string? Team      { get; init; }
    [JsonPropertyName("remarks")]   public string? Remarks   { get; init; }
    [JsonPropertyName("last_seen")] public DateTime? LastSeen { get; init; }
}
