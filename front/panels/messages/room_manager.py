"""Chat-room manager dialog for Arrow Front — create rooms, add/remove members."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QInputDialog, QMessageBox, QWidget,
)


class RoomManagerDialog(QDialog):
    """Manage chat rooms and their membership.

    Left: room list (+ New / Delete). Right: member checkboxes for the selected
    room with a Save button that diffs against the server. All calls go through
    the shared ArrowClient. Emits ``rooms_changed`` whenever the server is
    mutated so the parent can refresh its room combo.
    """

    rooms_changed = pyqtSignal()

    def __init__(self, client, operators: list[dict], parent=None):
        super().__init__(parent)
        self._client = client
        self._operators = operators or []
        self._rooms: list[dict] = []
        self.setWindowTitle("Chat Rooms")
        self.resize(560, 420)
        self._build_ui()
        self._reload_rooms()

    # ---- UI ----------------------------------------------------------------
    def _build_ui(self):
        root = QHBoxLayout(self)

        # Left — room list
        left = QVBoxLayout()
        left.addWidget(QLabel("Rooms", styleSheet="font-weight:700;color:#8b949e"))
        self._room_list = QListWidget()
        self._room_list.currentRowChanged.connect(lambda _: self._on_room_selected())
        left.addWidget(self._room_list, 1)
        row = QHBoxLayout()
        new_btn = QPushButton("＋ New")
        new_btn.clicked.connect(self._new_room)
        del_btn = QPushButton("🗑 Delete")
        del_btn.clicked.connect(self._delete_room)
        row.addWidget(new_btn); row.addWidget(del_btn)
        left.addLayout(row)
        lw = QWidget(); lw.setLayout(left); lw.setFixedWidth(220)
        root.addWidget(lw)

        # Right — members
        right = QVBoxLayout()
        self._members_label = QLabel("Members", styleSheet="font-weight:700;color:#8b949e")
        right.addWidget(self._members_label)
        self._member_list = QListWidget()
        right.addWidget(self._member_list, 1)
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self._save_btn = QPushButton("Save members")
        self._save_btn.setObjectName("primaryButton")
        self._save_btn.clicked.connect(self._save_members)
        save_row.addWidget(self._save_btn)
        right.addLayout(save_row)
        root.addLayout(right, 1)

    # ---- Data --------------------------------------------------------------
    def _reload_rooms(self, select_id: int | None = None):
        try:
            self._rooms = self._client.chatrooms()
        except Exception as e:
            QMessageBox.warning(self, "Chat Rooms", f"Failed to load rooms: {e}")
            self._rooms = []
        self._room_list.blockSignals(True)
        self._room_list.clear()
        target_row = 0
        for i, r in enumerate(self._rooms):
            item = QListWidgetItem(f"# {r.get('name', '?')}  ({len(r.get('member_ids', []))})")
            item.setData(Qt.ItemDataRole.UserRole, r.get("id"))
            self._room_list.addItem(item)
            if select_id is not None and r.get("id") == select_id:
                target_row = i
        self._room_list.blockSignals(False)
        if self._rooms:
            self._room_list.setCurrentRow(target_row)
        else:
            self._member_list.clear()
        self.rooms_changed.emit()

    def _current_room(self) -> dict | None:
        item = self._room_list.currentItem()
        if not item:
            return None
        rid = item.data(Qt.ItemDataRole.UserRole)
        return next((r for r in self._rooms if r.get("id") == rid), None)

    def _on_room_selected(self):
        room = self._current_room()
        self._member_list.clear()
        if not room:
            return
        members = set(room.get("member_ids", []))
        self._members_label.setText(f"Members — # {room.get('name', '?')}")
        for op in self._operators:
            item = QListWidgetItem(f"{op.get('callsign', '?')}  ({op.get('role', '')})")
            item.setData(Qt.ItemDataRole.UserRole, op.get("id"))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if op.get("id") in members else Qt.CheckState.Unchecked
            )
            self._member_list.addItem(item)

    # ---- Actions -----------------------------------------------------------
    def _new_room(self):
        name, ok = QInputDialog.getText(self, "New Chat Room", "Room name:")
        if not ok or not name.strip():
            return
        try:
            room = self._client.create_chatroom(name.strip())
            self._reload_rooms(select_id=room.get("id"))
        except Exception as e:
            QMessageBox.warning(self, "Chat Rooms", f"Create failed: {e}")

    def _delete_room(self):
        room = self._current_room()
        if not room:
            return
        if QMessageBox.question(self, "Delete Room",
                                f"Delete room '{room.get('name')}'?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self._client.delete_chatroom(room["id"])
            self._reload_rooms()
        except Exception as e:
            QMessageBox.warning(self, "Chat Rooms", f"Delete failed: {e}")

    def _save_members(self):
        room = self._current_room()
        if not room:
            return
        rid = room["id"]
        current = set(room.get("member_ids", []))
        try:
            for i in range(self._member_list.count()):
                item = self._member_list.item(i)
                op_id = item.data(Qt.ItemDataRole.UserRole)
                checked = item.checkState() == Qt.CheckState.Checked
                if checked and op_id not in current:
                    self._client.add_chatroom_member(rid, op_id)
                elif not checked and op_id in current:
                    self._client.remove_chatroom_member(rid, op_id)
            self._reload_rooms(select_id=rid)
        except Exception as e:
            QMessageBox.warning(self, "Chat Rooms", f"Save failed: {e}")
