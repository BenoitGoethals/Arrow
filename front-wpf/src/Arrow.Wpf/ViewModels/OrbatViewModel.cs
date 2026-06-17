using System.Collections.ObjectModel;
using System.Windows;
using Arrow.Core.Models;
using Arrow.Core.Realtime;
using Arrow.Core.Services;
using Arrow.Wpf.Services;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace Arrow.Wpf.ViewModels;

/// <summary>Live operator hierarchy panel — companies → platoons → sections → teams.</summary>
public sealed partial class OrbatViewModel : ObservableObject
{
    private readonly IArrowApiClient _api;
    private readonly IArrowWebSocket _ws;
    private readonly IMapBridge      _bridge;

    public ObservableCollection<HierarchyNode> Roots { get; } = new();

    [ObservableProperty] private string _filter = "";
    [ObservableProperty] private bool   _onlineOnly;
    [ObservableProperty] private string _statusLine = "0 online · 0 total";

    public OrbatViewModel(IArrowApiClient api, IArrowWebSocket ws, IMapBridge bridge)
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
            var h = await _api.GetHierarchyAsync();
            Application.Current?.Dispatcher.Invoke(() => Populate(h));
        }
        catch { /* shown in status bar; don't crash */ }
    }

    [RelayCommand]
    private async Task FocusOperatorAsync(Operator? op)
    {
        if (op?.Latitude is not double lat || op?.Longitude is not double lon) return;
        await _bridge.CenterOnAsync(lat, lon, 16);
    }

    private void OnWsEvent(object? _, ArrowWsEvent e)
    {
        if (e.Channel is ArrowChannels.Presence or ArrowChannels.Tracking)
            _ = RefreshAsync();
    }

    private void Populate(Hierarchy h)
    {
        Roots.Clear();
        int onlineCount = 0, totalCount = 0;

        foreach (var co in h.Companies)
        {
            var coNode = new HierarchyNode($"{co.Name}", null);
            foreach (var pl in co.Platoons)
            {
                var plNode = new HierarchyNode(pl.Name, null);
                foreach (var sec in pl.Sections)
                {
                    var secNode = new HierarchyNode(sec.Name, null);
                    foreach (var team in sec.Teams)
                    {
                        var tmNode = new HierarchyNode(team.Name, null);
                        foreach (var op in team.Operators)
                        {
                            totalCount++;
                            if (op.Online) onlineCount++;
                            tmNode.Children.Add(new HierarchyNode($"{op.Callsign} ({op.Role})", op));
                        }
                        secNode.Children.Add(tmNode);
                    }
                    plNode.Children.Add(secNode);
                }
                coNode.Children.Add(plNode);
            }
            Roots.Add(coNode);
        }
        if (h.UnassignedOperators.Count > 0)
        {
            var u = new HierarchyNode("◇ Unassigned", null);
            foreach (var op in h.UnassignedOperators)
            {
                totalCount++;
                if (op.Online) onlineCount++;
                u.Children.Add(new HierarchyNode($"{op.Callsign} ({op.Role})", op));
            }
            Roots.Add(u);
        }
        StatusLine = $"{onlineCount} online · {totalCount} total";
    }
}

public sealed class HierarchyNode
{
    public string                       Label    { get; }
    public Operator?                    Operator { get; }
    public ObservableCollection<HierarchyNode> Children { get; } = new();

    public HierarchyNode(string label, Operator? op)
    {
        Label = label;
        Operator = op;
    }

    public bool IsOperator => Operator is not null;
    public bool IsOnline   => Operator?.Online ?? false;
}
