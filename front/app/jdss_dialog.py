"""Arrow Front — JDSS Gateway dialog (configure + monitor the coalition bridge).

Mirrors the web admin JDSS page (web/templates/admin.html) using the same backend
endpoints exposed by ``front.client.arrow_client``:

* ``GET  /jdss/status``  — live status (any operator)
* ``GET  /jdss/config``  — config (ADMIN / BATTLE_CAPTAIN)
* ``PUT  /jdss/config``  — update config (ADMIN)
* ``POST /jdss/restart`` — restart the bridge (ADMIN)

The dialog polls ``/jdss/status`` on a timer while open so the connection state,
rx/tx counters and coalition-peer list stay live. Config editing + Save + Apply &
Restart are enabled only for ADMIN (matching the endpoint auth).
"""

from __future__ import annotations

import httpx
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Reuse the settings-dialog visual helpers for a consistent look.
from front.app.settings_dialog import _lbl, _section

_REFRESH_MS = 3000


class JdssGatewayDialog(QDialog):
    """Configure and monitor the JDSSArrow coalition bridge."""

    def __init__(self, parent=None, *, client, role: str = "OPERATOR"):
        super().__init__(parent)
        self._client = client
        self._role = role
        self._can_write = role == "ADMIN"

        self.setWindowTitle("Arrow Front — JDSS Gateway")
        self.setMinimumSize(560, 620)
        self.setMaximumSize(720, 820)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.MSWindowsFixedSizeDialogHint
        )
        self._build()
        self._reload_config()
        self._refresh_status()

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start()

    # ── Build UI ─────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setFixedHeight(46)
        hdr.setStyleSheet("background:#161b22;border-bottom:1px solid #30363d;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18, 0, 18, 0)
        title = QLabel("🛰  JDSS GATEWAY")
        title.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        title.setStyleSheet("color:#3fb950;letter-spacing:2px;")
        hl.addWidget(title)
        hl.addStretch()
        self._dot = QLabel("●")
        self._dot.setStyleSheet("color:#6e7681;font-size:14px;")
        hl.addWidget(self._dot)
        self._conn_lbl = QLabel("—")
        self._conn_lbl.setStyleSheet(
            "color:#8b949e;font-size:10px;font-family:'Courier New',monospace;"
        )
        hl.addWidget(self._conn_lbl)
        root.addWidget(hdr)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(14)
        root.addWidget(body, 1)

        # ── Live status ──────────────────────────────────────────────
        lay.addWidget(_section("Live status"))
        stat_form = QFormLayout()
        stat_form.setSpacing(8)
        stat_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._st_url = _mono()
        self._st_rx = _mono()
        self._st_tx = _mono()
        self._st_last = _mono()
        stat_form.addRow(_lbl("Gateway URL"), self._st_url)
        stat_form.addRow(_lbl("Msgs from JDSS"), self._st_rx)
        stat_form.addRow(_lbl("Msgs to JDSS"), self._st_tx)
        stat_form.addRow(_lbl("Last event"), self._st_last)
        lay.addLayout(stat_form)

        self._st_error = QLabel("")
        self._st_error.setWordWrap(True)
        self._st_error.setStyleSheet("color:#d29922;font-size:10px;")
        self._st_error.setVisible(False)
        lay.addWidget(self._st_error)

        # ── Coalition peers ──────────────────────────────────────────
        lay.addWidget(_section("Coalition peers"))
        self._peers = QListWidget()
        self._peers.setFont(QFont("Courier New", 11))
        self._peers.setMaximumHeight(120)
        lay.addWidget(self._peers)

        # ── Config ───────────────────────────────────────────────────
        lay.addWidget(_section("Bridge configuration"))
        cfg_form = QFormLayout()
        cfg_form.setSpacing(10)
        cfg_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._base_url = QLineEdit()
        self._base_url.setPlaceholderText("http://192.168.0.202:8000")
        cfg_form.addRow(_lbl("Gateway URL"), self._base_url)
        lay.addLayout(cfg_form)

        self._enabled = QCheckBox("Bridge enabled on startup")
        lay.addWidget(self._enabled)

        pub_row = QHBoxLayout()
        self._pub_presence = QCheckBox("Publish presence")
        self._pub_contacts = QCheckBox("Publish contacts")
        self._pub_chat = QCheckBox("Publish chat")
        for cb in (self._pub_presence, self._pub_contacts, self._pub_chat):
            pub_row.addWidget(cb)
        pub_row.addStretch()
        lay.addLayout(pub_row)

        if not self._can_write:
            note = QLabel("Configuration is read-only — requires ADMIN role.")
            note.setStyleSheet("color:#484f58;font-size:9px;")
            lay.addWidget(note)
            for wgt in (
                self._base_url,
                self._enabled,
                self._pub_presence,
                self._pub_contacts,
                self._pub_chat,
            ):
                wgt.setEnabled(False)

        lay.addStretch()

        # Footer
        ftr = QFrame()
        ftr.setFixedHeight(52)
        ftr.setStyleSheet("background:#161b22;border-top:1px solid #30363d;")
        fl = QHBoxLayout(ftr)
        fl.setContentsMargins(18, 8, 18, 8)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color:#6e7681;font-size:10px;")
        fl.addWidget(self._status_lbl, 1)

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(90)
        close_btn.clicked.connect(self.reject)
        fl.addWidget(close_btn)

        self._restart_btn = QPushButton("Apply & Restart")
        self._restart_btn.setFixedWidth(130)
        self._restart_btn.clicked.connect(self._on_restart)
        fl.addWidget(self._restart_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("primaryButton")
        self._save_btn.setFixedWidth(90)
        self._save_btn.clicked.connect(self._on_save)
        fl.addWidget(self._save_btn)

        if not self._can_write:
            self._save_btn.setEnabled(False)
            self._restart_btn.setEnabled(False)

        root.addWidget(ftr)

    # ── Data ─────────────────────────────────────────────────────────────
    def _reload_config(self):
        try:
            cfg = self._client.jdss_config()
        except Exception as exc:  # non-ADMIN/BC → 403, or gateway unreachable
            self._set_status(f"Could not load config: {_short(exc)}", warn=True)
            return
        self._base_url.setText(str(cfg.get("base_url", "")))
        self._enabled.setChecked(bool(cfg.get("enabled", True)))
        self._pub_presence.setChecked(bool(cfg.get("publish_presence", True)))
        self._pub_contacts.setChecked(bool(cfg.get("publish_contacts", True)))
        self._pub_chat.setChecked(bool(cfg.get("publish_chat", True)))

    def _refresh_status(self):
        try:
            s = self._client.jdss_status()
        except Exception as exc:
            self._dot.setStyleSheet("color:#f85149;font-size:14px;")
            self._conn_lbl.setText("unreachable")
            self._set_status(f"Status error: {_short(exc)}", warn=True)
            return

        connected = bool(s.get("ws_connected"))
        running = bool(s.get("running"))
        self._dot.setStyleSheet(
            f"color:{'#3fb950' if connected else '#d29922' if running else '#6e7681'};"
            "font-size:14px;"
        )
        self._conn_lbl.setText(
            "CONNECTED" if connected else ("CONNECTING" if running else "STOPPED")
        )
        self._st_url.setText(str(s.get("base_url") or "—"))
        self._st_rx.setText(str(s.get("rx_messages", 0)))
        tx = (
            int(s.get("tx_presence", 0))
            + int(s.get("tx_contacts", 0))
            + int(s.get("tx_chat", 0))
        )
        self._st_tx.setText(
            f"{tx}  (presence {s.get('tx_presence', 0)} · "
            f"contacts {s.get('tx_contacts', 0)} · chat {s.get('tx_chat', 0)})"
        )
        ago = s.get("last_event_ago_s")
        self._st_last.setText(f"{ago}s ago" if ago is not None else "—")

        err = s.get("last_error") or ""
        self._st_error.setText(f"⚠ {err}" if err else "")
        self._st_error.setVisible(bool(err))

        peers = s.get("peers") or []
        self._peers.clear()
        for p in peers:
            pid = p.get("originator_id") or p.get("id") or "—"
            cs = p.get("callsign") or ""
            self._peers.addItem(f"{pid}   {cs}".rstrip())
        if not peers:
            self._peers.addItem("— no peers reported —")

    def _patch(self) -> dict:
        return {
            "base_url": self._base_url.text().strip().rstrip("/"),
            "enabled": self._enabled.isChecked(),
            "publish_presence": self._pub_presence.isChecked(),
            "publish_contacts": self._pub_contacts.isChecked(),
            "publish_chat": self._pub_chat.isChecked(),
        }

    def _on_save(self):
        try:
            self._client.jdss_update_config(self._patch())
        except Exception as exc:
            self._set_status(f"Save failed: {_short(exc)}", warn=True)
            return
        self._set_status("✓ Saved — click Apply & Restart to activate")

    def _on_restart(self):
        # Persist the current form first so restart picks it up.
        try:
            self._client.jdss_update_config(self._patch())
            s = self._client.jdss_restart()
        except Exception as exc:
            self._set_status(f"Restart failed: {_short(exc)}", warn=True)
            return
        running = bool(s.get("running"))
        self._set_status(
            f"✓ Bridge {'started → ' + str(s.get('base_url')) if running else 'stopped'}"
        )
        self._refresh_status()

    # ── Helpers ──────────────────────────────────────────────────────────
    def _set_status(self, text: str, *, warn: bool = False):
        self._status_lbl.setText(text)
        self._status_lbl.setStyleSheet(
            f"color:{'#f85149' if warn else '#3fb950'};font-size:10px;"
        )

    def closeEvent(self, event):  # noqa: N802 (Qt override)
        self._timer.stop()
        super().closeEvent(event)

    def reject(self):
        self._timer.stop()
        super().reject()


def _mono() -> QLabel:
    lbl = QLabel("—")
    lbl.setStyleSheet(
        "color:#c9d1d9;font-size:11px;font-family:'Courier New',monospace;"
    )
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return lbl


def _short(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 403:
            return "403 — requires ADMIN role"
        return f"HTTP {code}"
    msg = str(exc)
    return msg[:60] if len(msg) > 60 else msg
