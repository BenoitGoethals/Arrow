using System.Collections.ObjectModel;
using System.Windows;
using Arrow.Core.Models;
using Arrow.Core.Realtime;
using Arrow.Core.Services;
using Arrow.Wpf.Services;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace Arrow.Wpf.ViewModels;

public sealed partial class AlertsViewModel : ObservableObject
{
    private readonly IArrowApiClient _api;
    private readonly IArrowWebSocket _ws;
    private readonly IMapBridge      _bridge;

    public ObservableCollection<Alert> Alerts { get; } = new();

    public AlertsViewModel(IArrowApiClient api, IArrowWebSocket ws, IMapBridge bridge)
    {
        _api    = api;
        _ws     = ws;
        _bridge = bridge;
        _ws.EventReceived += OnWsEvent;
    }

    [RelayCommand]
    private async Task RefreshAsync()
    {
        try
        {
            var list = await _api.GetAlertsAsync();
            Application.Current?.Dispatcher.Invoke(() =>
            {
                Alerts.Clear();
                foreach (var a in list) Alerts.Add(a);
            });
        }
        catch { }
    }

    [RelayCommand]
    private async Task LocateAsync(Alert? alert)
    {
        if (alert?.Latitude is not double lat || alert?.Longitude is not double lon) return;
        await _bridge.CenterOnAsync(lat, lon, 16);
    }

    [RelayCommand]
    private async Task AckAsync(Alert? alert)
    {
        if (alert is null) return;
        try { await _api.AckAlertAsync(alert.Id); }
        catch { /* surface via dialog in real app */ }
    }

    private void OnWsEvent(object? _, ArrowWsEvent e)
    {
        if (e.Channel != ArrowChannels.Alert) return;
        if (e.Event == "triggered")
        {
            // Add the alert immediately so it shows even before REST refresh.
            var alert = e.DataAs<Alert>();
            if (alert is not null)
            {
                Application.Current?.Dispatcher.Invoke(() =>
                {
                    Alerts.Insert(0, alert);
                });
                if (alert.Latitude is double lat && alert.Longitude is double lon
                    && !(lat == 0 && lon == 0))
                {
                    _ = _bridge.CenterOnAsync(lat, lon, 16);
                    _ = _bridge.AddAlertMarkerAsync(alert);
                }
            }
        }
        else
        {
            _ = RefreshAsync();
        }
    }
}
