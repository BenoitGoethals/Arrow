using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using Arrow.Core.Configuration;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Arrow.Core.Realtime;

/// <summary>
/// ClientWebSocket-backed implementation of <see cref="IArrowWebSocket"/>.
/// Reconnects with exponential backoff (2 → 30 s) so transient outages don't
/// require app restart.
/// </summary>
public sealed class ArrowWebSocket : IArrowWebSocket
{
    private readonly IOptionsMonitor<ArrowOptions> _opts;
    private readonly ILogger<ArrowWebSocket> _log;
    private readonly CancellationTokenSource _cts = new();
    private Task? _loop;
    private ClientWebSocket? _socket;
    private bool _connected;

    public ArrowWebSocket(IOptionsMonitor<ArrowOptions> opts, ILogger<ArrowWebSocket> log)
    {
        _opts = opts;
        _log  = log;
    }

    public bool IsConnected => _connected;

    public event EventHandler<ArrowWsEvent>? EventReceived;
    public event EventHandler<bool>?         ConnectionChanged;

    public Task StartAsync(CancellationToken ct = default)
    {
        if (_loop is not null) return Task.CompletedTask;
        _loop = Task.Run(() => RunAsync(_cts.Token), CancellationToken.None);
        return Task.CompletedTask;
    }

    public async Task StopAsync()
    {
        try { _cts.Cancel(); } catch { }
        try
        {
            if (_socket?.State == WebSocketState.Open)
                await _socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "shutdown", CancellationToken.None);
        }
        catch { }
        try { if (_loop is not null) await _loop; } catch { }
        SetConnected(false);
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync();
        _socket?.Dispose();
        _cts.Dispose();
    }

    // ── Background loop ─────────────────────────────────────────────────────

    private async Task RunAsync(CancellationToken ct)
    {
        var backoff = TimeSpan.FromSeconds(2);
        var max     = TimeSpan.FromSeconds(30);

        while (!ct.IsCancellationRequested)
        {
            try
            {
                using var ws = new ClientWebSocket();
                _socket = ws;
                var uri = _opts.CurrentValue.WebSocketUri;
                _log.LogInformation("WS connecting to {Uri}", uri);
                await ws.ConnectAsync(uri, ct);
                SetConnected(true);
                backoff = TimeSpan.FromSeconds(2);  // reset on success

                await ReadLoop(ws, ct);
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex)
            {
                _log.LogWarning(ex, "WS connection error, reconnecting in {Backoff}", backoff);
            }
            finally
            {
                SetConnected(false);
            }

            try { await Task.Delay(backoff, ct); } catch { }
            backoff = TimeSpan.FromMilliseconds(Math.Min(max.TotalMilliseconds, backoff.TotalMilliseconds * 1.7));
        }
    }

    private async Task ReadLoop(ClientWebSocket ws, CancellationToken ct)
    {
        var buffer = new byte[64 * 1024];
        var ms     = new MemoryStream();

        while (!ct.IsCancellationRequested && ws.State == WebSocketState.Open)
        {
            ms.SetLength(0);
            WebSocketReceiveResult result;
            do
            {
                result = await ws.ReceiveAsync(buffer, ct);
                if (result.MessageType == WebSocketMessageType.Close)
                    return;
                ms.Write(buffer, 0, result.Count);
            }
            while (!result.EndOfMessage);

            if (result.MessageType != WebSocketMessageType.Text) continue;
            var json = Encoding.UTF8.GetString(ms.GetBuffer(), 0, (int)ms.Length);
            TryDispatch(json);
        }
    }

    private void TryDispatch(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root    = doc.RootElement;
            var channel = root.TryGetProperty("channel", out var c) ? c.GetString() ?? "" : "";
            var evt     = root.TryGetProperty("event",   out var e) ? e.GetString() ?? "" : "";
            var data    = root.TryGetProperty("data",    out var d) ? d.Clone() : default;
            int? mid    = root.TryGetProperty("mission_id", out var m) && m.TryGetInt32(out var mv) ? mv : null;
            EventReceived?.Invoke(this, new ArrowWsEvent(channel, evt, data, mid));
        }
        catch (Exception ex)
        {
            _log.LogDebug(ex, "WS JSON dispatch failure");
        }
    }

    private void SetConnected(bool now)
    {
        if (_connected == now) return;
        _connected = now;
        ConnectionChanged?.Invoke(this, now);
    }
}
