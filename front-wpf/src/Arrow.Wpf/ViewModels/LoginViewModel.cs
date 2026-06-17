using Arrow.Core.Configuration;
using Arrow.Core.Models;
using Arrow.Core.Services;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Extensions.Options;

namespace Arrow.Wpf.ViewModels;

public sealed partial class LoginViewModel : ObservableObject
{
    private readonly IArrowApiClient _api;
    private readonly IAuthStore      _store;
    private readonly ArrowOptions    _opts;

    [ObservableProperty] private string  _serverUrl = "http://localhost:6001";
    [ObservableProperty] private string  _callsign  = "";
    [ObservableProperty] private string  _password  = "";
    [ObservableProperty] private string? _errorMessage;
    [ObservableProperty] private bool    _isBusy;

    public bool LoginSucceeded { get; private set; }

    public LoginViewModel(IArrowApiClient api, IAuthStore store, IOptions<ArrowOptions> opts)
    {
        _api   = api;
        _store = store;
        _opts  = opts.Value;

        var stored = store.Load();
        if (stored is not null)
        {
            ServerUrl = stored.ServerUrl;
            Callsign  = stored.Callsign;
        }
    }

    [RelayCommand]
    private async Task LoginAsync()
    {
        ErrorMessage = null;
        if (string.IsNullOrWhiteSpace(Callsign) || string.IsNullOrEmpty(Password))
        {
            ErrorMessage = "Callsign and password are required.";
            return;
        }

        IsBusy = true;
        try
        {
            _opts.ServerUrl = ServerUrl;
            var resp = await _api.LoginAsync(Callsign, Password);
            _opts.Token = resp.AccessToken;
            var me = await _api.MeAsync();
            _store.Save(new StoredCredentials(ServerUrl, me.Callsign, resp.AccessToken));
            LoginSucceeded = true;
        }
        catch (HttpRequestException ex)
        {
            ErrorMessage = $"Connection failed: {ex.Message}";
        }
        catch (Exception ex)
        {
            ErrorMessage = $"Login failed: {ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }
}
