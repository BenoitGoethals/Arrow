"""Compatibility patches for pymumble on Python 3.12+.

Must be imported before pymumble_py3. Fixes:
  1. libopus not found — ctypes.util.find_library no longer reads DYLD_LIBRARY_PATH
     on Python 3.14/macOS; on Linux the library may simply not be installed.
  2. ssl.wrap_socket removed in Python 3.12
  3. ssl.PROTOCOL_TLS / ssl.PROTOCOL_TLSv1 removed in Python 3.12

If libopus cannot be found at all (not installed), the patch silently does nothing
and pymumble will raise its own "Could not find Opus library" exception — which the
monitor catches and stores as an error message shown in the web panel, along with
installation instructions.
"""
import ctypes
import ctypes.util
import os
import ssl
import sys

# ── 1. libopus ────────────────────────────────────────────────────────────────

_EXPLICIT_PATHS: list[str] = []

if sys.platform == "darwin":
    _EXPLICIT_PATHS = [
        "/opt/homebrew/lib/libopus.dylib",
        "/usr/local/lib/libopus.dylib",
        "/opt/local/lib/libopus.dylib",
    ]
else:
    # Linux: explicit paths as fallback when ldconfig hasn't been updated
    _EXPLICIT_PATHS = [
        "/usr/lib/x86_64-linux-gnu/libopus.so.0",
        "/usr/lib/aarch64-linux-gnu/libopus.so.0",
        "/usr/lib/arm-linux-gnueabihf/libopus.so.0",
        "/usr/lib64/libopus.so.0",
        "/usr/lib/libopus.so.0",
        "/usr/local/lib/libopus.so",
        "/usr/local/lib/libopus.so.0",
    ]


def _patch_opus() -> bool:
    """Return True if opus was located and the ctypes patch was applied."""
    if getattr(ctypes.util, "_arrow_opus_patched", False):
        return True

    # Step 1: try the natural lookup (works on Linux when libopus0 is installed
    # and ldconfig is up to date, or on macOS with recent Python versions)
    natural = ctypes.util.find_library("opus")
    if natural:
        try:
            ctypes.cdll.LoadLibrary(natural)
            ctypes.util._arrow_opus_patched = True
            return True
        except OSError:
            pass

    # Step 2: search explicit paths
    opus_path: str | None = None
    for p in _EXPLICIT_PATHS:
        if os.path.exists(p):
            opus_path = p
            break

    if not opus_path:
        return False  # not installed — let opuslib produce its own error

    try:
        ctypes.cdll.LoadLibrary(opus_path)
    except OSError:
        return False

    _orig = ctypes.util.find_library

    def _find(name: str, _path: str = opus_path, _orig=_orig) -> str | None:
        return _path if name == "opus" else _orig(name)

    ctypes.util.find_library = _find
    ctypes.util._arrow_opus_patched = True
    return True


# ── 2. ssl.wrap_socket / PROTOCOL_TLS* removed in Python 3.12 ────────────────

def _patch_ssl() -> None:
    if getattr(ssl, "_arrow_ssl_patched", False):
        return

    for attr, alias in [
        ("PROTOCOL_TLS",     "PROTOCOL_TLS_CLIENT"),
        ("PROTOCOL_TLSv1",   "PROTOCOL_TLS_CLIENT"),
        ("PROTOCOL_SSLv23",  "PROTOCOL_TLS_CLIENT"),
    ]:
        if not hasattr(ssl, attr):
            setattr(ssl, attr, getattr(ssl, alias))

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


# ── 3. opuslib vararg calling convention on ARM64 / Python 3.12+ ─────────────
# opus_encoder_ctl / opus_decoder_ctl are variadic C functions.  On ARM64
# macOS (Apple Silicon) ctypes cannot infer argument types for varargs —
# the C ABI treats fixed and variadic arguments differently.  Without
# explicit argtypes the wrong register is used, causing OPUS_BAD_ARG even
# for perfectly valid values.  We wrap libopus_ctl with a small proxy that
# sets argtypes before every call so ctypes uses the right convention.

def _patch_opuslib_varargs() -> None:
    if getattr(ctypes, "_arrow_opuslib_patched", False):
        return
    try:
        import opuslib.api.encoder as _enc
        import opuslib.api.decoder as _dec
        import opuslib.api as _api

        _raw_enc = _api.libopus.opus_encoder_ctl
        _raw_dec = _api.libopus.opus_decoder_ctl

        _byref_type = type(ctypes.byref(ctypes.c_int()))  # CArgObject

        class _CTLProxy:
            """Calls an opus_*_ctl C function with explicit argtypes each time."""
            def __init__(self, fn):
                self._fn = fn
                self._fn.restype = ctypes.c_int

            def __call__(self, obj, request_code, value=None):
                fn = self._fn
                if value is None:
                    fn.argtypes = None
                    return fn(obj, request_code)
                if isinstance(value, _byref_type):
                    # getter: byref(c_int) pointer for output
                    fn.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
                    return fn(obj, request_code, value)
                if isinstance(value, ctypes._SimpleCData):
                    fn.argtypes = [ctypes.c_void_p, ctypes.c_int, type(value)]
                    return fn(obj, request_code, value)
                # Plain Python int / float — most common (setter) case
                fn.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
                return fn(obj, request_code, ctypes.c_int(int(value)))

        _enc.libopus_ctl = _CTLProxy(_raw_enc)
        _dec.libopus_ctl = _CTLProxy(_raw_dec)
        ctypes._arrow_opuslib_patched = True
    except Exception:
        pass


_patch_opuslib_varargs()


# ── Install hint (shown in web panel via monitor._ERR) ───────────────────────

OPUS_INSTALL_HINT: str = ""
if not getattr(ctypes.util, "_arrow_opus_patched", False):
    if sys.platform == "darwin":
        OPUS_INSTALL_HINT = "run: brew install opus"
    else:
        OPUS_INSTALL_HINT = "run: apt install libopus0   (or: yum install opus)"
