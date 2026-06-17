using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using Arrow.Core.Models;

namespace Arrow.Core.Services;

/// <summary>
/// Persists the JWT in the Windows Credential Manager (vault).  Falls back to a
/// DPAPI-encrypted file under %LOCALAPPDATA%\Arrow when the vault is unavailable.
/// </summary>
public sealed class WindowsCredentialAuthStore : IAuthStore
{
    private const string TargetName = "Arrow.Wpf.Credentials";
    private static readonly string FallbackPath =
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                     "Arrow", "credentials.bin");

    public StoredCredentials? Load()
    {
        try
        {
            if (CredentialNative.TryRead(TargetName, out var blob) && blob is not null)
                return Decode(blob);
        }
        catch { /* fall through to file backup */ }

        return LoadFallback();
    }

    public void Save(StoredCredentials credentials)
    {
        var json = JsonSerializer.SerializeToUtf8Bytes(credentials);
        try
        {
            CredentialNative.Write(TargetName, credentials.Callsign, json);
            return;
        }
        catch { /* fall through */ }

        SaveFallback(json);
    }

    public void Clear()
    {
        try { CredentialNative.Delete(TargetName); } catch { }
        try { if (File.Exists(FallbackPath)) File.Delete(FallbackPath); } catch { }
    }

    private static StoredCredentials? Decode(byte[] json)
    {
        try { return JsonSerializer.Deserialize<StoredCredentials>(json); }
        catch { return null; }
    }

    private static StoredCredentials? LoadFallback()
    {
        try
        {
            if (!File.Exists(FallbackPath)) return null;
            var encrypted = File.ReadAllBytes(FallbackPath);
            var plain = System.Security.Cryptography.ProtectedData.Unprotect(
                encrypted, null, System.Security.Cryptography.DataProtectionScope.CurrentUser);
            return Decode(plain);
        }
        catch { return null; }
    }

    private static void SaveFallback(byte[] json)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(FallbackPath)!);
            var encrypted = System.Security.Cryptography.ProtectedData.Protect(
                json, null, System.Security.Cryptography.DataProtectionScope.CurrentUser);
            File.WriteAllBytes(FallbackPath, encrypted);
        }
        catch { /* swallow — the user will just have to log in again */ }
    }

    // ── Windows Credential Manager P/Invoke ──────────────────────────────────

    private static class CredentialNative
    {
        private const int CRED_TYPE_GENERIC      = 1;
        private const int CRED_PERSIST_LOCAL     = 2;

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct CREDENTIAL
        {
            public uint   Flags;
            public uint   Type;
            public IntPtr TargetName;
            public IntPtr Comment;
            public long   LastWritten;
            public uint   CredentialBlobSize;
            public IntPtr CredentialBlob;
            public uint   Persist;
            public uint   AttributeCount;
            public IntPtr Attributes;
            public IntPtr TargetAlias;
            public IntPtr UserName;
        }

        [DllImport("advapi32", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool CredReadW(string targetName, uint type, uint flags, out IntPtr cred);

        [DllImport("advapi32", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool CredWriteW([In] ref CREDENTIAL credential, uint flags);

        [DllImport("advapi32", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool CredDeleteW(string target, uint type, uint flags);

        [DllImport("advapi32", SetLastError = true)]
        private static extern void CredFree(IntPtr cred);

        public static bool TryRead(string target, out byte[]? blob)
        {
            blob = null;
            if (!CredReadW(target, CRED_TYPE_GENERIC, 0, out var ptr))
                return false;
            try
            {
                var cred = Marshal.PtrToStructure<CREDENTIAL>(ptr);
                if (cred.CredentialBlobSize == 0) return true;
                blob = new byte[cred.CredentialBlobSize];
                Marshal.Copy(cred.CredentialBlob, blob, 0, (int)cred.CredentialBlobSize);
                return true;
            }
            finally { CredFree(ptr); }
        }

        public static void Write(string target, string username, byte[] blob)
        {
            var targetPtr = Marshal.StringToHGlobalUni(target);
            var userPtr   = Marshal.StringToHGlobalUni(username);
            var blobPtr   = Marshal.AllocHGlobal(blob.Length);
            try
            {
                Marshal.Copy(blob, 0, blobPtr, blob.Length);
                var cred = new CREDENTIAL
                {
                    Type              = CRED_TYPE_GENERIC,
                    TargetName        = targetPtr,
                    UserName          = userPtr,
                    CredentialBlob    = blobPtr,
                    CredentialBlobSize = (uint)blob.Length,
                    Persist           = CRED_PERSIST_LOCAL,
                };
                if (!CredWriteW(ref cred, 0))
                    throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            finally
            {
                Marshal.FreeHGlobal(targetPtr);
                Marshal.FreeHGlobal(userPtr);
                Marshal.FreeHGlobal(blobPtr);
            }
        }

        public static void Delete(string target)
        {
            if (!CredDeleteW(target, CRED_TYPE_GENERIC, 0))
                throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }
}
