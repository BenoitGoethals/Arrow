"""Global QSS stylesheet — modern dark theme for the launcher.

Palette is roughly Tailwind slate + a single cyan accent. Applied once at
QApplication startup from `sim_gui.app:main`.
"""

from __future__ import annotations

ACCENT = "#38bdf8"  # sky-400
ACCENT_DEEP = "#0ea5e9"  # sky-500
SUCCESS = "#10b981"  # emerald-500
DANGER = "#ef4444"  # red-500
WARN = "#f59e0b"  # amber-500

BG = "#0f1419"  # near-black
BG_PANEL = "#161b22"  # gunmetal
BG_RAISED = "#1f2630"
BORDER = "#2a323d"
TEXT = "#e2e8f0"  # slate-200
TEXT_MUTED = "#94a3b8"  # slate-400
TEXT_DIM = "#64748b"  # slate-500


STYLESHEET = f"""
* {{
    color: {TEXT};
    font-family: -apple-system, "SF Pro Text", "Inter", "Segoe UI", system-ui, sans-serif;
    font-size: 12px;
}}

QMainWindow, QWidget {{
    background-color: {BG};
}}

/* ── Header bar ──────────────────────────────────────────────────────────── */
#HeaderBar {{
    background-color: {BG_PANEL};
    border-bottom: 1px solid {BORDER};
}}
#HeaderTitle {{
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 0.2px;
}}
#HeaderSubtitle {{
    color: {TEXT_MUTED};
    font-size: 11px;
}}
#ConnectionPill {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 4px 10px;
    color: {TEXT_MUTED};
    font-size: 11px;
}}
#ConnectionPill[state="connected"] {{
    color: {SUCCESS};
    border-color: {SUCCESS};
}}
#ConnectionPill[state="disconnected"] {{
    color: {TEXT_DIM};
}}
#ConnectionPill[state="error"] {{
    color: {DANGER};
    border-color: {DANGER};
}}

/* ── Side panels ─────────────────────────────────────────────────────────── */
#SidePanel, #CenterPanel, #RightPanel {{
    background-color: {BG_PANEL};
    border-right: 1px solid {BORDER};
}}
#RightPanel {{
    border-right: none;
    border-left: 1px solid {BORDER};
}}
#PanelHeader {{
    color: {TEXT_MUTED};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    padding: 14px 14px 8px 14px;
}}

/* ── Scenario list cards ─────────────────────────────────────────────────── */
QListWidget {{
    background-color: transparent;
    border: none;
    padding: 4px 6px;
    outline: none;
}}
QListWidget::item {{
    background-color: {BG_RAISED};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 10px 12px;
    margin: 4px 4px;
    color: {TEXT};
}}
QListWidget::item:hover {{
    border-color: {BORDER};
    background-color: #232a36;
}}
QListWidget::item:selected {{
    border-color: {ACCENT};
    background-color: rgba(56, 189, 248, 0.10);
    color: {TEXT};
}}

/* ── Buttons ─────────────────────────────────────────────────────────────── */
QPushButton {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 14px;
    color: {TEXT};
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: #2b3340;
    border-color: #3b4554;
}}
QPushButton:pressed {{
    background-color: #1a1f29;
}}
QPushButton:disabled {{
    color: {TEXT_DIM};
    background-color: #14181f;
    border-color: #1f242d;
}}
QPushButton#PrimaryButton {{
    background-color: {ACCENT_DEEP};
    border-color: {ACCENT_DEEP};
    color: #0b1018;
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}
QPushButton#PrimaryButton:disabled {{
    background-color: #1b2330;
    border-color: #1b2330;
    color: {TEXT_DIM};
}}
QPushButton#DangerButton {{
    background-color: transparent;
    border-color: {DANGER};
    color: {DANGER};
}}
QPushButton#DangerButton:hover {{
    background-color: rgba(239, 68, 68, 0.12);
}}
QPushButton#DangerButton:disabled {{
    color: {TEXT_DIM};
    border-color: #2a323d;
    background-color: transparent;
}}

/* ── Tabs ────────────────────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: none;
    background-color: transparent;
    top: 0;
}}
QTabBar {{
    background-color: transparent;
    qproperty-drawBase: 0;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {TEXT_MUTED};
    padding: 8px 14px;
    margin: 0 2px;
    border-bottom: 2px solid transparent;
    font-weight: 500;
}}
QTabBar::tab:hover {{
    color: {TEXT};
}}
QTabBar::tab:selected {{
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
}}

/* ── Log view ────────────────────────────────────────────────────────────── */
QPlainTextEdit {{
    background-color: #0a0e13;
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 8px;
    color: {TEXT_MUTED};
    font-family: "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
    font-size: 11px;
    selection-background-color: {ACCENT_DEEP};
}}

/* ── Inputs ──────────────────────────────────────────────────────────────── */
QLineEdit {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    color: {TEXT};
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}

QDialog {{
    background-color: {BG_PANEL};
}}

/* ── Status bar ──────────────────────────────────────────────────────────── */
QStatusBar {{
    background-color: {BG_PANEL};
    border-top: 1px solid {BORDER};
    color: {TEXT_MUTED};
    font-size: 11px;
}}
QStatusBar::item {{ border: none; }}

/* ── Scrollbars ──────────────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: #3b4554;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QSplitter::handle {{
    background-color: {BORDER};
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
QSplitter::handle:vertical {{
    height: 1px;
}}

QMenu {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 14px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: rgba(56, 189, 248, 0.15);
    color: {TEXT};
}}
QMenuBar {{
    background-color: {BG_PANEL};
    color: {TEXT_MUTED};
}}
QMenuBar::item:selected {{
    background-color: {BG_RAISED};
}}

QToolTip {{
    background-color: {BG_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 8px;
}}
"""
