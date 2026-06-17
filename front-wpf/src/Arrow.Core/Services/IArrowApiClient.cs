using Arrow.Core.Models;

namespace Arrow.Core.Services;

/// <summary>
/// REST surface to the Arrow backend.  Mirrors the relevant subset of
/// <c>front/client/arrow_client.py</c>.
/// </summary>
public interface IArrowApiClient
{
    // ── Auth ──────────────────────────────────────────────────────────────
    Task<LoginResponse> LoginAsync(string callsign, string password, CancellationToken ct = default);
    Task<Operator>      MeAsync(CancellationToken ct = default);

    // ── Hierarchy & operators ────────────────────────────────────────────
    Task<Hierarchy>              GetHierarchyAsync(CancellationToken ct = default);
    Task<IReadOnlyList<Operator>> GetOperatorsAsync(CancellationToken ct = default);

    // ── Tactical entities ────────────────────────────────────────────────
    Task<IReadOnlyList<TacticalObject>> GetTacticalObjectsAsync(CancellationToken ct = default);
    Task<TacticalObject>                CreateTacticalObjectAsync(TacticalObjectDraft draft, CancellationToken ct = default);
    Task<TacticalObject>                PatchTacticalObjectAsync(int id, TacticalObjectPatch patch, CancellationToken ct = default);
    Task                                 DeleteTacticalObjectAsync(int id, CancellationToken ct = default);
    Task<IReadOnlyList<CotTrack>>       GetCotTracksAsync(CancellationToken ct = default);

    // ── Alerts ──────────────────────────────────────────────────────────
    Task<IReadOnlyList<Alert>> GetAlertsAsync(CancellationToken ct = default);
    Task<Alert>                SendAlertAsync(string type, double? lat = null, double? lon = null,
                                              CancellationToken ct = default);
    Task                       AckAlertAsync(int id, CancellationToken ct = default);

    // ── Reports ─────────────────────────────────────────────────────────
    Task<IReadOnlyList<Report>> GetReportsAsync(CancellationToken ct = default);

    // ── Messages ────────────────────────────────────────────────────────
    Task<IReadOnlyList<Message>> GetMessagesAsync(CancellationToken ct = default);
    Task<Message>                SendMessageAsync(MessageDraft draft, CancellationToken ct = default);

    // ── Missions ────────────────────────────────────────────────────────
    Task<IReadOnlyList<Mission>> GetMissionsAsync(CancellationToken ct = default);
    Task<Mission>                GetMissionAsync(int id, CancellationToken ct = default);
}
