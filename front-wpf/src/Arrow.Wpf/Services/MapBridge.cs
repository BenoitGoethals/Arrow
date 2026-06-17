using System.Text.Json;
using Arrow.Core.Models;
using Microsoft.Extensions.Logging;
using Microsoft.Web.WebView2.Wpf;

namespace Arrow.Wpf.Services;

/// <summary>
/// Implementation of <see cref="IMapBridge"/> that talks to the Leaflet page
/// hosted in a WebView2.  The page must emit messages via
/// <c>window.chrome.webview.postMessage(JSON.stringify({kind, ...}))</c>.
/// </summary>
public sealed class MapBridge : IMapBridge
{
    private readonly ILogger<MapBridge> _log;
    private WebView2? _webView;
    private static readonly JsonSerializerOptions JsonOpts = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };

    public MapBridge(ILogger<MapBridge> log) { _log = log; }

    public bool IsReady { get; private set; }

    public event EventHandler?               MapReady;
    public event EventHandler<MapCoordsArgs>? CoordsChanged;
    public event EventHandler<int>?           TrackClicked;
    public event EventHandler<MapClickArgs>?  MapClicked;
    public event EventHandler<RadialAction>?  RadialAction;
    public event EventHandler<SymbolPlaced>?  SymbolSelected;

    /// <summary>Called by MapControl once the WebView2 has loaded the Leaflet page.</summary>
    public void Attach(WebView2 webView)
    {
        _webView = webView;
        webView.WebMessageReceived += OnWebMessage;
    }

    private void OnWebMessage(object? _, Microsoft.Web.WebView2.Core.CoreWebView2WebMessageReceivedEventArgs args)
    {
        try
        {
            using var doc = JsonDocument.Parse(args.WebMessageAsJson);
            var root = doc.RootElement;
            var kind = root.TryGetProperty("kind", out var k) ? k.GetString() ?? "" : "";

            switch (kind)
            {
                case "map_ready":
                    IsReady = true;
                    MapReady?.Invoke(this, EventArgs.Empty);
                    break;
                case "coords":
                    CoordsChanged?.Invoke(this, new MapCoordsArgs(
                        root.GetProperty("lat").GetDouble(),
                        root.GetProperty("lon").GetDouble(),
                        root.GetProperty("mgrs").GetString() ?? ""));
                    break;
                case "track_clicked":
                    TrackClicked?.Invoke(this, root.GetProperty("id").GetInt32());
                    break;
                case "map_clicked":
                    MapClicked?.Invoke(this, new MapClickArgs(
                        root.GetProperty("lat").GetDouble(),
                        root.GetProperty("lon").GetDouble()));
                    break;
                case "radial_action":
                    RadialAction?.Invoke(this, new RadialAction(
                        root.GetProperty("action").GetString() ?? "",
                        root.GetProperty("lat").GetDouble(),
                        root.GetProperty("lon").GetDouble()));
                    break;
                case "symbol_selected":
                    SymbolSelected?.Invoke(this, new SymbolPlaced(
                        root.GetProperty("sidc").GetString() ?? "",
                        root.GetProperty("designation").GetString() ?? "",
                        root.GetProperty("lat").GetDouble(),
                        root.GetProperty("lon").GetDouble()));
                    break;
            }
        }
        catch (Exception ex)
        {
            _log.LogDebug(ex, "MapBridge dispatch failed for: {Msg}", args.WebMessageAsJson);
        }
    }

    // ── C# → JS commands ────────────────────────────────────────────────

    public Task UpdateTrackAsync(Operator op)         => RunJs($"window.updateTrack({Json(op)})");
    public Task RemoveTrackAsync(int operatorId)      => RunJs($"window.removeTrack({operatorId})");
    public Task AddTacticalObjectAsync(TacticalObject obj) => RunJs($"window.addTacticalObject({Json(obj)})");
    public Task RemoveTacticalObjectAsync(int id)     => RunJs($"window.removeTacticalObject({id})");
    public Task AddAlertMarkerAsync(Alert alert)      => RunJs($"window.addAlertMarker({Json(alert)})");
    public Task CenterOnAsync(double lat, double lon, int zoom = 14)
                                                      => RunJs($"window.centerOn({lat.ToString("G", System.Globalization.CultureInfo.InvariantCulture)}, {lon.ToString("G", System.Globalization.CultureInfo.InvariantCulture)}, {zoom})");
    public Task FitTracksAsync()                      => RunJs("window.fitTracks && window.fitTracks()");
    public Task SetBaseLayerAsync(string name)        => RunJs($"window.setBaseLayer && window.setBaseLayer({Json(name)})");

    private async Task RunJs(string js)
    {
        if (_webView is null || !IsReady) return;
        try
        {
            await _webView.Dispatcher.InvokeAsync(async () =>
                await _webView.CoreWebView2.ExecuteScriptAsync(js));
        }
        catch (Exception ex)
        {
            _log.LogDebug(ex, "MapBridge RunJs failed: {Js}", js);
        }
    }

    private static string Json(object o) => JsonSerializer.Serialize(o, JsonOpts);
}
