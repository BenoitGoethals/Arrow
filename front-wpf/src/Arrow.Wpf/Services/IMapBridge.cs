using Arrow.Core.Models;

namespace Arrow.Wpf.Services;

/// <summary>
/// Two-way Python↔JS bridge sits behind this contract in the WPF version.
/// The WebView2-hosted Leaflet page emits events through CoreWebView2.WebMessageReceived;
/// the C# side both observes those events and pushes commands the other way
/// via ExecuteScriptAsync.
/// </summary>
public interface IMapBridge
{
    bool IsReady { get; }

    // ── JS → C# events ───────────────────────────────────────────────────
    event EventHandler?               MapReady;
    event EventHandler<MapCoordsArgs>? CoordsChanged;
    event EventHandler<int>?           TrackClicked;
    event EventHandler<MapClickArgs>?  MapClicked;
    event EventHandler<RadialAction>?  RadialAction;
    event EventHandler<SymbolPlaced>?  SymbolSelected;

    // ── C# → JS commands ────────────────────────────────────────────────
    Task UpdateTrackAsync(Operator op);
    Task RemoveTrackAsync(int operatorId);
    Task AddTacticalObjectAsync(TacticalObject obj);
    Task RemoveTacticalObjectAsync(int id);
    Task AddAlertMarkerAsync(Alert alert);
    Task CenterOnAsync(double lat, double lon, int zoom = 14);
    Task FitTracksAsync();
    Task SetBaseLayerAsync(string name);
}

public sealed record MapCoordsArgs(double Latitude, double Longitude, string Mgrs);
public sealed record MapClickArgs(double Latitude, double Longitude);
public sealed record RadialAction(string Action, double Latitude, double Longitude);
public sealed record SymbolPlaced(string Sidc, string Designation, double Latitude, double Longitude);
