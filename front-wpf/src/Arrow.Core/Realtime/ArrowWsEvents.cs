using System.Text.Json;

namespace Arrow.Core.Realtime;

/// <summary>One channel event off the WebSocket.</summary>
public sealed record ArrowWsEvent(string Channel, string Event, JsonElement Data, int? MissionId)
{
    public TPayload? DataAs<TPayload>() =>
        Data.ValueKind == JsonValueKind.Undefined || Data.ValueKind == JsonValueKind.Null
            ? default
            : JsonSerializer.Deserialize<TPayload>(Data.GetRawText());
}

/// <summary>Channels we know about — mirrors backend.websocket.manager.</summary>
public static class ArrowChannels
{
    public const string Tracking       = "tracking";
    public const string CotTrack       = "cot-track";
    public const string CotPresence    = "cot-presence";
    public const string Presence       = "presence";
    public const string Alert          = "alert";
    public const string Report         = "report";
    public const string Chat           = "chat";
    public const string TacticalObject = "tactical-object";
    public const string Vehicle        = "vehicle";
    public const string FireMission    = "fire-mission";
    public const string KmlLayer       = "kml-layer";
    public const string Mission        = "mission";
    public const string StrikePackage  = "strike-package";
    public const string Stream         = "stream";
    public const string AtakShape      = "atak-shape";
}
