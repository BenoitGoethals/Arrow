"""Arrow Front — entry point."""

import sys
import os

def _build_webengine_flags() -> str:
    """Platform-tuned Chromium flags for a low-latency, always-live map.

    Must be set before QtWebEngine is imported/initialised (below). Detects the
    OS and picks the fastest safe GPU/latency options for each; anything already
    in the env is preserved.
    """
    flags = set(os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").split())

    # Unbundled (uv-launched) process cannot use the sandbox helper.
    flags.add("--no-sandbox")

    # Real-time COP: never throttle or pause the renderer when the window loses
    # focus / is occluded / is backgrounded, so live tracks and the map keep
    # updating with no lag. Also disable the native-window occlusion probe that
    # can freeze rendering on macOS/Windows.
    flags.update(
        {
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "--disable-features=CalculateNativeWinOcclusion",
            "--enable-smooth-scrolling",
        }
    )

    if sys.platform == "darwin":
        # Apple Silicon/Metal: the GPU raster path is fast and stable over
        # http:// (see MapView) — leave it ON; forcing software raster is laggy.
        pass
    elif sys.platform.startswith("linux"):
        # Many Linux GPUs are on Chromium's blocklist; opt back into hardware
        # acceleration so tiles/markers stay latency-free.
        flags.update(
            {
                "--ignore-gpu-blocklist",
                "--enable-gpu-rasterization",
                "--enable-zero-copy",
            }
        )
    elif sys.platform.startswith("win"):
        # ANGLE/D3D11 is the fast default on Windows; make it explicit and keep
        # GPU rasterisation on.
        flags.update({"--use-angle=d3d11", "--enable-gpu-rasterization"})

    return " ".join(sorted(f for f in flags if f))


os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = _build_webengine_flags()

# macOS: Homebrew opus lives outside the default dyld search path.
# Must be set before any import that pulls in opuslib (pymumble dependency).
if sys.platform == "darwin":
    for _brew_lib in ("/opt/homebrew/lib", "/usr/local/lib"):
        if os.path.isdir(_brew_lib):
            os.environ["DYLD_LIBRARY_PATH"] = (
                _brew_lib + os.pathsep + os.environ.get("DYLD_LIBRARY_PATH", "")
            )
            break

from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QFont, QIcon

from front.utils.log_setup import setup_logging

setup_logging()  # must be before any other front.* import

from front.app.theme import TACTICAL_DARK
from front.app.login_dialog import LoginDialog
from front.app.main_window import MainWindow
from front.map.setup_libs import ensure_libs


def _platform_ui_font() -> QFont:
    """Native UI font per OS — avoids the missing-"Ubuntu" fallback + font-alias
    cost on macOS/Windows and keeps text rendering fast and crisp everywhere."""
    if sys.platform == "darwin":
        family = ".AppleSystemUIFont"  # San Francisco; Qt resolves the alias
    elif sys.platform.startswith("win"):
        family = "Segoe UI"
    else:
        family = "Ubuntu"  # Linux target ships Ubuntu; falls back to sans-serif
    font = QFont(family, 12)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def _try_auto_connect() -> tuple[str, str, str] | None:
    """Return (server_url, token, callsign) from keyring if still valid, else None."""
    settings = QSettings("Arrow", "ArrowFront")
    url = settings.value("server_url", "")
    callsign = settings.value("last_callsign", "")
    if not url or not callsign:
        return None
    from front.client import auth as keyring_auth
    from front.client.arrow_client import ArrowClient

    token = keyring_auth.load_token(url)
    if not token:
        return None
    try:
        client = ArrowClient(url, token)
        me = client.me()
        return url, token, me.get("callsign", callsign)
    except Exception:
        return None


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Arrow Front")
    app.setApplicationDisplayName("Arrow Front")
    app.setOrganizationName("Arrow")
    app.setOrganizationDomain("com.arrow")
    app.setStyleSheet(TACTICAL_DARK)
    app.setFont(_platform_ui_font())

    # Application icon
    icon_path = Path(__file__).parent / "resources" / "arrow_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Download Leaflet / milsymbol / mgrs if not already bundled
    ensure_libs()

    # Try to auto-connect from saved credentials
    saved = _try_auto_connect()
    if saved:
        server_url, token, callsign = saved
    else:
        login = LoginDialog()
        if login.exec() != LoginDialog.DialogCode.Accepted:
            sys.exit(0)
        server_url, token, callsign = login.result()

    # ── Mandatory mission selection ──────────────────────────────────────
    # Every session must be in a mission. Admins pick/create one; everyone else
    # is locked to their assigned mission (the backend enforces this too).
    from PyQt6.QtWidgets import QDialog, QMessageBox

    from front.app.mission_dialog import MissionDialog
    from front.client.arrow_client import ArrowClient

    _client = ArrowClient(server_url, token)
    try:
        me = _client.me()
    except Exception:
        me = {}
    role = str(me.get("role", "OPERATOR")).upper()
    clearance = int(me.get("clearance", 0) or 0)
    mission_id = me.get("mission_id")

    if role == "ADMIN":
        dlg = MissionDialog(client=_client, clearance=clearance)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.selected_id:
            sys.exit(0)
        active_mission_id = dlg.selected_id
    else:
        if not mission_id:
            QMessageBox.critical(
                None,
                "No mission assigned",
                "You are not assigned to a mission.\n\n"
                "Ask an administrator to assign you to one, then sign in again.",
            )
            sys.exit(0)
        active_mission_id = int(mission_id)

    window = MainWindow(
        server_url=server_url,
        token=token,
        callsign=callsign,
        mission_id=active_mission_id,
    )
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
