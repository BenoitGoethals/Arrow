using Arrow.Core.Models;

namespace Arrow.Core.Services;

/// <summary>
/// Persists the operator's JWT + server URL across sessions.  The default Windows
/// implementation uses the Windows Credential Manager (DPAPI-encrypted at rest).
/// </summary>
public interface IAuthStore
{
    StoredCredentials? Load();
    void Save(StoredCredentials credentials);
    void Clear();
}
