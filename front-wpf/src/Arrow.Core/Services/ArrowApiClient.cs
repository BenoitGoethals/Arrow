using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using Arrow.Core.Configuration;
using Arrow.Core.Models;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Arrow.Core.Services;

/// <summary>HttpClient-based implementation of IArrowApiClient.</summary>
public sealed class ArrowApiClient : IArrowApiClient, IDisposable
{
    private readonly HttpClient _http;
    private readonly ArrowOptions _opts;
    private readonly ILogger<ArrowApiClient> _log;

    public ArrowApiClient(IOptionsMonitor<ArrowOptions> opts, ILogger<ArrowApiClient> log)
    {
        _opts = opts.CurrentValue;
        _log  = log;
        _http = new HttpClient { Timeout = _opts.HttpTimeout };
        UpdateBaseAddress();
    }

    private void UpdateBaseAddress()
    {
        _http.BaseAddress = new Uri(_opts.ServerUrl.TrimEnd('/') + "/");
        if (!string.IsNullOrEmpty(_opts.Token))
            _http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", _opts.Token);
    }

    // ── Auth ──────────────────────────────────────────────────────────────

    public async Task<LoginResponse> LoginAsync(string callsign, string password, CancellationToken ct = default)
    {
        var form = new FormUrlEncodedContent(new Dictionary<string, string>
        {
            ["username"] = callsign,
            ["password"] = password,
        });
        var resp = await _http.PostAsync("auth/login", form, ct);
        resp.EnsureSuccessStatusCode();
        var result = await resp.Content.ReadFromJsonAsync<LoginResponse>(cancellationToken: ct)
                     ?? throw new InvalidOperationException("Empty login response");

        _opts.Token = result.AccessToken;
        UpdateBaseAddress();
        return result;
    }

    public Task<Operator> MeAsync(CancellationToken ct = default) =>
        GetAsync<Operator>("auth/me", ct);

    // ── Hierarchy ─────────────────────────────────────────────────────────

    public Task<Hierarchy>              GetHierarchyAsync(CancellationToken ct = default) =>
        GetAsync<Hierarchy>("hierarchy", ct);

    public Task<IReadOnlyList<Operator>> GetOperatorsAsync(CancellationToken ct = default) =>
        GetListAsync<Operator>("operators", ct);

    // ── Tactical objects ──────────────────────────────────────────────────

    public Task<IReadOnlyList<TacticalObject>> GetTacticalObjectsAsync(CancellationToken ct = default) =>
        GetListAsync<TacticalObject>("tactical-objects", ct);

    public async Task<TacticalObject> CreateTacticalObjectAsync(TacticalObjectDraft draft, CancellationToken ct = default)
    {
        var resp = await _http.PostAsJsonAsync("tactical-objects", draft, ct);
        resp.EnsureSuccessStatusCode();
        return (await resp.Content.ReadFromJsonAsync<TacticalObject>(cancellationToken: ct))!;
    }

    public async Task<TacticalObject> PatchTacticalObjectAsync(int id, TacticalObjectPatch patch, CancellationToken ct = default)
    {
        var req = new HttpRequestMessage(HttpMethod.Patch, $"tactical-objects/{id}")
        {
            Content = JsonContent.Create(patch),
        };
        var resp = await _http.SendAsync(req, ct);
        resp.EnsureSuccessStatusCode();
        return (await resp.Content.ReadFromJsonAsync<TacticalObject>(cancellationToken: ct))!;
    }

    public async Task DeleteTacticalObjectAsync(int id, CancellationToken ct = default)
    {
        var resp = await _http.DeleteAsync($"tactical-objects/{id}", ct);
        resp.EnsureSuccessStatusCode();
    }

    public Task<IReadOnlyList<CotTrack>> GetCotTracksAsync(CancellationToken ct = default) =>
        GetListAsync<CotTrack>("cot/tracks", ct);

    // ── Alerts ────────────────────────────────────────────────────────────

    public Task<IReadOnlyList<Alert>> GetAlertsAsync(CancellationToken ct = default) =>
        GetListAsync<Alert>("alerts", ct);

    public async Task<Alert> SendAlertAsync(string type, double? lat = null, double? lon = null, CancellationToken ct = default)
    {
        var body = new { type, latitude = lat, longitude = lon };
        var resp = await _http.PostAsJsonAsync("alerts", body, ct);
        resp.EnsureSuccessStatusCode();
        return (await resp.Content.ReadFromJsonAsync<Alert>(cancellationToken: ct))!;
    }

    public async Task AckAlertAsync(int id, CancellationToken ct = default)
    {
        var resp = await _http.PostAsync($"alerts/{id}/ack", null, ct);
        resp.EnsureSuccessStatusCode();
    }

    // ── Reports / Messages / Missions ─────────────────────────────────────

    public Task<IReadOnlyList<Report>>  GetReportsAsync(CancellationToken ct = default)  =>
        GetListAsync<Report>("reports", ct);

    public Task<IReadOnlyList<Message>> GetMessagesAsync(CancellationToken ct = default) =>
        GetListAsync<Message>("messages", ct);

    public async Task<Message> SendMessageAsync(MessageDraft draft, CancellationToken ct = default)
    {
        var resp = await _http.PostAsJsonAsync("messages", draft, ct);
        resp.EnsureSuccessStatusCode();
        return (await resp.Content.ReadFromJsonAsync<Message>(cancellationToken: ct))!;
    }

    public Task<IReadOnlyList<Mission>> GetMissionsAsync(CancellationToken ct = default) =>
        GetListAsync<Mission>("missions", ct);

    public Task<Mission> GetMissionAsync(int id, CancellationToken ct = default) =>
        GetAsync<Mission>($"missions/{id}", ct);

    // ── Helpers ───────────────────────────────────────────────────────────

    private async Task<T> GetAsync<T>(string path, CancellationToken ct)
    {
        var result = await _http.GetFromJsonAsync<T>(path, ct);
        return result ?? throw new InvalidOperationException($"Empty response from {path}");
    }

    private async Task<IReadOnlyList<T>> GetListAsync<T>(string path, CancellationToken ct)
    {
        var result = await _http.GetFromJsonAsync<List<T>>(path, ct);
        return result ?? [];
    }

    public void Dispose() => _http.Dispose();
}
