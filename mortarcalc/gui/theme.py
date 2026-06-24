"""Military / fire-direction-center visual theme.

A single olive-drab dark theme applied globally so every panel, dialog and
native control inherits the same tactical look. Call :func:`apply_theme` once
on the QApplication at start-up.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

# ---- palette ---------------------------------------------------------------
# Olive drab / khaki field-radio scheme.
_BG_DARK = "#1d2116"      # window / deepest background
_BG_PANEL = "#272c1d"     # panels, inputs
_BG_RAISED = "#323924"    # buttons, headers, raised surfaces
_BORDER = "#55663b"       # olive borders / dividers
_BORDER_HI = "#7d9450"    # focused / hovered border
_TEXT = "#d6dcc4"         # pale khaki body text
_TEXT_DIM = "#8a9173"     # muted / disabled text
_ACCENT = "#c8a13e"       # amber — selections, highlights
_SIGNAL = "#9fc070"       # signal green — active / ok
_DANGER = "#c25a3a"       # rounds-on-target red-orange


def _build_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(_BG_DARK))
    p.setColor(QPalette.ColorRole.WindowText, QColor(_TEXT))
    p.setColor(QPalette.ColorRole.Base, QColor(_BG_PANEL))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(_BG_RAISED))
    p.setColor(QPalette.ColorRole.Text, QColor(_TEXT))
    p.setColor(QPalette.ColorRole.Button, QColor(_BG_RAISED))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(_TEXT))
    p.setColor(QPalette.ColorRole.BrightText, QColor(_DANGER))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(_BG_RAISED))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(_TEXT))
    p.setColor(QPalette.ColorRole.Highlight, QColor(_ACCENT))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(_BG_DARK))
    p.setColor(QPalette.ColorRole.Link, QColor(_SIGNAL))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(_TEXT_DIM))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(_TEXT_DIM))
    return p


# ---- stylesheet ------------------------------------------------------------
QSS = f"""
* {{
    font-family: "Menlo", "DejaVu Sans Mono", "Consolas", monospace;
    font-size: 12px;
}}

QMainWindow, QDialog, QWidget {{
    background-color: {_BG_DARK};
    color: {_TEXT};
}}

/* --- group boxes: stencilled field-form sections --- */
QGroupBox {{
    background-color: {_BG_PANEL};
    border: 1px solid {_BORDER};
    border-radius: 3px;
    margin-top: 14px;
    padding: 8px 6px 6px 6px;
    font-weight: bold;
    text-transform: uppercase;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 1px 8px;
    color: {_ACCENT};
    background-color: {_BG_RAISED};
    border: 1px solid {_BORDER};
    border-radius: 2px;
    letter-spacing: 1px;
}}

/* --- buttons --- */
QPushButton {{
    background-color: {_BG_RAISED};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 2px;
    padding: 5px 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QPushButton:hover {{
    border-color: {_BORDER_HI};
    background-color: #3b431f;
}}
QPushButton:pressed {{
    background-color: {_ACCENT};
    color: {_BG_DARK};
}}
QPushButton:disabled {{
    color: {_TEXT_DIM};
    border-color: #3a4128;
}}
QPushButton:default {{
    border: 1px solid {_ACCENT};
}}

/* --- text inputs / spin boxes --- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {_BG_DARK};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 2px;
    padding: 3px 6px;
    selection-background-color: {_ACCENT};
    selection-color: {_BG_DARK};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {_BORDER_HI};
}}
QComboBox::drop-down {{
    border-left: 1px solid {_BORDER};
    width: 18px;
}}
QComboBox QAbstractItemView {{
    background-color: {_BG_PANEL};
    border: 1px solid {_BORDER};
    selection-background-color: {_ACCENT};
    selection-color: {_BG_DARK};
}}

/* --- tables --- */
QTableWidget, QTableView, QListWidget, QTreeWidget, QTreeView {{
    background-color: {_BG_PANEL};
    alternate-background-color: {_BG_DARK};
    gridline-color: {_BORDER};
    border: 1px solid {_BORDER};
    selection-background-color: {_ACCENT};
    selection-color: {_BG_DARK};
}}
QHeaderView::section {{
    background-color: {_BG_RAISED};
    color: {_ACCENT};
    border: none;
    border-right: 1px solid {_BORDER};
    border-bottom: 1px solid {_BORDER};
    padding: 4px 6px;
    text-transform: uppercase;
    letter-spacing: 1px;
    font-weight: bold;
}}
QTableCornerButton::section {{
    background-color: {_BG_RAISED};
    border: 1px solid {_BORDER};
}}

/* --- tabs: nato-style tracking bar --- */
QTabWidget::pane {{
    border: 1px solid {_BORDER};
    top: -1px;
}}
QTabBar::tab {{
    background-color: {_BG_PANEL};
    color: {_TEXT_DIM};
    border: 1px solid {_BORDER};
    border-bottom: none;
    padding: 7px 16px;
    margin-right: 2px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QTabBar::tab:selected {{
    background-color: {_BG_RAISED};
    color: {_ACCENT};
    border-top: 2px solid {_ACCENT};
}}
QTabBar::tab:hover:!selected {{
    color: {_TEXT};
}}

/* --- menus --- */
QMenuBar {{
    background-color: {_BG_DARK};
    color: {_TEXT};
    border-bottom: 1px solid {_BORDER};
}}
QMenuBar::item:selected {{
    background-color: {_BG_RAISED};
    color: {_ACCENT};
}}
QMenu {{
    background-color: {_BG_PANEL};
    border: 1px solid {_BORDER};
}}
QMenu::item:selected {{
    background-color: {_ACCENT};
    color: {_BG_DARK};
}}
QMenu::separator {{
    height: 1px;
    background-color: {_BORDER};
    margin: 4px 8px;
}}

/* --- status bar: signal strip --- */
QStatusBar {{
    background-color: {_BG_RAISED};
    color: {_SIGNAL};
    border-top: 1px solid {_BORDER};
}}
QStatusBar::item {{ border: none; }}

/* --- misc --- */
QSplitter::handle {{ background-color: {_BORDER}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}

QScrollBar:vertical {{
    background: {_BG_DARK}; width: 12px; margin: 0;
}}
QScrollBar:horizontal {{
    background: {_BG_DARK}; height: 12px; margin: 0;
}}
QScrollBar::handle {{
    background: {_BORDER}; border-radius: 2px; min-height: 24px; min-width: 24px;
}}
QScrollBar::handle:hover {{ background: {_BORDER_HI}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QToolTip {{
    background-color: {_BG_RAISED};
    color: {_TEXT};
    border: 1px solid {_ACCENT};
    padding: 3px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {_BORDER};
    background: {_BG_DARK};
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {_SIGNAL};
    border-color: {_SIGNAL};
}}
"""


def apply_theme(app: QApplication) -> None:
    """Apply the military FDC theme to the whole application."""
    app.setStyle("Fusion")
    app.setPalette(_build_palette())
    app.setFont(QFont("Menlo", 10))
    app.setStyleSheet(QSS)
