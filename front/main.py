"""Arrow Front — entry point."""
import sys
import os

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QFont

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
    app.setStyleSheet(TACTICAL_DARK)
    app.setFont(QFont("Ubuntu", 10))

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
