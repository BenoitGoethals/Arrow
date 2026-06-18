"""Compatibility shim for pymumble on Python 3.12+ and systems without libopus.

Import this module BEFORE importing pymumble_py3.  It applies three layers of fixes:

Layer 1 — libopus C library
  Loads libopus from the Homebrew / system path and patches ctypes.util.find_library
  so opuslib finds it.  If libopus is simply not installed, falls through to Layer 3.

Layer 2 — ssl
  Restores ssl.wrap_socket and ssl.PROTOCOL_TLS* that were removed in Python 3.12.

Layer 3 — opuslib stub (fallback when libopus is absent)
  Installs a pure-Python opuslib in sys.modules so pymumble can import and operate in
  presence-only mode (no audio encoding/decoding).  The stub produces silent frames,
  which is fine for the backend monitor bot and for displaying voice channels in the UI.
  Users who need real audio must install libopus: apt install libopus0 / brew install opus.

Layer 4 — vararg calling convention (ARM64 / Python 3.14)
  Wraps libopus_ctl so ctypes sets explicit argtypes before each variadic C call,
  preventing OPUS_BAD_ARG on Apple Silicon.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import ssl
import sys
import types

# ── Layer 1: locate libopus ───────────────────────────────────────────────────

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
        "/usr/lib/arm-linux-gnueabihf/libopus.so.0",
        "/usr/lib64/libopus.so.0",
        "/usr/lib/libopus.so.0",
        "/usr/local/lib/libopus.so",
        "/usr/local/lib/libopus.so.0",
    ]

# Inside a py2app .app bundle we ship libopus at Contents/Resources/lib so voice
# works on machines without Homebrew. Search it first so the bundled copy wins.
if getattr(sys, "frozen", False) and sys.platform == "darwin":
    _bundle_lib = os.path.normpath(
        os.path.join(os.path.dirname(sys.executable), os.pardir, "Resources", "lib")
    )
    _OPUS_SEARCH.insert(0, os.path.join(_bundle_lib, "libopus.0.dylib"))

_opus_real_path: str | None = None


def _patch_opus_path() -> bool:
    global _opus_real_path
    if getattr(ctypes.util, "_arrow_opus_patched", False):
        return True

    # 1a. Natural lookup (works when ldconfig knows about libopus)
    natural = ctypes.util.find_library("opus")
    if natural:
        try:
            ctypes.cdll.LoadLibrary(natural)
            _opus_real_path = natural
            ctypes.util._arrow_opus_patched = True
            return True
        except OSError:
            pass

    # 1b. Explicit search paths
    for p in _OPUS_SEARCH:
        if os.path.exists(p):
            try:
                ctypes.cdll.LoadLibrary(p)
            except OSError:
                continue
            _orig = ctypes.util.find_library

            def _find(name: str, _p=p, _orig=_orig):
                return _p if name == "opus" else _orig(name)

            ctypes.util.find_library = _find
            _opus_real_path = p
            ctypes.util._arrow_opus_patched = True
            return True

    return False   # libopus not available → use stub


# ── Layer 2: ssl ─────────────────────────────────────────────────────────────

def _patch_ssl() -> None:
    if getattr(ssl, "_arrow_ssl_patched", False):
        return
    for attr, alias in [
        ("PROTOCOL_TLS",    "PROTOCOL_TLS_CLIENT"),
        ("PROTOCOL_TLSv1",  "PROTOCOL_TLS_CLIENT"),
        ("PROTOCOL_SSLv23", "PROTOCOL_TLS_CLIENT"),
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


# ── Layer 3: pure-Python opuslib stub ────────────────────────────────────────

def _install_opuslib_stub() -> None:
    """Register a no-op opuslib in sys.modules so pymumble can import."""
    if "opuslib" in sys.modules:
        return  # real one already loaded

    # --- exceptions sub-module ---
    exc_mod = types.ModuleType("opuslib.exceptions")

    class OpusError(Exception):
        pass

    exc_mod.OpusError = OpusError  # type: ignore[attr-defined]

    # --- api sub-module (bare minimum) ---
    api_mod     = types.ModuleType("opuslib.api")
    api_enc_mod = types.ModuleType("opuslib.api.encoder")
    api_dec_mod = types.ModuleType("opuslib.api.decoder")
    api_ctl_mod = types.ModuleType("opuslib.api.ctl")

    # Stub CTL no-ops so soundoutput._set_bandwidth doesn't crash
    def _noop_ctl(*_a, **_kw):
        return 0

    api_ctl_mod.set_bitrate   = _noop_ctl  # type: ignore[attr-defined]
    api_ctl_mod.get_bitrate   = _noop_ctl  # type: ignore[attr-defined]
    api_ctl_mod.set_complexity = _noop_ctl # type: ignore[attr-defined]

    # --- stub Encoder ---
    class _StubEncoder:
        def __init__(self, fs: int, channels: int, application: int):
            self.encoder_state = object()   # non-None sentinel
            self._bitrate     = 64_000
            self._complexity  = 5

        @property
        def bitrate(self) -> int:
            return self._bitrate

        @bitrate.setter
        def bitrate(self, v: float | int):
            self._bitrate = max(500, int(v))

        @property
        def complexity(self) -> int:
            return self._complexity

        @complexity.setter
        def complexity(self, v: int):
            self._complexity = int(v)

        def encode(self, pcm_data: bytes, frame_size: int,
                   encode_fec: bool = False) -> bytes:
            return b"\xf8\xff\xfe"  # minimal valid silent Opus packet

        def encode_float(self, pcm_data: bytes, frame_size: int,
                         encode_fec: bool = False) -> bytes:
            return b"\xf8\xff\xfe"

    # --- stub Decoder ---
    class _StubDecoder:
        def __init__(self, fs: int, channels: int):
            self.decoder_state = object()
            self._gain = 0

        @property
        def gain(self) -> int:
            return self._gain

        @gain.setter
        def gain(self, v: int):
            self._gain = int(v)

        def decode(self, data: bytes, frame_size: int,
                   decode_fec: bool = False) -> bytes:
            return b"\x00" * frame_size * 2  # silence (int16)

        def decode_float(self, data: bytes, frame_size: int,
                         decode_fec: bool = False) -> bytes:
            return b"\x00" * frame_size * 4  # silence (float32)

    # --- main module ---
    opus_mod = types.ModuleType("opuslib")
    opus_mod.Encoder  = _StubEncoder              # type: ignore[attr-defined]
    opus_mod.Decoder  = _StubDecoder              # type: ignore[attr-defined]
    opus_mod.APPLICATION_VOIP                = 2048   # type: ignore[attr-defined]
    opus_mod.APPLICATION_AUDIO               = 2049   # type: ignore[attr-defined]
    opus_mod.APPLICATION_RESTRICTED_LOWDELAY = 2051   # type: ignore[attr-defined]
    opus_mod.OK         = 0                           # type: ignore[attr-defined]
    opus_mod.exceptions = exc_mod                     # type: ignore[attr-defined]
    opus_mod.api        = api_mod                     # type: ignore[attr-defined]

    for name, mod in [
        ("opuslib",              opus_mod),
        ("opuslib.exceptions",   exc_mod),
        ("opuslib.api",          api_mod),
        ("opuslib.api.encoder",  api_enc_mod),
        ("opuslib.api.decoder",  api_dec_mod),
        ("opuslib.api.ctl",      api_ctl_mod),
    ]:
        sys.modules[name] = mod


# ── Layer 4: ARM64 vararg calling convention fix ──────────────────────────────

def _patch_opuslib_varargs() -> None:
    if getattr(ctypes, "_arrow_opuslib_patched", False):
        return
    try:
        import opuslib.api.encoder as _enc
        import opuslib.api.decoder as _dec
        import opuslib.api as _api

        if not hasattr(_api, "libopus"):
            return  # stub — nothing to patch

        _raw_enc = _api.libopus.opus_encoder_ctl
        _raw_dec = _api.libopus.opus_decoder_ctl

        _byref_type = type(ctypes.byref(ctypes.c_int()))

        class _CTLProxy:
            def __init__(self, fn):
                self._fn = fn
                self._fn.restype = ctypes.c_int

            def __call__(self, obj, request_code, value=None):
                fn = self._fn
                if value is None:
                    fn.argtypes = None
                    return fn(obj, request_code)
                if isinstance(value, _byref_type):
                    fn.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
                    return fn(obj, request_code, value)
                if isinstance(value, ctypes._SimpleCData):
                    fn.argtypes = [ctypes.c_void_p, ctypes.c_int, type(value)]
                    return fn(obj, request_code, value)
                fn.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
                return fn(obj, request_code, ctypes.c_int(int(value)))

        _enc.libopus_ctl = _CTLProxy(_raw_enc)
        _dec.libopus_ctl = _CTLProxy(_raw_dec)
        ctypes._arrow_opuslib_patched = True
    except Exception:
        pass


# ── Apply all patches in order ────────────────────────────────────────────────

_opus_available = _patch_opus_path()
_patch_ssl()

if not _opus_available:
    _install_opuslib_stub()

# Vararg fix only makes sense when the real library is loaded
if _opus_available:
    _patch_opuslib_varargs()


# ── Public hint for error messages ───────────────────────────────────────────

OPUS_INSTALL_HINT: str = ""
if not _opus_available:
    if sys.platform == "darwin":
        OPUS_INSTALL_HINT = "brew install opus"
    else:
        OPUS_INSTALL_HINT = "apt install libopus0"

OPUS_STUB_ACTIVE: bool = not _opus_available
