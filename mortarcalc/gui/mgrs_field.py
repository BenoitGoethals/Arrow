"""MgrsLineEdit — een QLineEdit die MGRS-invoer live valideert.

Geeft visuele feedback (rode rand + tooltip) zodra de getypte grid-referentie
structureel ongeldig is, zodat fouten zichtbaar zijn vóór het indienen. De
uiteindelijke conversie blijft via `mgrs_to_utm`, dat dezelfde validatie plus
de echte coördinaat-omzetting doet.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QLineEdit

from ..geo import validate_mgrs, MGRSError

_INVALID_STYLE = "border: 1px solid #c0392b;"


class MgrsLineEdit(QLineEdit):
    """QLineEdit met live MGRS-validatie."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if not self.placeholderText():
            self.setPlaceholderText("e.g. 31UDS1234567890")
        self.textChanged.connect(self._revalidate)

    def _revalidate(self) -> None:
        text = self.text().strip()
        if not text:                       # leeg = neutraal (nog niets ingevuld)
            self.setStyleSheet("")
            self.setToolTip("")
            return
        try:
            validate_mgrs(text)
        except MGRSError as e:
            self.setStyleSheet(_INVALID_STYLE)
            self.setToolTip(str(e))
        else:
            self.setStyleSheet("")
            self.setToolTip("Valid MGRS grid reference")

    def is_valid(self) -> bool:
        try:
            validate_mgrs(self.text())
        except MGRSError:
            return False
        return True
