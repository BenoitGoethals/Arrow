using System.Text.Json.Serialization;

namespace Arrow.Core.Models;

public sealed record LoginRequest(
    [property: JsonPropertyName("username")] string Username,
    [property: JsonPropertyName("password")] string Password);

public sealed record LoginResponse
{
    [JsonPropertyName("access_token")] public string AccessToken { get; init; } = string.Empty;
    [JsonPropertyName("token_type")]   public string TokenType   { get; init; } = "bearer";
}

/// <summary>The credentials we persist between sessions (Windows Credential Manager).</summary>
public sealed record StoredCredentials(string ServerUrl, string Callsign, string Token);
