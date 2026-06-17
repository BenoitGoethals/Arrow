namespace Arrow.Core.Configuration;

/// <summary>Runtime configuration injected into the HTTP + WebSocket clients.</summary>
public sealed class ArrowOptions
{
    public string ServerUrl { get; set; } = "http://localhost:6001";
    public string Token     { get; set; } = string.Empty;
    public TimeSpan HttpTimeout { get; set; } = TimeSpan.FromSeconds(30);

    public Uri WebSocketUri =>
        new(ServerUrl.Replace("http://", "ws://", StringComparison.OrdinalIgnoreCase)
                     .Replace("https://", "wss://", StringComparison.OrdinalIgnoreCase)
            + $"/ws?token={Uri.EscapeDataString(Token)}");
}
