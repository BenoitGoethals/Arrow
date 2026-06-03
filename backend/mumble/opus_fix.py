"""Compatibility patches for pymumble on Python 3.12+.

Must be imported before pymumble_py3. Fixes:
  1. libopus not found — ctypes.util.find_library no longer reads DYLD_LIBRARY_PATH
  2. ssl.wrap_socket removed in Python 3.12
  3. ssl.PROTOCOL_TLS / ssl.PROTOCOL_TLSv1 removed in Python 3.12
"""
import ctypes
import ctypes.util
import os
import ssl
import sys

# ── 1. libopus path ───────────────────────────────────────────────────────────

if sys.platform == "darwin":
    _OPUS_SEARCH = [
        "/opt/homebrew/lib/libopus.dylib",
        "/usr/local/lib/libopus.dylib",
        "/opt/local/lib/libopus.dylib",
    ]
else:
    _OPUS_SEARCH = [
        "/usr/lib/x86_64-linux-gnu/libopus.so.0",
        "/usr/lib/aarch64-linux-gnu/libopus.so.0",
        "/usr/lib/libopus.so.0",
        "/usr/local/lib/libopus.so",
    ]


def _patch_opus():
    if getattr(ctypes.util, "_arrow_opus_patched", False):
        return
    for p in _OPUS_SEARCH:
        if os.path.exists(p):
            try:
                ctypes.cdll.LoadLibrary(p)
            except OSError:
                continue
            _orig = ctypes.util.find_library

            def _find(name, _path=p, _orig=_orig):
                return _path if name == "opus" else _orig(name)

            ctypes.util.find_library = _find
            ctypes.util._arrow_opus_patched = True
            break


# ── 2. ssl.wrap_socket removed in Python 3.12 ────────────────────────────────

def _patch_ssl():
    if getattr(ssl, "_arrow_ssl_patched", False):
        return

    # Restore deprecated constants that pymumble references
    if not hasattr(ssl, "PROTOCOL_TLS"):
        ssl.PROTOCOL_TLS = ssl.PROTOCOL_TLS_CLIENT          # type: ignore[attr-defined]
    if not hasattr(ssl, "PROTOCOL_TLSv1"):
        ssl.PROTOCOL_TLSv1 = ssl.PROTOCOL_TLS_CLIENT        # type: ignore[attr-defined]
    if not hasattr(ssl, "PROTOCOL_SSLv23"):
        ssl.PROTOCOL_SSLv23 = ssl.PROTOCOL_TLS_CLIENT       # type: ignore[attr-defined]

    if not hasattr(ssl, "wrap_socket"):
        def wrap_socket(sock, keyfile=None, certfile=None,
                        server_side=False, ssl_version=None,
                        ca_certs=None, do_handshake_on_connect=True,
                        suppress_ragged_eofs=True, **_):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            if certfile:
                ctx.load_cert_chain(certfile, keyfile)
            if ca_certs:
                ctx.load_verify_locations(ca_certs)
            return ctx.wrap_socket(
                sock,
                server_side=server_side,
                do_handshake_on_connect=do_handshake_on_connect,
                suppress_ragged_eofs=suppress_ragged_eofs,
            )

        ssl.wrap_socket = wrap_socket  # type: ignore[attr-defined]

    ssl._arrow_ssl_patched = True  # type: ignore[attr-defined]


_patch_opus()
_patch_ssl()
