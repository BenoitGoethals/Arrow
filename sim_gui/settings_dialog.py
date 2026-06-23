"""Backend settings dialog — URL + ADMIN credentials.

The password is offered to the OS keyring (same `_SERVICE` namespace as the
existing `front/client/auth.py` to keep things tidy). If keyring is broken
the dialog silently falls back to in-memory storage for the session.
"""

from __future__ import annotations

import keyring
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)

from sim_utils import load_saved_backend, save_backend

_SERVICE = "ArrowSimGui"
_PWD_USER = "admin-password"


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Backend Settings")
        self.setMinimumWidth(420)

        self._url = QLineEdit()
        self._url.setPlaceholderText("http://localhost:6001")
        self._callsign = QLineEdit()
        self._callsign.setPlaceholderText("benoit")
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)

        form = QFormLayout()
        form.addRow("Backend URL", self._url)
        form.addRow("Admin callsign", self._callsign)
        form.addRow("Admin password", self._password)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._load()

    # ------------------------------------------------------------------
    def values(self) -> tuple[str, str, str]:
        return (
            self._url.text().strip() or "http://localhost:6001",
            self._callsign.text().strip() or "benoit",
            self._password.text(),
        )

    # ------------------------------------------------------------------
    def _load(self) -> None:
        url = load_saved_backend() or "http://localhost:6001"
        self._url.setText(url)
        try:
            cs = keyring.get_password(_SERVICE, "admin-callsign") or "benoit"
        except Exception:
            cs = "benoit"
        self._callsign.setText(cs)
        try:
            pwd = keyring.get_password(_SERVICE, _PWD_USER) or ""
        except Exception:
            pwd = ""
        self._password.setText(pwd)

    def _on_accept(self) -> None:
        url, cs, pwd = self.values()
        try:
            save_backend(url)
        except Exception:
            pass
        try:
            keyring.set_password(_SERVICE, "admin-callsign", cs)
            if pwd:
                keyring.set_password(_SERVICE, _PWD_USER, pwd)
        except Exception:
            pass
        self.accept()
