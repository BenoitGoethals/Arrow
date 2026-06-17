using System.Collections.ObjectModel;
using System.Windows;
using Arrow.Core.Models;
using Arrow.Core.Realtime;
using Arrow.Core.Services;
using Arrow.Wpf.Services;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace Arrow.Wpf.ViewModels;

public sealed partial class MissionsViewModel : ObservableObject
{
    private readonly IArrowApiClient _api;
    private readonly IArrowWebSocket _ws;
    private readonly AppState        _state;

    public ObservableCollection<Mission> Missions { get; } = new();

    [ObservableProperty] private Mission? _selectedMission;

    public MissionsViewModel(IArrowApiClient api, IArrowWebSocket ws, AppState state)
    {
        _api   = api;
        _ws    = ws;
        _state = state;

        _ws.EventReceived += OnWsEvent;
    }

    partial void OnSelectedMissionChanged(Mission? value)
    {
        _state.ActiveMission = value;
    }

    [RelayCommand]
    private async Task RefreshAsync()
    {
        try
        {
            var list = await _api.GetMissionsAsync();
            Application.Current?.Dispatcher.Invoke(() =>
            {
                Missions.Clear();
                foreach (var m in list) Missions.Add(m);
                SelectedMission = list.FirstOrDefault(m => m.Status == "ACTIVE");
            });
        }
        catch { }
    }

    private void OnWsEvent(object? _, ArrowWsEvent e)
    {
        if (e.Channel == ArrowChannels.Mission) _ = RefreshAsync();
    }
}
