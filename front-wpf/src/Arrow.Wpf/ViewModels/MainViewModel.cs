using Arrow.Core.Realtime;
using Arrow.Core.Services;
using Arrow.Wpf.Services;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Extensions.Logging;

namespace Arrow.Wpf.ViewModels;

public sealed partial class MainViewModel : ObservableObject
{
    private readonly IArrowApiClient _api;
    private readonly IArrowWebSocket _ws;
    private readonly IMapBridge      _bridge;
    private readonly AppState        _state;
    private readonly ILogger<MainViewModel> _log;

    public AppState          State    => _state;
    public OrbatViewModel    Orbat    { get; }
    public AlertsViewModel   Alerts   { get; }
    public MessagesViewModel Messages { get; }
    public ReportsViewModel  Reports  { get; }
    public MissionsViewModel Missions { get; }

    [ObservableProperty] private string _title    = "Arrow Front";
    [ObservableProperty] private string _statusMsg = "Connecting…";
    [ObservableProperty] private string _activeTab = "ORBAT";

    public MainViewModel(
        IArrowApiClient api,
        IArrowWebSocket ws,
        IMapBridge      bridge,
        AppState        state,
        OrbatViewModel  orbat,
        AlertsViewModel alerts,
        MessagesViewModel messages,
        ReportsViewModel reports,
        MissionsViewModel missions,
        ILogger<MainViewModel> log)
    {
        _api    = api;
        _ws     = ws;
        _bridge = bridge;
        _state  = state;
        _log    = log;

        Orbat    = orbat;
        Alerts   = alerts;
        Messages = messages;
        Reports  = reports;
        Missions = missions;

        _ws.ConnectionChanged += (_, online) =>
            System.Windows.Application.Current?.Dispatcher.Invoke(() =>
            {
                _state.IsConnected = online;
                StatusMsg = online ? "Server: ONLINE" : "Server: OFFLINE — reconnecting…";
            });

        _bridge.CoordsChanged += (_, c) =>
            System.Windows.Application.Current?.Dispatcher.Invoke(() =>
            {
                _state.CursorLatitude  = c.Latitude;
                _state.CursorLongitude = c.Longitude;
                _state.CursorMgrs      = c.Mgrs;
            });
    }

    public async Task LoadAsync()
    {
        try
        {
            var me = await _api.MeAsync();
            _state.CurrentOperator = me;
            Title = $"Arrow Front — {me.Callsign} ({me.Role})";
        }
        catch (Exception ex) { _log.LogWarning(ex, "Failed loading current operator"); }

        await _ws.StartAsync();

        await Task.WhenAll(
            Orbat.RefreshCommand.ExecuteAsync(null),
            Alerts.RefreshCommand.ExecuteAsync(null),
            Messages.RefreshCommand.ExecuteAsync(null),
            Reports.RefreshCommand.ExecuteAsync(null),
            Missions.RefreshCommand.ExecuteAsync(null));
    }

    [RelayCommand]
    private async Task FitTracksAsync() => await _bridge.FitTracksAsync();

    [RelayCommand]
    private async Task SendEmergencyAlertAsync(string? type)
    {
        if (string.IsNullOrEmpty(type)) return;
        try
        {
            await _api.SendAlertAsync(type,
                _state.CurrentOperator?.Latitude,
                _state.CurrentOperator?.Longitude);
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Failed to send {Type} alert", type);
        }
    }

    [RelayCommand]
    private async Task ChangeBaseLayerAsync(string? name) =>
        await _bridge.SetBaseLayerAsync(name ?? "osm");
}
