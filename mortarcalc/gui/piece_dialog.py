"""Modal dialogs for adding/editing pieces and aiming points."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox,
    QPushButton, QHBoxLayout, QMessageBox, QDialogButtonBox, QWidget,
    QGroupBox, QVBoxLayout,
)

from ..battery import (
    Peloton, Piece, AimingPoint, Observer,
    KNOWN_SHELLS, DEFAULT_INITIAL_STOCK, shell_label,
)
from ..geo import mgrs_to_utm, Position
from ..geo.current_location import get_current_position, LocationUnavailable
from .coord_dialog import prompt_position
from .mgrs_field import MgrsLineEdit


def _acquire_position(parent) -> Position | None:
    try:
        return get_current_position()
    except LocationUnavailable as e:
        if QMessageBox.question(
            parent, "GPS unavailable",
            f"{e}\n\nEnter coordinates manually?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes,
        ) == QMessageBox.StandardButton.Yes:
            return prompt_position(parent)
        return None


class _CoordInputs:
    """Group of MGRS + altitude + 'Current location' button."""

    def __init__(self, parent: QDialog) -> None:
        self.parent = parent
        self.mgrs = MgrsLineEdit(); self.mgrs.setMinimumWidth(220)
        self.alt = QDoubleSpinBox(); self.alt.setRange(-500, 9000); self.alt.setSuffix(" m")
        self.btn_loc = QPushButton("Current location")
        self.btn_loc.clicked.connect(self._fill_from_location)
        self.mgrs_row = QWidget()
        row = QHBoxLayout(self.mgrs_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.mgrs, 1)
        row.addWidget(self.btn_loc)

    def _fill_from_location(self) -> None:
        pos = _acquire_position(self.parent)
        if pos is None:
            return
        self.mgrs.setText(pos.to_mgrs())
        self.alt.setValue(pos.altitude_m)


class AddPieceDialog(QDialog):
    """Modal: add or edit a single mortar piece with per-shell ammo.

    Pass ``piece`` (and optionally ``ammo``) to open in edit mode, pre-filling
    every field. After accept(): .result_piece is set and .result_ammo holds
    {shell: count} for every shell.
    """

    def __init__(
        self,
        peloton: Peloton,
        parent=None,
        *,
        piece: Piece | None = None,
        ammo: dict[str, int] | None = None,
    ) -> None:
        super().__init__(parent)
        self.peloton = peloton
        self.result_piece: Piece | None = None
        self.result_ammo: dict[str, int] = {}
        # In edit mode this is the original name so the duplicate check can
        # ignore the piece being edited (and the caller knows to update).
        self.original_name: str | None = piece.name if piece is not None else None

        self.setWindowTitle("Edit piece" if piece is not None else "Add piece")
        self.setModal(True)
        self.resize(440, 0)

        root = QVBoxLayout(self)

        # ---- identity + position ----
        form = QFormLayout()
        self.name = QLineEdit(); self.name.setPlaceholderText("e.g. A, B, 1, 2")
        self.name.setMinimumWidth(220)
        self.coords = _CoordInputs(self)
        self.role = QComboBox(); self.role.addItems(["Slave piece", "Base piece"])
        form.addRow("Name", self.name)
        form.addRow("GPS (MGRS)", self.coords.mgrs_row)
        form.addRow("Altitude", self.coords.alt)
        form.addRow("Role", self.role)
        root.addLayout(form)

        # ---- per-shell stock ----
        ammo_box = QGroupBox("Ammunition (per shell type)")
        ammo_form = QFormLayout(ammo_box)
        self.ammo_spinners: dict[str, QSpinBox] = {}
        for shell in KNOWN_SHELLS:
            sb = QSpinBox()
            sb.setRange(0, 999)
            sb.setValue(DEFAULT_INITIAL_STOCK.get(shell, 0))
            sb.setSuffix(" rnd")
            ammo_form.addRow(shell_label(shell), sb)
            self.ammo_spinners[shell] = sb
        root.addWidget(ammo_box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        if piece is not None:
            self._prefill(piece, ammo or {})
        self.name.setFocus()

    def _prefill(self, piece: Piece, ammo: dict[str, int]) -> None:
        self.name.setText(piece.name)
        self.coords.mgrs.setText(piece.position.to_mgrs())
        self.coords.alt.setValue(piece.position.altitude_m)
        self.role.setCurrentIndex(1 if piece.is_base else 0)
        for shell, sb in self.ammo_spinners.items():
            sb.setValue(int(ammo.get(shell, 0)))

    def _on_ok(self) -> None:
        name = self.name.text().strip() or f"#{len(self.peloton.pieces) + 1}"
        try:
            pos = mgrs_to_utm(self.coords.mgrs.text().strip(), altitude_m=self.coords.alt.value())
        except Exception as e:
            QMessageBox.warning(self, "MGRS error", str(e))
            return
        if name != self.original_name and any(p.name == name for p in self.peloton.pieces):
            QMessageBox.warning(self, "Piece", f"Piece '{name}' already exists.")
            return
        self.result_piece = Piece(name=name, position=pos, is_base=(self.role.currentIndex() == 1))
        self.result_ammo = {
            shell: sb.value()
            for shell, sb in self.ammo_spinners.items()
        }
        self.accept()


class AddAimingPointDialog(QDialog):
    """Modal: add a single aiming point."""

    def __init__(self, peloton: Peloton, parent=None) -> None:
        super().__init__(parent)
        self.peloton = peloton
        self.result_ap: AimingPoint | None = None

        self.setWindowTitle("Add aiming point")
        self.setModal(True)

        form = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setMinimumWidth(220)
        self.coords = _CoordInputs(self)
        form.addRow("Name", self.name)
        form.addRow("MGRS", self.coords.mgrs_row)
        form.addRow("Altitude", self.coords.alt)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.name.setFocus()

    def _on_ok(self) -> None:
        name = self.name.text().strip()
        if not name:
            QMessageBox.information(self, "Name", "Provide a name for the aiming point.")
            return
        try:
            pos = mgrs_to_utm(self.coords.mgrs.text().strip(), altitude_m=self.coords.alt.value())
        except Exception as e:
            QMessageBox.warning(self, "MGRS error", str(e))
            return
        if any(a.name == name for a in self.peloton.aiming_points):
            QMessageBox.warning(self, "Aiming point", f"Aiming point '{name}' already exists.")
            return
        self.result_ap = AimingPoint(name=name, position=pos)
        self.accept()


class AddObserverDialog(QDialog):
    """Modal: add or edit a Forward Observer (call sign + position).

    Pass ``observer`` to open in edit mode. After accept(): .result_observer
    holds the new Observer.
    """

    def __init__(self, peloton: Peloton, parent=None, *, observer: Observer | None = None) -> None:
        super().__init__(parent)
        self.peloton = peloton
        self.result_observer: Observer | None = None
        self.original_call_sign: str | None = observer.call_sign if observer else None

        self.setWindowTitle("Edit FO" if observer else "Add FO")
        self.setModal(True)

        form = QFormLayout(self)
        self.call_sign = QLineEdit()
        self.call_sign.setPlaceholderText("call sign, e.g. OP1")
        self.call_sign.setMinimumWidth(220)
        self.coords = _CoordInputs(self)
        form.addRow("Call sign", self.call_sign)
        form.addRow("MGRS", self.coords.mgrs_row)
        form.addRow("Altitude", self.coords.alt)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        if observer is not None:
            self.call_sign.setText(observer.call_sign)
            self.coords.mgrs.setText(observer.position.to_mgrs())
            self.coords.alt.setValue(observer.position.altitude_m)
        self.call_sign.setFocus()

    def _on_ok(self) -> None:
        call_sign = self.call_sign.text().strip()
        if not call_sign:
            QMessageBox.information(self, "Call sign", "Provide a call sign for the FO.")
            return
        try:
            pos = mgrs_to_utm(self.coords.mgrs.text().strip(), altitude_m=self.coords.alt.value())
        except Exception as e:
            QMessageBox.warning(self, "MGRS error", str(e))
            return
        if call_sign != self.original_call_sign and any(
            o.call_sign == call_sign for o in self.peloton.observers
        ):
            QMessageBox.warning(self, "FO", f"FO '{call_sign}' already exists.")
            return
        self.result_observer = Observer(call_sign=call_sign, position=pos)
        self.accept()
