"""Mumble voice panel — channel tree, user list, PTT / mute / deafen controls."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QSlider, QFrame, QSizePolicy,
    QLineEdit, QSpinBox, QFormLayout, QDialog, QDialogButtonBox,
    QComboBox,
)
import socket
import threading
import time as _time

from PyQt6.QtCore import Qt, QSettings, pyqtSignal, pyqtSlot, QTimer, QMetaObject, Q_ARG
from PyQt6.QtGui import QFont, QColor

from front.mumble.client import MumbleClient, list_audio_devices

_S = QSettings("Arrow", "ArrowFront")

_MONO = QFont("Courier New", 12)


# ─────────────────────────────────────────────────────────────────────────────
# Quick-connect dialog
# ─────────────────────────────────────────────────────────────────────────────

class _ConnectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mumble — Connect")
        self.setMinimumWidth(340)
        lay = QVBoxLayout(self)

        form = QFormLayout()
        form.setSpacing(8)

        self._host = QLineEdit(_S.value("mumble/host", ""))
        self._host.setPlaceholderText("mumble.example.com")
        form.addRow(_lbl("Server"), self._host)

        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(int(_S.value("mumble/port", 64738)))
        form.addRow(_lbl("Port"), self._port)

        self._user = QLineEdit(_S.value("mumble/username", ""))
        self._user.setPlaceholderText("callsign")
        form.addRow(_lbl("Username"), self._user)

        self._pwd = QLineEdit(_S.value("mumble/password", ""))
        self._pwd.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_lbl("Password"), self._pwd)

        self._chan = QLineEdit(_S.value("mumble/channel", ""))
        self._chan.setPlaceholderText("Root  (optional)")
        form.addRow(_lbl("Channel"), self._chan)

        lay.addLayout(form)

        # Audio device pickers
        ins, outs = list_audio_devices()
        in_lbl  = _lbl("Mic")
        out_lbl = _lbl("Speaker")

        self._in_dev  = QComboBox()
        self._out_dev = QComboBox()
        self._in_dev.addItem("System default", None)
        self._out_dev.addItem("System default", None)
        for idx, name in ins:
            self._in_dev.addItem(name, idx)
        for idx, name in outs:
            self._out_dev.addItem(name, idx)

        saved_in  = _S.value("mumble/in_device",  None)
        saved_out = _S.value("mumble/out_device", None)
        self._restore_combo(self._in_dev,  saved_in)
        self._restore_combo(self._out_dev, saved_out)

        form2 = QFormLayout()
        form2.setSpacing(8)
        form2.addRow(in_lbl,  self._in_dev)
        form2.addRow(out_lbl, self._out_dev)
        lay.addLayout(form2)

        # ── Test button ──────────────────────────────────────────────────
        test_row = QHBoxLayout()
        self._test_btn = QPushButton("🔗 Test server")
        self._test_btn.setFixedHeight(26)
        self._test_btn.clicked.connect(self._do_test)
        self._test_lbl = QLabel("")
        self._test_lbl.setFont(_MONO)
        self._test_lbl.setStyleSheet("font-size:12px;color:#6e7681;")
        test_row.addWidget(self._test_btn)
        test_row.addWidget(self._test_lbl, 1)
        lay.addLayout(test_row)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _do_test(self):
        host = self._host.text().strip()
        port = self._port.value()
        if not host:
            self._test_lbl.setText("Enter a server address first")
            self._test_lbl.setStyleSheet("font-size:12px;color:#d29922;")
            return
        self._test_btn.setEnabled(False)
        self._test_lbl.setText("Probing…")
        self._test_lbl.setStyleSheet("font-size:12px;color:#6e7681;")

        def _probe():
            t0 = _time.monotonic()
            try:
                with socket.create_connection((host, port), timeout=3.0):
                    ms = int((_time.monotonic() - t0) * 1000)
                result = (True, f"✓  {host}:{port}  —  {ms} ms")
            except OSError as exc:
                result = (False, f"✗  {exc}")
            # marshal back to Qt main thread via a QTimer zero-shot
                QMetaObject.invokeMethod(
                self, "_apply_test_result",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(bool, result[0]),
                Q_ARG(str, result[1]),
            )

        threading.Thread(target=_probe, daemon=True).start()

    @pyqtSlot(bool, str)
    def _apply_test_result(self, ok: bool, msg: str):
        self._test_btn.setEnabled(True)
        color = "#3fb950" if ok else "#f85149"
        self._test_lbl.setText(msg)
        self._test_lbl.setStyleSheet(f"font-size:12px;color:{color};")

    def _restore_combo(self, combo: QComboBox, saved):
        if saved is None:
            return
        for i in range(combo.count()):
            if str(combo.itemData(i)) == str(saved):
                combo.setCurrentIndex(i)
                return

    def _accept(self):
        _S.setValue("mumble/host",       self._host.text().strip())
        _S.setValue("mumble/port",       self._port.value())
        _S.setValue("mumble/username",   self._user.text().strip())
        _S.setValue("mumble/password",   self._pwd.text())
        _S.setValue("mumble/channel",    self._chan.text().strip())
        _S.setValue("mumble/in_device",  self._in_dev.currentData())
        _S.setValue("mumble/out_device", self._out_dev.currentData())
        self.accept()

    @property
    def params(self) -> dict:
        return {
            "host":       _S.value("mumble/host", ""),
            "port":       int(_S.value("mumble/port", 64738)),
            "username":   _S.value("mumble/username", ""),
            "password":   _S.value("mumble/password", ""),
            "channel":    _S.value("mumble/channel", ""),
            "in_device":  _S.value("mumble/in_device",  None),
            "out_device": _S.value("mumble/out_device", None),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Main panel
# ─────────────────────────────────────────────────────────────────────────────

class MumblePanel(QWidget):
    """Mumble voice panel — embeds in the right info strip."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client  = MumbleClient(self)
        self._channels: list[dict] = []
        self._users:    list[dict] = []
        self._ptt_held = False
        self._server_addr:    str  = ""
        self._handshake_done: bool = False

        self._build()
        self._wire()

    # ── Build UI ─────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Status header ────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setStyleSheet("background:#161b22;border:1px solid #21262d;border-radius:2px;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8, 6, 8, 6)

        self._led = QLabel("●")
        self._led.setFont(QFont("Courier New", 15))
        self._led.setStyleSheet("color:#484f58;")
        hl.addWidget(self._led)

        self._status = QLabel("Disconnected")
        self._status.setFont(_MONO)
        self._status.setStyleSheet("color:#6e7681;")
        hl.addWidget(self._status, 1)

        self._conn_btn = QPushButton("Connect")
        self._conn_btn.setObjectName("toolButton")
        self._conn_btn.setFixedWidth(80)
        self._conn_btn.clicked.connect(self._on_connect_clicked)
        hl.addWidget(self._conn_btn)

        root.addWidget(hdr)

        # ── Channel tree ─────────────────────────────────────────────────
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setFont(_MONO)
        self._tree.setMinimumHeight(160)
        self._tree.setStyleSheet(
            "QTreeWidget{background:#0d1117;border:1px solid #21262d;}"
            "QTreeWidget::item{padding:2px 4px;color:#c9d1d9;}"
            "QTreeWidget::item:selected{background:#1c2d3f;color:#79c0ff;}"
        )
        self._tree.itemDoubleClicked.connect(self._on_channel_dclick)
        root.addWidget(self._tree)

        # ── User list ────────────────────────────────────────────────────
        user_lbl = QLabel("USERS IN CHANNEL")
        user_lbl.setStyleSheet(
            "color:#484f58;font-size:11px;font-weight:700;letter-spacing:2px;"
        )
        root.addWidget(user_lbl)

        self._user_list = QTreeWidget()
        self._user_list.setHeaderHidden(True)
        self._user_list.setFont(_MONO)
        self._user_list.setMaximumHeight(130)
        self._user_list.setStyleSheet(
            "QTreeWidget{background:#0d1117;border:1px solid #21262d;}"
            "QTreeWidget::item{padding:2px 4px;}"
        )
        root.addWidget(self._user_list)

        # ── Controls ─────────────────────────────────────────────────────
        ctrl = QFrame()
        ctrl.setStyleSheet("background:#161b22;border:1px solid #21262d;border-radius:2px;")
        cl = QVBoxLayout(ctrl)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.setSpacing(6)

        btn_row = QHBoxLayout()

        # PTT — hold to talk
        self._ptt_btn = QPushButton("🎙  HOLD TO TALK")
        self._ptt_btn.setCheckable(False)
        self._ptt_btn.setMinimumHeight(36)
        self._ptt_btn.setStyleSheet(
            "QPushButton{background:#1c2d3f;border:1px solid #388bfd;"
            "color:#79c0ff;font-weight:700;font-family:'Courier New',monospace;"
            "font-size:13px;letter-spacing:0.5px;border-radius:2px;}"
            "QPushButton:pressed{background:#388bfd;color:#fff;border-color:#388bfd;}"
            "QPushButton:disabled{background:#161b22;color:#484f58;border-color:#21262d;}"
        )
        self._ptt_btn.pressed.connect(self._ptt_press)
        self._ptt_btn.released.connect(self._ptt_release)
        self._ptt_btn.setEnabled(False)
        cl.addWidget(self._ptt_btn)

        # Mute / Deafen
        self._mute_btn = QPushButton("🎤 Mute")
        self._mute_btn.setCheckable(True)
        self._mute_btn.setEnabled(False)
        self._mute_btn.toggled.connect(self._on_mute)
        btn_row.addWidget(self._mute_btn)

        self._deaf_btn = QPushButton("🔇 Deafen")
        self._deaf_btn.setCheckable(True)
        self._deaf_btn.setEnabled(False)
        self._deaf_btn.toggled.connect(self._on_deafen)
        btn_row.addWidget(self._deaf_btn)

        cl.addLayout(btn_row)

        # Volume
        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("Vol"))
        self._vol = QSlider(Qt.Orientation.Horizontal)
        self._vol.setRange(0, 100)
        self._vol.setValue(80)
        self._vol.setEnabled(False)
        vol_row.addWidget(self._vol, 1)
        self._vol_lbl = QLabel("80")
        self._vol_lbl.setFixedWidth(28)
        self._vol_lbl.setFont(_MONO)
        self._vol_lbl.setStyleSheet("color:#6e7681;")
        vol_row.addWidget(self._vol_lbl)
        self._vol.valueChanged.connect(lambda v: self._vol_lbl.setText(str(v)))
        cl.addLayout(vol_row)

        root.addWidget(ctrl)

    # ── Wire signals ─────────────────────────────────────────────────────────

    def _wire(self):
        self._client.state_changed.connect(self._on_state)
        self._client.channels_updated.connect(self._on_channels)
        self._client.users_updated.connect(self._on_users)
        self._client.speaking_changed.connect(self._on_speaking)

    # ── Slots ────────────────────────────────────────────────────────────────

    def _on_connect_clicked(self):
        if self._conn_btn.text() == "Disconnect":
            self._client.disconnect()
            return

        dlg = _ConnectDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        p = dlg.params
        if not p["host"] or not p["username"]:
            return
        self._server_addr = f"{p['host']}:{p['port']}"
        self._client.set_devices(p["in_device"], p["out_device"])
        self._client.connect_to(
            p["host"], p["port"], p["username"], p["password"], p["channel"]
        )

    def _on_state(self, state: str):
        if state == "connected":
            self._handshake_done = False
            self._led.setStyleSheet("color:#3fb950;")
            self._status.setText(self._server_addr or "Connected")
            self._status.setStyleSheet("color:#3fb950;")
            self._conn_btn.setText("Disconnect")
            for w in (self._ptt_btn, self._mute_btn, self._deaf_btn, self._vol):
                w.setEnabled(True)

        elif state == "connecting":
            self._led.setStyleSheet("color:#d29922;")
            self._status.setText("Connecting…")
            self._status.setStyleSheet("color:#d29922;")
            self._conn_btn.setEnabled(False)

        elif state == "disconnected":
            self._handshake_done = False
            self._led.setStyleSheet("color:#484f58;")
            self._status.setText("Disconnected")
            self._status.setStyleSheet("color:#6e7681;")
            self._conn_btn.setText("Connect")
            self._conn_btn.setEnabled(True)
            for w in (self._ptt_btn, self._mute_btn, self._deaf_btn, self._vol):
                w.setEnabled(False)
            self._tree.clear()
            self._user_list.clear()

        elif state.startswith("error:"):
            msg = state[6:]
            self._led.setStyleSheet("color:#f85149;")
            self._status.setText(f"Error: {msg[:40]}")
            self._status.setStyleSheet("color:#f85149;")
            self._conn_btn.setText("Connect")
            self._conn_btn.setEnabled(True)

    def _on_channels(self, channels: list[dict]):
        self._channels = channels
        self._rebuild_tree()

    def _on_users(self, users: list[dict]):
        self._users = users
        self._rebuild_tree()
        self._rebuild_user_list()
        if not self._handshake_done and users:
            self_user = next((u for u in users if u.get("self")), None)
            self._handshake_done = True
            if self_user:
                n = len(users)
                ch = len(self._channels)
                self._status.setText(f"✓ comms OK · {n} user{'s' if n>1 else ''} · {ch} ch")
                self._status.setStyleSheet("color:#3fb950;")
                QTimer.singleShot(5000, self._restore_status)
            else:
                self._status.setText("⚠ connected — not in user list")
                self._status.setStyleSheet("color:#d29922;")
                QTimer.singleShot(5000, self._restore_status)

    def _restore_status(self):
        if self._conn_btn.text() == "Disconnect":
            self._status.setText(self._server_addr or "Connected")
            self._status.setStyleSheet("color:#3fb950;")

    def _on_speaking(self, name: str, speaking: bool):
        # Update user list item colour live
        root = self._user_list.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            if item.data(0, Qt.ItemDataRole.UserRole + 1) == name:
                _set_speaking(item, speaking)
                break

    def _on_channel_dclick(self, item: QTreeWidgetItem, _col: int):
        cid = item.data(0, Qt.ItemDataRole.UserRole)
        if cid is not None:
            self._client.join_channel(cid)

    def _ptt_press(self):
        if not self._client._audio_in:
            self._status.setText("⚠ No mic — check permissions")
            self._status.setStyleSheet("color:#d29922;")
            QTimer.singleShot(4000, self._restore_status)
            return
        self._client.set_ptt(True)
        self._ptt_btn.setStyleSheet(
            "QPushButton{background:#388bfd;border:1px solid #58a6ff;"
            "color:#fff;font-weight:700;font-family:'Courier New',monospace;"
            "font-size:13px;letter-spacing:0.5px;border-radius:2px;}"
        )

    def _ptt_release(self):
        self._client.set_ptt(False)
        self._ptt_btn.setStyleSheet(
            "QPushButton{background:#1c2d3f;border:1px solid #388bfd;"
            "color:#79c0ff;font-weight:700;font-family:'Courier New',monospace;"
            "font-size:13px;letter-spacing:0.5px;border-radius:2px;}"
            "QPushButton:pressed{background:#388bfd;color:#fff;border-color:#388bfd;}"
            "QPushButton:disabled{background:#161b22;color:#484f58;border-color:#21262d;}"
        )

    def _on_mute(self, checked: bool):
        self._client.set_muted(checked)
        self._mute_btn.setText("🔴 Muted" if checked else "🎤 Mute")

    def _on_deafen(self, checked: bool):
        self._client.set_deafened(checked)
        self._deaf_btn.setText("🔇 Deafened" if checked else "🔇 Deafen")

    # ── Tree builders ────────────────────────────────────────────────────────

    def _rebuild_tree(self):
        self._tree.clear()
        # Build id → item map
        id_map: dict[int, QTreeWidgetItem] = {}
        # Sort channels root-first
        for ch in sorted(self._channels, key=lambda c: c.get("parent_id", -1)):
            cid     = ch["id"]
            name    = ch["name"]
            parent  = ch.get("parent_id", -1)

            item = QTreeWidgetItem([f"📁 {name}"])
            item.setData(0, Qt.ItemDataRole.UserRole, cid)
            item.setFont(0, _MONO)
            item.setForeground(0, QColor("#8b949e"))
            id_map[cid] = item

            # Add users in this channel
            for u in self._users:
                if u.get("channel_id") == cid:
                    _make_user_item(item, u)

            if parent in id_map:
                id_map[parent].addChild(item)
            else:
                self._tree.addTopLevelItem(item)

        self._tree.expandAll()

    def _rebuild_user_list(self):
        # Find my current channel
        my_channel = None
        for u in self._users:
            if u.get("self"):
                my_channel = u.get("channel_id")
                break

        self._user_list.clear()
        root = self._user_list.invisibleRootItem()
        for u in self._users:
            if my_channel is not None and u.get("channel_id") != my_channel:
                continue
            item = QTreeWidgetItem([_user_label(u)])
            item.setFont(0, _MONO)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, u["name"])
            _set_speaking(item, u.get("speaking", False))
            root.addChild(item)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_user_item(parent: QTreeWidgetItem, u: dict) -> QTreeWidgetItem:
    item = QTreeWidgetItem(parent, [_user_label(u)])
    item.setFont(0, _MONO)
    item.setData(0, Qt.ItemDataRole.UserRole + 1, u["name"])
    _set_speaking(item, u.get("speaking", False))
    return item


def _user_label(u: dict) -> str:
    icons = ""
    if u.get("self"):     icons += " ◆"
    if u.get("muted"):    icons += " 🔴"
    if u.get("deafened"): icons += " 🔇"
    return f"{'🔊 ' if u.get('speaking') else '  '}{u['name']}{icons}"


def _set_speaking(item: QTreeWidgetItem, speaking: bool):
    color = "#3fb950" if speaking else "#c9d1d9"
    item.setForeground(0, QColor(color))
    # Rebuild label
    name = item.data(0, Qt.ItemDataRole.UserRole + 1) or item.text(0)
    prefix = "🔊 " if speaking else "  "
    rest = item.text(0).lstrip("🔊 ")
    item.setText(0, prefix + rest.strip())


def _lbl(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "color:#8b949e;font-size:12px;font-weight:600;letter-spacing:1.2px;"
    )
    return lbl
