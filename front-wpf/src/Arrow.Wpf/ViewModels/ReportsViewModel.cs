using System.Collections.ObjectModel;
using System.Windows;
using Arrow.Core.Models;
using Arrow.Core.Realtime;
using Arrow.Core.Services;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace Arrow.Wpf.ViewModels;

public sealed partial class ReportsViewModel : ObservableObject
{
    private readonly IArrowApiClient _api;
    private readonly IArrowWebSocket _ws;

    public ObservableCollection<Report> Reports { get; } = new();

    public ReportsViewModel(IArrowApiClient api, IArrowWebSocket ws)
    {
        _api = api;
        _ws  = ws;
        _ws.EventReceived += OnWsEvent;
    }

    [RelayCommand]
    private async Task RefreshAsync()
    {
        try
        {
            var list = await _api.GetReportsAsync();
            Application.Current?.Dispatcher.Invoke(() =>
            {
                Reports.Clear();
                foreach (var r in list) Reports.Add(r);
            });
        }
        catch { }
    }

    private void OnWsEvent(object? _, ArrowWsEvent e)
    {
        if (e.Channel == ArrowChannels.Report) _ = RefreshAsync();
    }
}
