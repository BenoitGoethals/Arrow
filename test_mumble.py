#!/usr/bin/env python
"""Mumble stack smoke-test — run with:  uv run python test_mumble.py"""

import sys
import os

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
WARN = "\033[33m⚠\033[0m"


def check(label: str, fn):
    try:
        result = fn()
        print(f"  {PASS}  {label}" + (f"  →  {result}" if result else ""))
        return True
    except Exception as exc:
        print(f"  {FAIL}  {label}  →  {exc}")
        return False


print("\n══════════════════════════════════════════")
print("  ARROW  —  Mumble stack smoke-test")
print("══════════════════════════════════════════\n")

# ── 1. Python / venv ──────────────────────────────────────────────────────────
print("① Python environment")
check("Python version", lambda: sys.version.split()[0])
check("Venv prefix", lambda: sys.prefix)
print()

# ── 2. System opus library ───────────────────────────────────────────────────
print("② System libopus")
opus_path = None
for _p in (
    "/opt/homebrew/lib/libopus.dylib",
    "/usr/local/lib/libopus.dylib",
    "/usr/lib/x86_64-linux-gnu/libopus.so.0",
    "/usr/lib/aarch64-linux-gnu/libopus.so.0",
):
    if os.path.exists(_p):
        opus_path = _p
        break

if opus_path:
    print(f"  {PASS}  libopus found  →  {opus_path}")
else:
    print(f"  {FAIL}  libopus NOT found")
    if sys.platform == "darwin":
        print("        → run:  brew install opus")
    else:
        print("        → run:  apt install libopus0")
print()

# ── 3. Set DYLD path (macOS) and test opuslib ────────────────────────────────
print("③ opuslib (Python Opus wrapper)")
if sys.platform == "darwin" and opus_path:
    lib_dir = os.path.dirname(opus_path)
    os.environ["DYLD_LIBRARY_PATH"] = (
        lib_dir + os.pathsep + os.environ.get("DYLD_LIBRARY_PATH", "")
    )
check("import opuslib", lambda: __import__("opuslib") and "OK")
print()

# ── 4. pymumble ──────────────────────────────────────────────────────────────
print("④ pymumble_py3")
check("import pymumble_py3", lambda: str(__import__("pymumble_py3").Mumble))
print()

# ── 5. sounddevice + audio devices ───────────────────────────────────────────
print("⑤ sounddevice + audio devices")
ok = check("import sounddevice", lambda: __import__("sounddevice") and "OK")
if ok:
    import sounddevice as sd

    devs = sd.query_devices()
    ins = [d for d in devs if d["max_input_channels"] > 0]
    outs = [d for d in devs if d["max_output_channels"] > 0]
    print(f"  {PASS}  Input  devices: {len(ins)}")
    for d in ins:
        print(f"       • {d['name']}")
    print(f"  {PASS}  Output devices: {len(outs)}")
    for d in outs:
        print(f"       • {d['name']}")
print()

# ── 6. numpy ─────────────────────────────────────────────────────────────────
print("⑥ numpy")
check("import numpy", lambda: __import__("numpy").__version__)
print()

# ── 7. Backend mumble monitor ────────────────────────────────────────────────
print("⑦ Backend mumble monitor (backend.mumble.monitor)")
check(
    "import monitor",
    lambda: str(__import__("backend.mumble.monitor", fromlist=["monitor"]).monitor),
)
check(
    "_AVAILABLE flag",
    lambda: str(
        __import__("backend.mumble.monitor", fromlist=["_AVAILABLE"])._AVAILABLE
    ),
)
print()

# ── 8. Front mumble client ────────────────────────────────────────────────────
print("⑧ Front desktop mumble client (front.mumble.client)")
check(
    "import MumbleClient",
    lambda: str(
        __import__("front.mumble.client", fromlist=["MumbleClient"]).MumbleClient
    ),
)
check(
    "MUMBLE_AVAILABLE flag",
    lambda: str(
        __import__(
            "front.mumble.client", fromlist=["MUMBLE_AVAILABLE"]
        ).MUMBLE_AVAILABLE
    ),
)
print()

# ── 9. Quick connectivity test (optional) ────────────────────────────────────
print("⑨ Optional — live Mumble server test")
host = os.environ.get("MUMBLE_HOST", "")
if not host:
    print(f"  {WARN}  Skipped (set MUMBLE_HOST=your.server to test connectivity)")
else:
    port = int(os.environ.get("MUMBLE_PORT", 64738))
    user = os.environ.get("MUMBLE_USER", "ArrowTest")
    import pymumble_py3 as pymumble
    import threading

    result = {"ok": False, "err": ""}
    ev = threading.Event()

    def _on_ready():
        result["ok"] = True
        ev.set()

    try:
        m = pymumble.Mumble(host, user, port=port, reconnect=False)
        m.set_application_string("Arrow smoke-test")
        m.callbacks.set_callback(
            pymumble.PYMUMBLE_CLBK_CONNECTED,
            lambda: (result.__setitem__("ok", True), ev.set()),
        )
        m.start()
        ev.wait(timeout=10)
        channels = len(m.channels)
        users = len(m.users)
        m.stop()
        if result["ok"]:
            print(
                f"  {PASS}  Connected to {host}:{port} — "
                f"{channels} channels, {users} users"
            )
        else:
            print(f"  {FAIL}  Connected but ready signal not received")
    except Exception as exc:
        print(f"  {FAIL}  {host}:{port}  →  {exc}")

print("\n══════════════════════════════════════════\n")
