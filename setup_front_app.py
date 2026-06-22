"""py2app build script — packages Arrow Front as a macOS ``.app`` bundle.

Why this exists
---------------
macOS Core Location only presents the permission prompt and delivers fixes to a
real ``.app`` bundle that has a bundle identifier and an Info.plist
``NSLocationWhenInUseUsageDescription`` key (see
``front/utils/location_provider.py``). Launched via ``uv run arrow-front`` the
host is a bare Python interpreter with no bundle identity, so authorisation
stays ``NotDetermined`` and no own-position fix is ever delivered. Wrapping the
app in a proper bundle is what unlocks native GPS / Wi-Fi positioning.

Build
-----
Recommended for running on your own machine (fast, and reliable with
PyQt6-WebEngine because Qt is referenced in place rather than relocated):

    uv run --extra front-bundle python setup_front_app.py py2app -A
    open "dist/Arrow Front.app"

Alias mode (``-A``) is not redistributable — it points back at this checkout and
its virtualenv — but it produces a genuine bundle id + Info.plist, which is all
Core Location needs locally.

Full standalone bundle (self-contained, ~620 MB, no venv references):

    uv run --extra front-bundle python setup_front_app.py py2app
    open "dist/Arrow Front.app"

The full build bundles Qt6 + QtWebEngine, the bundled CPython, and the ctypes
libraries py2app's static analysis cannot see (libmgrs, libportaudio) — see
DATA_FILES / packages below. Verified to launch with no missing-module errors.

The map JS libraries must already be present in ``front/map/html/lib/`` (they are
committed; otherwise run the app once or call ``front.map.setup_libs.download_libs``)
so they are bundled rather than written into the read-only app at runtime.

libopus (Mumble voice codec) is bundled at Contents/Resources/lib/libopus.0.dylib
from Homebrew at build time, so voice works on Macs without Homebrew —
front/mumble/opus_fix.py searches that path first when frozen.

Redistribution caveat (only matters when shipping to *other* Macs):
  * The bundle is ad-hoc signed. Gatekeeper will block it on other machines
    until it is signed with a Developer ID and notarised.
"""

import os
import sysconfig
import tempfile
import zlib

from setuptools import setup

# --- Python 3.14 compatibility shim for py2app 0.28 -------------------------
# A full (non-alias) build calls `self.copy_file(zlib.__file__, ...)` to ship
# zlib next to python3xx.zip so the bootstrap can unzip the stdlib. On Python
# 3.14 zlib is a statically-linked builtin with no `__file__`, which crashes the
# build. zlib is importable in the bundled interpreter regardless, so point
# `__file__` at a throwaway file — py2app's copy becomes an inert no-op.
if not hasattr(zlib, "__file__"):
    _zlib_stub = os.path.join(tempfile.gettempdir(), "zlib_builtin_stub")
    if not os.path.exists(_zlib_stub):
        open(_zlib_stub, "w").close()
    zlib.__file__ = _zlib_stub

# py2app refuses to build when the distribution carries `install_requires`, but
# setuptools auto-populates it from this repo's pyproject.toml `[project]`
# dependencies. Clear it on the command before py2app inspects it.
try:
    from py2app.build_app import py2app as _py2app_cmd

    class py2app(_py2app_cmd):  # noqa: N801 (matches the command name)
        def finalize_options(self):
            self.distribution.install_requires = None
            super().finalize_options()

    CMDCLASS = {"py2app": py2app}
except ImportError:  # py2app only present with the `front-bundle` extra
    CMDCLASS = {}

APP = ["front/main.py"]

# Native libraries loaded at runtime via ctypes.CDLL are invisible to py2app's
# static analysis, so ship them explicitly.
#
# mgrs loads `libmgrs.<SOABI>.so` from one level above its package dir — in the
# bundle that is Contents/Resources/lib/python3.14/. (sounddevice's
# libportaudio.dylib is handled via the `_sounddevice_data` package below.)
DATA_FILES = []
import mgrs  # noqa: E402  (only importable in the build venv; harmless here)

_soabi = sysconfig.get_config_var("SOABI")
_libmgrs = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(mgrs.__file__))),
    f"libmgrs.{_soabi}.so",
)
if os.path.exists(_libmgrs):
    DATA_FILES.append(("lib/python3.14", [_libmgrs]))

# libopus (Mumble voice codec) is loaded by opuslib via ctypes — invisible to
# py2app. Ship the Homebrew dylib at Contents/Resources/lib so voice works on
# machines without Homebrew; front/mumble/opus_fix.py searches that path when
# frozen. It depends only on libSystem, so the single file is self-contained.
for _opus_src in (
    "/opt/homebrew/lib/libopus.0.dylib",
    "/usr/local/lib/libopus.0.dylib",
):
    if os.path.exists(_opus_src):
        DATA_FILES.append(("lib", [os.path.realpath(_opus_src)]))
        break

OPTIONS = {
    # PyQt apps must not use Carbon argv emulation.
    "argv_emulation": False,
    "iconfile": "front/resources/arrow_icon.icns",
    # Copy whole packages so their data/binaries come along:
    #  - front: map/html/ (map.html + lib/), resources/ (icon, sounds)
    #  - _sounddevice_data: bundled libportaudio.dylib (sounddevice loads it via
    #    CFFI from this package; imported at startup by VoiceAlertPlayer)
    # (No-op in alias mode, where packages are referenced from this checkout.)
    #  - keyring.backends: discovered via entry points (invisible to py2app), so
    #    include the whole subpackage or the macOS Keychain backend is missing
    #    and token persistence / auto-login silently fail.
    "packages": ["front", "_sounddevice_data", "keyring.backends"],
    # pyobjc frameworks for native location are imported lazily, so name them
    # explicitly for the dependency graph.
    "includes": [
        "CoreLocation",
        "Foundation",
        "objc",
    ],
    "plist": {
        "CFBundleName": "Arrow Front",
        "CFBundleDisplayName": "Arrow Front",
        "CFBundleIdentifier": "com.arrow.front",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        # The reason for bundling: lets Core Location prompt for and then deliver
        # GPS / Wi-Fi fixes. Both keys provided for older/newer macOS.
        "NSLocationWhenInUseUsageDescription": "Arrow shows your own position on the tactical map.",
        "NSLocationUsageDescription": "Arrow shows your own position on the tactical map.",
    },
}

setup(
    name="Arrow Front",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    cmdclass=CMDCLASS,
)
