using System.Text.Json.Serialization;

namespace Arrow.Core.Models;

public sealed record Mission
{
    [JsonPropertyName("id")]             public int    Id          { get; init; }
    [JsonPropertyName("name")]           public string Name        { get; init; } = string.Empty;
    [JsonPropertyName("status")]         public string Status      { get; init; } = "PLANNING";
    [JsonPropertyName("created_by")]     public int?   CreatedBy   { get; init; }
    [JsonPropertyName("created_at")]     public DateTime? CreatedAt { get; init; }
    [JsonPropertyName("map_center_lat")] public double? MapCenterLat { get; init; }
    [JsonPropertyName("map_center_lng")] public double? MapCenterLng { get; init; }
    [JsonPropertyName("map_zoom")]       public int?   MapZoom     { get; init; }
}
