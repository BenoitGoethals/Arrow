using System.Text.Json.Serialization;

namespace Arrow.Core.Models;

public sealed record Message
{
    [JsonPropertyName("id")]              public int    Id            { get; init; }
    [JsonPropertyName("sender_id")]       public int    SenderId      { get; init; }
    [JsonPropertyName("sender_callsign")] public string? SenderCallsign { get; init; }
    [JsonPropertyName("receiver_id")]     public int?   ReceiverId    { get; init; }
    [JsonPropertyName("group_id")]        public string? GroupId      { get; init; }
    [JsonPropertyName("content")]         public string Content       { get; init; } = string.Empty;
    [JsonPropertyName("timestamp")]       public DateTime Timestamp   { get; init; }
    [JsonPropertyName("message_type")]    public string MessageType   { get; init; } = "DIRECT";
    [JsonPropertyName("photo_id")]        public int?   PhotoId       { get; init; }
    [JsonPropertyName("photo_mime_type")] public string? PhotoMimeType { get; init; }
    [JsonPropertyName("source")]          public string? Source       { get; init; }
}

public sealed record MessageDraft(
    string Content,
    int? ReceiverId = null,
    string? GroupId = null,
    string MessageType = "DIRECT",
    int? PhotoId = null);
