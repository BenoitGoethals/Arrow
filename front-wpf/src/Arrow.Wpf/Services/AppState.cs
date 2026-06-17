using Arrow.Core.Models;
using CommunityToolkit.Mvvm.ComponentModel;

namespace Arrow.Wpf.Services;

/// <summary>
/// Session-wide state that survives panel/page changes.  Centralising it here
/// avoids passing the current operator + mission through every ViewModel ctor.
/// </summary>
public sealed partial class AppState : ObservableObject
{
    [ObservableProperty] private Operator? _currentOperator;
    [ObservableProperty] private Mission?  _activeMission;
    [ObservableProperty] private bool      _isConnected;
    [ObservableProperty] private double?   _cursorLatitude;
    [ObservableProperty] private double?   _cursorLongitude;
    [ObservableProperty] private string?   _cursorMgrs;

    public string Role => CurrentOperator?.Role ?? "OPERATOR";
    public bool   IsAdminOrBc => Role is "ADMIN" or "BATTLE_CAPTAIN";
}
