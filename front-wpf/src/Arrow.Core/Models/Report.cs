using System.Text.Json.Serialization;

namespace Arrow.Core.Models;

public sealed record Report
{
    [JsonPropertyName("id")]          public int    Id         { get; init; }
    [JsonPropertyName("type")]        public string Type       { get; init; } = string.Empty;
    [JsonPropertyName("operator_id")] public int    OperatorId { get; init; }
    [JsonPropertyName("callsign")]    public string? Callsign  { get; init; }
    [JsonPropertyName("payload")]     public string? Payload   { get; init; }
    [JsonPropertyName("status")]      public string Status     { get; init; } = "RECEIVED";
    [JsonPropertyName("timestamp")]   public DateTime? Timestamp { get; init; }
    [JsonPropertyName("source")]      public string? Source    { get; init; }
}
