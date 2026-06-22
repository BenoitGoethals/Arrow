"""Login dialog — server URL + credentials → JWT, with skip and auto-connect."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFrame,
    QCheckBox,
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QFont

import httpx
from front.client.arrow_client import ArrowClient
from front.client import auth as keyring_auth

_SETTINGS_KEY_URL = "server_url"
_SETTINGS_KEY_CALLSIGN = "last_callsign"


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Arrow Front — Connect")
        self.setFixedSize(420, 400)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self._token: str = ""
        self._callsign: str = "GUEST"
        self._server_url: str = ""
        self._settings = QSettings("Arrow", "ArrowFront")
        self._build_ui()
        self._restore_fields()

    # ---- UI ---------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title bar
        title_bar = QFrame()
        title_bar.setFixedHeight(48)
        title_bar.setStyleSheet("background:#161b22;border-bottom:1px solid #30363d;")
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(16, 0, 16, 0)
        logo = QLabel("◆  ARROW FRONT")
        logo.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        logo.setStyleSheet("color:#3fb950;letter-spacing:2px;")
        version = QLabel("v1.0")
        version.setStyleSheet("color:#484f58;font-size:10px;")
        tb_layout.addWidget(logo)
        tb_layout.addStretch()
        tb_layout.addWidget(version)
        layout.addWidget(title_bar)

        # Form body
        body = QFrame()
        body.setStyleSheet("background:#0d1117;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(32, 24, 32, 16)
        body_layout.setSpacing(12)

        subtitle = QLabel("COMMON OPERATIONAL PICTURE")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(
            "color:#484f58;font-size:9px;font-weight:600;letter-spacing:3px;"
        )
        body_layout.addWidget(subtitle)
        body_layout.addSpacing(4)

        # Fields
        self._url_field = QLineEdit()
        self._callsign_field = QLineEdit()
        self._callsign_field.setPlaceholderText("callsign")
        self._password_field = QLineEdit()
        self._password_field.setPlaceholderText("password")
        self._password_field.setEchoMode(QLineEdit.EchoMode.Password)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow(_lbl("SERVER"), self._url_field)
        form.addRow(_lbl("CALLSIGN"), self._callsign_field)
        form.addRow(_lbl("PASSWORD"), self._password_field)
        body_layout.addLayout(form)

        # Remember checkbox
        self._remember = QCheckBox("Remember credentials")
        self._remember.setChecked(True)
        self._remember.setStyleSheet("color:#8b949e;font-size:10px;")
        body_layout.addWidget(self._remember)

        # Error label
        self._error = QLabel("")
        self._error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error.setStyleSheet("color:#f85149;font-size:10px;min-height:16px;")
        body_layout.addWidget(self._error)

        # CONNECT button
        self._connect_btn = QPushButton("CONNECT")
        self._connect_btn.setObjectName("primaryButton")
        self._connect_btn.setFixedHeight(36)
        self._connect_btn.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self._connect_btn.clicked.connect(self._do_login)
        body_layout.addWidget(self._connect_btn)

        # SKIP button
        skip_btn = QPushButton("Continue without login  →")
        skip_btn.setFlat(True)
        skip_btn.setStyleSheet(
            "QPushButton{color:#484f58;font-size:10px;border:none;padding:4px;}"
            "QPushButton:hover{color:#8b949e;}"
        )
        skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        skip_btn.clicked.connect(self._do_skip)
        body_layout.addWidget(skip_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._password_field.returnPressed.connect(self._do_login)
        layout.addWidget(body, 1)

        # Footer
        footer = QFrame()
        footer.setFixedHeight(32)
        footer.setStyleSheet("background:#161b22;border-top:1px solid #21262d;")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 0, 16, 0)
        fl.addWidget(
            QLabel(
                "Arrow Tactical Platform  ·  Secure Channel",
                styleSheet="color:#484f58;font-size:9px;",
            )
        )
        layout.addWidget(footer)

    # ---- Field persistence ------------------------------------------------

    def _restore_fields(self):
        saved_url = self._settings.value(_SETTINGS_KEY_URL, "http://localhost:6001")
        saved_callsign = self._settings.value(_SETTINGS_KEY_CALLSIGN, "")
        self._url_field.setText(saved_url)
        self._callsign_field.setText(saved_callsign)
        if saved_callsign:
            self._password_field.setFocus()
        else:
            self._callsign_field.setFocus()

    def _save_fields(self):
        self._settings.setValue(
            _SETTINGS_KEY_URL, self._normalize_url(self._url_field.text())
        )
        self._settings.setValue(
            _SETTINGS_KEY_CALLSIGN, self._callsign_field.text().strip()
        )

    # ---- Actions ----------------------------------------------------------

    @staticmethod
    def _normalize_url(raw: str) -> str:
        """Strip trailing slashes only — callers append their own paths."""
        return raw.strip().rstrip("/")

    def _do_login(self):
        url = self._normalize_url(self._url_field.text())
        callsign = self._callsign_field.text().strip()
        password = self._password_field.text()

        if not url or not callsign or not password:
            self._error.setText("All fields are required")
            return

        self._error.setText("")
        self._connect_btn.setEnabled(False)
        self._connect_btn.setText("CONNECTING…")

        try:
            client = ArrowClient(url)
            data = client.login(callsign, password)
            self._token = data["access_token"]
            self._callsign = callsign
            self._server_url = url
            self._save_fields()
            if self._remember.isChecked():
                keyring_auth.save_token(url, self._token)
            self.accept()
        except httpx.TimeoutException:
            self._error.setText("Server timed out — check URL and network")
        except Exception as exc:
            msg = str(exc)
            if "401" in msg or "403" in msg:
                self._error.setText("Invalid credentials")
            elif "connect" in msg.lower() or "Connection" in msg:
                self._error.setText("Cannot reach server")
            else:
                self._error.setText(f"Error: {msg[:60]}")
        finally:
            self._connect_btn.setEnabled(True)
            self._connect_btn.setText("CONNECT")

    def _do_skip(self):
        url = self._normalize_url(self._url_field.text()) or "http://localhost:6001"
        self._server_url = url
        self._token = ""
        self._callsign = "GUEST"
        self._save_fields()
        self.accept()

    def result(self) -> tuple[str, str, str]:
        """Returns (server_url, token, callsign)."""
        return self._server_url, self._token, self._callsign


def _lbl(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "color:#8b949e;font-size:9px;font-weight:600;letter-spacing:1.5px;"
    )
    return lbl
