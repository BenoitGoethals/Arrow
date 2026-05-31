"""Arrow Front — Tactical Dark QSS theme (Frontline-style)."""

TACTICAL_DARK = """
/* ============================================================
   ARROW FRONT — Tactical Dark Theme
   Inspired by Sitaware Frontline
   ============================================================ */

/* ---- Base -------------------------------------------------- */
QMainWindow, QWidget {
    background-color: #0d1117;
    color: #c9d1d9;
    font-family: "Ubuntu", "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 11px;
}

/* ---- Menu bar ---------------------------------------------- */
QMenuBar {
    background-color: #161b22;
    color: #c9d1d9;
    border-bottom: 1px solid #21262d;
    padding: 2px 4px;
    spacing: 2px;
}
QMenuBar::item { padding: 4px 10px; border-radius: 2px; }
QMenuBar::item:selected { background-color: #1f6feb; color: #ffffff; }

QMenu {
    background-color: #161b22;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 4px 0;
}
QMenu::item { padding: 5px 24px 5px 16px; }
QMenu::item:selected { background-color: #1f6feb; color: #ffffff; }
QMenu::separator { height: 1px; background: #30363d; margin: 4px 0; }

/* ---- Toolbar ----------------------------------------------- */
QToolBar {
    background-color: #161b22;
    border: none;
    border-bottom: 1px solid #21262d;
    spacing: 2px;
    padding: 3px 6px;
}
QToolBar::separator {
    width: 1px;
    background: #30363d;
    margin: 4px 6px;
}

/* ---- Dock widgets ------------------------------------------ */
QDockWidget {
    color: #8b949e;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}
QDockWidget::title {
    background-color: #161b22;
    border-bottom: 1px solid #21262d;
    padding: 5px 10px;
    text-align: left;
}
QDockWidget::close-button, QDockWidget::float-button {
    background: transparent;
    border: none;
    subcontrol-position: top right;
    subcontrol-origin: margin;
    top: 5px;
    right: 5px;
    width: 14px;
    height: 14px;
}
QDockWidget::close-button:hover { background: #f85149; border-radius: 2px; }

/* ---- Tab widget -------------------------------------------- */
QTabWidget::pane {
    border: none;
    background: #0d1117;
}
QTabBar {
    background: #161b22;
}
QTabBar::tab {
    background: #161b22;
    border: none;
    border-right: 1px solid #21262d;
    color: #6e7681;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 1.5px;
    padding: 6px 12px;
    min-width: 70px;
    text-transform: uppercase;
}
QTabBar::tab:selected {
    background: #0d1117;
    color: #79c0ff;
    border-bottom: 2px solid #1f6feb;
}
QTabBar::tab:hover:!selected { background: #21262d; color: #c9d1d9; }

/* ---- Tree widget ------------------------------------------- */
QTreeWidget {
    background-color: #0d1117;
    alternate-background-color: #0f141a;
    border: none;
    color: #c9d1d9;
    show-decoration-selected: 1;
    outline: 0;
}
QTreeWidget::item {
    padding: 3px 6px;
    border-bottom: 1px solid #161b22;
    min-height: 20px;
}
QTreeWidget::item:selected {
    background-color: #1c2d3f;
    color: #79c0ff;
}
QTreeWidget::item:hover:!selected { background-color: #161b22; }
QTreeWidget::branch { background: #0d1117; }

/* ---- List widget ------------------------------------------- */
QListWidget {
    background-color: #0d1117;
    alternate-background-color: #0f141a;
    border: none;
    color: #c9d1d9;
    outline: 0;
}
QListWidget::item {
    padding: 5px 8px;
    border-bottom: 1px solid #161b22;
    min-height: 22px;
    font-family: "Courier New", Consolas, monospace;
    font-size: 10px;
}
QListWidget::item:selected { background-color: #1c2d3f; color: #79c0ff; }
QListWidget::item:hover:!selected { background-color: #161b22; }

/* ---- Text/edit areas --------------------------------------- */
QTextEdit, QPlainTextEdit {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 2px;
    color: #c9d1d9;
    font-family: "Courier New", Consolas, monospace;
    font-size: 10px;
    selection-background-color: #1f6feb;
}

QLineEdit {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 2px;
    color: #c9d1d9;
    padding: 4px 8px;
    selection-background-color: #1f6feb;
}
QLineEdit:focus { border-color: #388bfd; }
QLineEdit::placeholder { color: #484f58; }

/* ---- Buttons ----------------------------------------------- */
QPushButton {
    background-color: #21262d;
    border: 1px solid #30363d;
    border-radius: 2px;
    color: #c9d1d9;
    padding: 5px 14px;
    min-width: 48px;
}
QPushButton:hover { background-color: #30363d; border-color: #8b949e; }
QPushButton:pressed { background-color: #161b22; }
QPushButton:disabled { color: #484f58; border-color: #21262d; }

QPushButton#primaryButton {
    background-color: #1f6feb;
    border-color: #1f6feb;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#primaryButton:hover { background-color: #388bfd; border-color: #388bfd; }

QPushButton#dangerButton {
    background-color: #8b1538;
    border-color: #da3633;
    color: #ffffff;
    font-weight: 700;
    font-size: 12px;
    letter-spacing: 1px;
}
QPushButton#dangerButton:hover { background-color: #da3633; }

QPushButton#toolButton {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 2px;
    color: #8b949e;
    padding: 4px 10px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.5px;
}
QPushButton#toolButton:hover { background-color: #21262d; color: #c9d1d9; }
QPushButton#toolButton:checked {
    background-color: #1c2d3f;
    border-color: #1f6feb;
    color: #79c0ff;
}

/* ---- Combo box -------------------------------------------- */
QComboBox {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 2px;
    color: #c9d1d9;
    padding: 3px 8px;
    min-width: 70px;
}
QComboBox:focus { border-color: #388bfd; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background-color: #161b22;
    border: 1px solid #30363d;
    color: #c9d1d9;
    selection-background-color: #1f6feb;
}

/* ---- Scroll bars ------------------------------------------- */
QScrollBar:vertical {
    background: #0d1117;
    width: 7px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #30363d;
    min-height: 24px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover { background: #484f58; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QScrollBar:horizontal {
    background: #0d1117;
    height: 7px;
    border: none;
}
QScrollBar::handle:horizontal {
    background: #30363d;
    min-width: 24px;
    border-radius: 3px;
}
QScrollBar::handle:horizontal:hover { background: #484f58; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ---- Status bar -------------------------------------------- */
QStatusBar {
    background-color: #010409;
    border-top: 1px solid #21262d;
    color: #8b949e;
    font-family: "Courier New", Consolas, monospace;
    font-size: 10px;
}
QStatusBar::item { border: none; }
QStatusBar QLabel { color: #8b949e; padding: 0 8px; }

/* ---- Splitter ---------------------------------------------- */
QSplitter::handle { background: #21262d; }
QSplitter::handle:vertical { height: 1px; }
QSplitter::handle:horizontal { width: 1px; }

/* ---- Dialog ------------------------------------------------ */
QDialog {
    background-color: #161b22;
    border: 1px solid #30363d;
}

QDialogButtonBox QPushButton { min-width: 72px; }

/* ---- Named object IDs ------------------------------------- */
QLabel#panelHeader {
    background-color: #161b22;
    color: #8b949e;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 5px 10px;
    border-bottom: 1px solid #21262d;
}

QLabel#sectionHeader {
    color: #484f58;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 2px 4px;
}

QLabel#statusSmall {
    color: #6e7681;
    font-size: 9px;
    font-family: "Courier New", Consolas, monospace;
    border-top: 1px solid #21262d;
    padding: 3px 8px;
}

QLabel#alertTic    { color: #f85149; font-weight: bold; }
QLabel#alertMedvac { color: #ff9e64; font-weight: bold; }
QLabel#alertDrone  { color: #d2a8ff; font-weight: bold; }
QLabel#online  { color: #3fb950; }
QLabel#offline { color: #6e7681; }
"""
