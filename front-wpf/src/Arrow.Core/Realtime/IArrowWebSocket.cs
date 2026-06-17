namespace Arrow.Core.Realtime;

/// <summary>
/// Long-lived WebSocket client to the Arrow backend.  Drops events from every
/// broadcast channel onto the <see cref="EventReceived"/> handler.  Survives
/// disconnects with exponential backoff.
/// </summary>
public interface IArrowWebSocket : IAsyncDisposable
{
    /// <summary>True when an active socket connection is open.</summary>
    bool IsConnected { get; }

    /// <summary>Fired whenever a JSON message arrives on the socket.</summary>
    event EventHandler<ArrowWsEvent>? EventReceived;

    /// <summary>Fired when the connection state flips.</summary>
    event EventHandler<bool>? ConnectionChanged;

    /// <summary>Start the background reader.  Idempotent.</summary>
    Task StartAsync(CancellationToken ct = default);

    /// <summary>Stop the background reader and close the socket.</summary>
    Task StopAsync();
}
