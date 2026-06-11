"""Arrow Front — entry point."""
import sys
import os

_existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
_flags = {"--no-sandbox"}
_flags.update(_existing.split())
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(sorted(_flags))

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
setup_logging()   # must be before any other front.* import

from front.app.theme import TACTICAL_DARK
from front.app.login_dialog import LoginDialog
from front.app.main_window import MainWindow
from front.map.setup_libs import ensure_libs


def _try_auto_connect() -> tuple[str, str, str] | None:
    """Return (server_url, token, callsign) from keyring if still valid, else None."""
    settings = QSettings("Arrow", "ArrowFront")
    url      = settings.value("server_url", "")
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
    app.setFont(QFont("Ubuntu", 12))

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

    window = MainWindow(server_url=server_url, token=token, callsign=callsign)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
