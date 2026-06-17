using System.Text.Json.Serialization;

namespace Arrow.Core.Models;

/// <summary>Org-chart returned by GET /hierarchy.</summary>
public sealed record Hierarchy
{
    [JsonPropertyName("companies")] public IReadOnlyList<Company> Companies { get; init; } = [];
    [JsonPropertyName("unassigned_operators")] public IReadOnlyList<Operator> UnassignedOperators { get; init; } = [];
}

public sealed record Company
{
    [JsonPropertyName("id")]       public int    Id       { get; init; }
    [JsonPropertyName("name")]     public string Name     { get; init; } = string.Empty;
    [JsonPropertyName("platoons")] public IReadOnlyList<Platoon> Platoons { get; init; } = [];
}

public sealed record Platoon
{
    [JsonPropertyName("id")]       public int    Id       { get; init; }
    [JsonPropertyName("name")]     public string Name     { get; init; } = string.Empty;
    [JsonPropertyName("sections")] public IReadOnlyList<Section> Sections { get; init; } = [];
}

public sealed record Section
{
    [JsonPropertyName("id")]    public int    Id    { get; init; }
    [JsonPropertyName("name")]  public string Name  { get; init; } = string.Empty;
    [JsonPropertyName("teams")] public IReadOnlyList<Team> Teams { get; init; } = [];
}

public sealed record Team
{
    [JsonPropertyName("id")]        public int    Id        { get; init; }
    [JsonPropertyName("name")]      public string Name      { get; init; } = string.Empty;
    [JsonPropertyName("operators")] public IReadOnlyList<Operator> Operators { get; init; } = [];
}
