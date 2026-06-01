"""Strike Package Planning Window — full SOF mission planning interface.

Opened from the Strike Package panel. Receives the full /bundle response.
Shows: Overview · Task Org · Assets · Assault Plan · Fire Plan · Comms · Exfil
"""
from __future__ import annotations
import json
from typing import Any

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QScrollArea, QFrame, QTreeWidget,
    QTreeWidgetItem, QTextEdit, QGridLayout, QSizePolicy, QToolBar,
    QSplitter,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont, QKeySequence, QShortcut

from front.utils.mgrs_util import to_mgrs

# ── SOF Element definitions ─────────────────────────────────────────────────

SOF_ELEMENTS = [
    {"key": "TOC",      "name": "TOC / C2",           "icon": "◆", "color": "#c9d1d9",
     "roles": {"ADMIN","BATTLE_CAPTAIN","OPS"}},
    {"key": "ASSAULT",  "name": "ASSAULT ELEMENT",     "icon": "⚔", "color": "#f85149",
     "roles": {"OPERATOR"}},
    {"key": "RECCE",    "name": "SNIPER / RECCE",      "icon": "◎", "color": "#d29922",
     "roles": {"INTEL"}},
    {"key": "FIRE_SPT", "name": "FIRE SUPPORT",        "icon": "🔥","color": "#ff8800",
     "roles": {"FO","CAS"}},
    {"key": "MEDEVAC",  "name": "MEDEVAC",             "icon": "🚁","color": "#3fb950",
     "roles": {"MED"}},
    {"key": "CBRN",     "name": "CBRN",                "icon": "☢", "color": "#d2a8ff",
     "roles": {"CBRN"}},
    {"key": "LOG",      "name": "SUSTAINMENT",         "icon": "📦","color": "#8b949e",
     "roles": {"LOG"}},
    {"key": "QRF",      "name": "QRF",                 "icon": "◈", "color": "#79c0ff",
     "roles": set()},   # remaining OPERATORs
]

STATUS_COLOR = {
    "PLANNING": "#d29922",
    "ACTIVE":   "#3fb950",
    "COMPLETE": "#6e7681",
    "ABORTED":  "#f85149",
}


def _categorize_operators(operators: list[dict]) -> dict[str, list[dict]]:
    """Sort operators into SOF element buckets by role."""
    buckets: dict[str, list[dict]] = {e["key"]: [] for e in SOF_ELEMENTS}
    for op in operators:
        role = (op.get("role") or "OPERATOR").upper()
        placed = False
        for elem in SOF_ELEMENTS:
            if role in elem["roles"]:
                buckets[elem["key"]].append(op)
                placed = True
                break
        if not placed:
            buckets["QRF"].append(op)  # unmatched → QRF
    return buckets


# ── Planning Window ──────────────────────────────────────────────────────────

class StrikePlannerWindow(QMainWindow):
    """Secondary window — full strike package planning interface."""

    overlay_load_requested = pyqtSignal(dict)  # send tactical objects back to main map

    def __init__(self, bundle: dict, parent=None):
        super().__init__(parent)
        self._bundle = bundle
        self._setup_window()
        self._build_ui()
        self._populate()

    # ── Window setup ────────────────────────────────────────────────────────

    def _setup_window(self):
        name   = self._bundle.get("name", "UNKNOWN")
        status = self._bundle.get("status", "PLANNING")
        self.setWindowTitle(f"◆ STRIKE PACKAGE  —  {name.upper()}  [{status}]")
        self.resize(1100, 760)
        self.setMinimumSize(900, 640)
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#0d1117; color:#c9d1d9;
                font-family:'Courier New',Consolas,monospace; font-size:11px; }
            QTabBar::tab { background:#161b22; border:none; border-right:1px solid #21262d;
                color:#6e7681; font-size:9px; font-weight:700; letter-spacing:1.5px;
                padding:7px 14px; text-transform:uppercase; min-width:80px; }
            QTabBar::tab:selected { background:#0d1117; color:#79c0ff;
                border-bottom:2px solid #1f6feb; }
            QTabBar::tab:hover:!selected { background:#21262d; color:#c9d1d9; }
            QTabWidget::pane { border:none; background:#0d1117; }
            QTreeWidget { background:#0d1117; alternate-background-color:#0f141a;
                border:none; color:#c9d1d9; }
            QTreeWidget::item { padding:3px 6px; border-bottom:1px solid #161b22; }
            QTreeWidget::item:selected { background:#1c2d3f; color:#79c0ff; }
            QScrollBar:vertical { background:#0d1117; width:7px; border:none; }
            QScrollBar::handle:vertical { background:#30363d; border-radius:3px; min-height:20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
            QTextEdit { background:#161b22; border:1px solid #30363d; color:#c9d1d9; }
            QFrame#sep { background:#21262d; max-height:1px; }
        """)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self.close)

    # ── Main layout ─────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Status bar ────────────────────────────────────────────────────
        status     = self._bundle.get("status", "PLANNING")
        color      = STATUS_COLOR.get(status, "#8b949e")
        status_bar = QFrame()
        status_bar.setFixedHeight(44)
        status_bar.setStyleSheet(f"background:#161b22;border-bottom:2px solid {color};")
        sb_row = QHBoxLayout(status_bar)
        sb_row.setContentsMargins(14, 0, 14, 0)

        name_lbl = QLabel(self._bundle.get("name", "?").upper())
        name_lbl.setStyleSheet(
            f"color:{color};font-size:13px;font-weight:700;letter-spacing:2px;")
        sb_row.addWidget(name_lbl)
        sb_row.addStretch()

        status_lbl = QLabel(f"● {status}")
        status_lbl.setStyleSheet(f"color:{color};font-size:10px;font-weight:700;")
        sb_row.addWidget(status_lbl)

        overlay_btn = QPushButton("⊕  PUSH TO MAP")
        overlay_btn.setStyleSheet(
            "QPushButton{background:#1a3020;border:1px solid #3fb950;"
            "color:#3fb950;font-size:9px;font-weight:700;padding:5px 12px;border-radius:2px;}"
            "QPushButton:hover{background:#3fb950;color:#0d1117;}"
        )
        overlay_btn.clicked.connect(self._push_overlay)
        sb_row.addWidget(overlay_btn)

        # ── Tabs ──────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)

        central = QWidget()
        cv = QVBoxLayout(central)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(status_bar)
        cv.addWidget(self._tabs, 1)
        self.setCentralWidget(central)

    # ── Tab builders ────────────────────────────────────────────────────────

    def _populate(self):
        b = self._bundle
        self._tabs.addTab(self._build_overview(b),     "OVERVIEW")
        self._tabs.addTab(self._build_task_org(b),     "TASK ORG")
        self._tabs.addTab(self._build_assets(b),       "ASSETS")
        self._tabs.addTab(self._build_assault_plan(b), "ASSAULT PLAN")
        self._tabs.addTab(self._build_fire_plan(b),    "FIRE PLAN")
        self._tabs.addTab(self._build_comms(b),        "COMMS")
        self._tabs.addTab(self._build_exfil(b),        "EXFIL")

    # ── OVERVIEW ────────────────────────────────────────────────────────────

    def _build_overview(self, b: dict) -> QWidget:
        scroll = _scroll()
        lay = _vlayout(scroll.widget())

        lay.addWidget(_section_header("MISSION SUMMARY"))

        grid = QGridLayout(); grid.setSpacing(8); grid.setColumnStretch(1, 1)
        rows = [
            ("NAME",        b.get("name", "—")),
            ("STATUS",      b.get("status", "—")),
            ("MISSION",     b.get("mission_name") or f"ID {b.get('mission_id','—')}"),
            ("CREATED BY",  str(b.get("created_by", "—"))),
        ]
        tlat, tlon = b.get("target_lat"), b.get("target_lon")
        if tlat and tlon:
            rows.append(("TARGET GRID", to_mgrs(tlat, tlon)))

        for i, (k, v) in enumerate(rows):
            grid.addWidget(_key(k), i, 0)
            grid.addWidget(_val(v), i, 1)
        lay.addLayout(grid)

        tdesc = b.get("target_description")
        if tdesc:
            lay.addWidget(_section_header("TARGET DESCRIPTION"))
            lay.addWidget(_block(tdesc))

        # Stats
        lay.addWidget(_section_header("PACKAGE CONTENTS"))
        stats_grid = QGridLayout(); stats_grid.setSpacing(6)
        ops     = b.get("operator_ids", [])
        assets  = b.get("assets", {})
        stats   = [
            ("OPERATORS",   len(ops)),
            ("TACT OBJECTS",len(b.get("tactical_object_ids", []))),
            ("FIRE MISSIONS",len(b.get("fire_mission_ids", []))),
            ("REPORTS",     len(b.get("report_ids", []))),
            ("DRONES",      len(assets.get("drones", []))),
            ("AIR SUPPORT", len(assets.get("air_support", []))),
            ("SNIPERS",     len(assets.get("sniper_overwatch", []))),
            ("EW ASSETS",   len(assets.get("electronic_warfare", []))),
        ]
        for i, (k, v) in enumerate(stats):
            card = _stat_card(k, str(v))
            stats_grid.addWidget(card, i // 4, i % 4)
        lay.addLayout(stats_grid)

        lay.addStretch()
        return scroll

    # ── TASK ORG ────────────────────────────────────────────────────────────

    def _build_task_org(self, b: dict) -> QWidget:
        scroll = _scroll()
        lay = _vlayout(scroll.widget())
        lay.addWidget(_section_header(
            f"TASK ORGANIZATION  —  {len(b.get('operator_ids', []))} OPERATORS"))

        operators = b.get("_operators_expanded", [])
        if not operators and b.get("operator_ids"):
            operators = [{"id": oid, "callsign": f"OP-{oid}", "role": "OPERATOR"}
                         for oid in b.get("operator_ids", [])]

        buckets = _categorize_operators(operators)

        for elem in SOF_ELEMENTS:
            key  = elem["key"]
            ops  = buckets.get(key, [])
            if not ops:
                continue
            elem_lbl = QLabel(f"  {elem['icon']}  {elem['name']}  ({len(ops)})")
            elem_lbl.setStyleSheet(
                f"color:{elem['color']};font-size:11px;font-weight:700;"
                f"letter-spacing:1px;padding:6px 0 2px;border-bottom:1px solid #21262d;"
            )
            lay.addWidget(elem_lbl)

            for op in ops:
                cs   = op.get("callsign", "?")
                rank = op.get("rank", "")
                role = op.get("role", "OPERATOR")
                online = "●" if op.get("online") or op.get("status")=="ONLINE" else "○"
                clr  = "#3fb950" if online == "●" else "#6e7681"
                row  = QHBoxLayout(); row.setContentsMargins(16, 1, 4, 1)
                lbl  = QLabel(f"{online}  {rank}  {cs}".strip())
                lbl.setStyleSheet(f"color:{clr};font-size:10px;")
                role_lbl = QLabel(f"[{role}]")
                role_lbl.setStyleSheet("color:#484f58;font-size:9px;")
                role_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                row.addWidget(lbl, 1); row.addWidget(role_lbl)
                container = QWidget(); container.setLayout(row)
                lay.addWidget(container)

        lay.addStretch()
        return scroll

    # ── ASSETS ──────────────────────────────────────────────────────────────

    def _build_assets(self, b: dict) -> QWidget:
        assets = b.get("assets", {})
        scroll = _scroll()
        lay = _vlayout(scroll.widget())

        # Drones
        drones = assets.get("drones", [])
        if drones:
            lay.addWidget(_section_header(f"UAV / DRONES  ({len(drones)})"))
            for d in drones:
                lay.addWidget(_asset_card(
                    d.get("platform", "?"), d.get("callsign", ""),
                    [("FEED", d.get("feed_url") or "—"),
                     ("NOTES", d.get("notes") or "—")],
                    "#d2a8ff"
                ))

        # ISR
        isr_list = assets.get("isr", [])
        if isr_list:
            lay.addWidget(_section_header(f"ISR  ({len(isr_list)})"))
            for s in isr_list:
                lay.addWidget(_asset_card(
                    s.get("sensor", "?"), s.get("platform", ""),
                    [("PRIORITY", s.get("collection_priority", "?")),
                     ("NOTES", s.get("notes") or "—")],
                    "#79c0ff"
                ))

        # Air Support
        air = assets.get("air_support", [])
        if air:
            lay.addWidget(_section_header(f"AIR SUPPORT  ({len(air)})"))
            for a in air:
                sta = a.get("station_time_min", 0)
                lay.addWidget(_asset_card(
                    a.get("aircraft", "?"), a.get("callsign", ""),
                    [("ORDNANCE", a.get("ordnance") or "—"),
                     ("ON STATION", f"{sta} min"),
                     ("FREQ", a.get("frequency") or "—"),
                     ("NOTES", a.get("notes") or "—")],
                    "#f85149"
                ))

        # Sniper Overwatch
        snipers = assets.get("sniper_overwatch", [])
        if snipers:
            lay.addWidget(_section_header(f"SNIPER OVERWATCH  ({len(snipers)})"))
            for s in snipers:
                pos = ""
                if s.get("position_lat") and s.get("position_lon"):
                    pos = to_mgrs(s["position_lat"], s["position_lon"])
                lay.addWidget(_asset_card(
                    s.get("callsign", "SNIPER"), "",
                    [("POSITION", pos or "—"),
                     ("SECTOR", s.get("sector_of_fire") or "—"),
                     ("CRITERIA", s.get("engagement_criteria") or "—")],
                    "#d29922"
                ))

        # EW
        ew_list = assets.get("electronic_warfare", [])
        if ew_list:
            lay.addWidget(_section_header(f"ELECTRONIC WARFARE  ({len(ew_list)})"))
            for e in ew_list:
                lay.addWidget(_asset_card(
                    e.get("system", "?"), e.get("callsign", ""),
                    [("BANDS", e.get("frequency_bands") or "—"),
                     ("OBJECTIVE", e.get("objective") or "—"),
                     ("NOTES", e.get("notes") or "—")],
                    "#ff8800"
                ))

        if not any([drones, isr_list, air, snipers, ew_list]):
            lay.addWidget(QLabel("No assets defined",
                styleSheet="color:#484f58;font-size:10px;padding:20px;"),
                alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addStretch()
        return scroll

    # ── ASSAULT PLAN ────────────────────────────────────────────────────────

    def _build_assault_plan(self, b: dict) -> QWidget:
        plan = (b.get("assets") or {}).get("assault_plan") or {}
        scroll = _scroll()
        lay = _vlayout(scroll.widget())

        phases = plan.get("phases", [])
        if phases:
            lay.addWidget(_section_header(f"PHASES  ({len(phases)})"))
            for i, ph in enumerate(phases, 1):
                ph_lbl = QLabel(f"  PHASE {i}  —  {ph.get('name','?').upper()}")
                ph_lbl.setStyleSheet(
                    "color:#79c0ff;font-size:11px;font-weight:700;padding:5px 0 2px;")
                lay.addWidget(ph_lbl)
                desc = ph.get("description")
                if desc:
                    lay.addWidget(_block(desc))
                actions = ph.get("actions")
                if actions:
                    lay.addWidget(_key("ACTIONS"))
                    lay.addWidget(_block(actions))

        breach = plan.get("breach_points", [])
        if breach:
            lay.addWidget(_section_header("BREACH POINTS"))
            for bp in breach:
                lay.addWidget(_val(f"  ▸  {bp}"))

        aoo = plan.get("actions_on_objective")
        if aoo:
            lay.addWidget(_section_header("ACTIONS ON OBJECTIVE"))
            lay.addWidget(_block(aoo))

        consol = plan.get("consolidation")
        if consol:
            lay.addWidget(_section_header("CONSOLIDATION"))
            lay.addWidget(_block(consol))

        if not phases and not breach and not aoo:
            lay.addWidget(QLabel("No assault plan defined",
                styleSheet="color:#484f58;font-size:10px;padding:20px;"),
                alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addStretch()
        return scroll

    # ── FIRE PLAN ───────────────────────────────────────────────────────────

    def _build_fire_plan(self, b: dict) -> QWidget:
        scroll = _scroll()
        lay = _vlayout(scroll.widget())

        fire_missions = b.get("_fire_missions_expanded", [])
        if not fire_missions:
            fm_ids = b.get("fire_mission_ids", [])
            if fm_ids:
                fire_missions = [{"id": fid, "mission_type": "PLANNED",
                                  "status": "PENDING"} for fid in fm_ids]

        if fire_missions:
            lay.addWidget(_section_header(f"FIRE MISSIONS  ({len(fire_missions)})"))
            tree = QTreeWidget()
            tree.setHeaderLabels(["TYPE", "AMMO", "GRID", "STATUS"])
            tree.setColumnWidth(0, 160); tree.setColumnWidth(1, 120)
            tree.setColumnWidth(2, 160); tree.setColumnWidth(3, 100)
            tree.setAlternatingRowColors(True)
            for fm in fire_missions:
                lat = fm.get("latitude"); lon = fm.get("longitude")
                grid = to_mgrs(lat, lon) if lat and lon else "—"
                it = QTreeWidgetItem([
                    fm.get("mission_type", "?"),
                    f"{fm.get('ammunition','?')} × {fm.get('quantity','?')}",
                    grid,
                    fm.get("status", "?"),
                ])
                c = "#3fb950" if fm.get("status")=="COMPLETED" else \
                    "#d29922" if fm.get("status")=="PENDING" else "#c9d1d9"
                it.setForeground(3, QBrush(QColor(c)))
                tree.addTopLevelItem(it)
            lay.addWidget(tree)
        else:
            lay.addWidget(QLabel("No fire missions linked",
                styleSheet="color:#484f58;font-size:10px;padding:20px;"),
                alignment=Qt.AlignmentFlag.AlignCenter)

        lay.addStretch()
        return scroll

    # ── COMMS ───────────────────────────────────────────────────────────────

    def _build_comms(self, b: dict) -> QWidget:
        comms = (b.get("assets") or {}).get("comms") or {}
        scroll = _scroll()
        lay = _vlayout(scroll.widget())
        lay.addWidget(_section_header("COMMUNICATIONS PLAN"))

        grid = QGridLayout(); grid.setSpacing(8); grid.setColumnStretch(1, 1)
        rows = [
            ("PRIMARY FREQ",   comms.get("primary_freq")   or "—"),
            ("ALTERNATE FREQ", comms.get("alternate_freq") or "—"),
            ("WAVEFORM",       comms.get("waveform")       or "—"),
        ]
        for i, (k, v) in enumerate(rows):
            grid.addWidget(_key(k), i, 0); grid.addWidget(_val(v), i, 1)
        lay.addLayout(grid)

        pace = comms.get("pace_plan")
        if pace:
            lay.addWidget(_section_header("PACE PLAN"))
            lay.addWidget(_block(pace))

        lay.addStretch()
        return scroll

    # ── EXFIL ───────────────────────────────────────────────────────────────

    def _build_exfil(self, b: dict) -> QWidget:
        routes = (b.get("assets") or {}).get("exfil_routes") or []
        scroll = _scroll()
        lay = _vlayout(scroll.widget())
        lay.addWidget(_section_header(f"EXFILTRATION ROUTES  ({len(routes)})"))

        if routes:
            for r in routes:
                rtype = r.get("name", "ROUTE").upper()
                color = {"PRIMARY":"#3fb950","ALTERNATE":"#d29922","EMERGENCY":"#f85149"}.get(rtype,"#c9d1d9")
                hdr = QLabel(f"  ▸  {rtype}  [{r.get('type','GROUND')}]")
                hdr.setStyleSheet(f"color:{color};font-size:11px;font-weight:700;padding:5px 0 2px;")
                lay.addWidget(hdr)
                desc = r.get("description")
                if desc:
                    lay.addWidget(_block(desc))
                toid = r.get("tactical_object_id")
                if toid:
                    lay.addWidget(_val(f"  Linked map object: #{toid}"))
        else:
            lay.addWidget(QLabel("No exfil routes defined",
                styleSheet="color:#484f58;font-size:10px;padding:20px;"),
                alignment=Qt.AlignmentFlag.AlignCenter)

        lay.addStretch()
        return scroll

    # ── Actions ─────────────────────────────────────────────────────────────

    def _push_overlay(self):
        self.overlay_load_requested.emit(self._bundle)


# ── Widget helpers ───────────────────────────────────────────────────────────

def _scroll() -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setStyleSheet("QScrollArea{background:#0d1117;}")
    w = QWidget(); w.setStyleSheet("background:#0d1117;")
    sa.setWidget(w)
    return sa

def _vlayout(parent: QWidget) -> QVBoxLayout:
    lay = QVBoxLayout(parent)
    lay.setContentsMargins(16, 12, 16, 12)
    lay.setSpacing(6)
    return lay

def _section_header(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(
        "color:#8b949e;font-size:9px;font-weight:700;letter-spacing:2px;"
        "padding:10px 0 4px;border-bottom:1px solid #21262d;"
    )
    return l

def _key(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet("color:#6e7681;font-size:9px;font-weight:700;letter-spacing:1px;min-width:140px;")
    return l

def _val(text: str) -> QLabel:
    l = QLabel(str(text))
    l.setStyleSheet("color:#c9d1d9;font-size:10px;")
    l.setWordWrap(True)
    return l

def _block(text: str) -> QLabel:
    l = QLabel(str(text))
    l.setStyleSheet(
        "color:#c9d1d9;font-size:10px;background:#161b22;"
        "border:1px solid #30363d;border-radius:2px;padding:8px;line-height:1.5;"
    )
    l.setWordWrap(True)
    return l

def _asset_card(title: str, subtitle: str, fields: list[tuple[str, str]], color: str) -> QFrame:
    card = QFrame()
    card.setStyleSheet(
        f"QFrame{{background:#161b22;border:1px solid #30363d;"
        f"border-left:3px solid {color};border-radius:2px;margin:2px 0;}}"
    )
    lay = QVBoxLayout(card); lay.setContentsMargins(10, 7, 10, 7); lay.setSpacing(4)
    hdr = QHBoxLayout()
    ttl = QLabel(title.upper())
    ttl.setStyleSheet(f"color:{color};font-size:11px;font-weight:700;")
    hdr.addWidget(ttl)
    if subtitle:
        sub = QLabel(f"·  {subtitle}")
        sub.setStyleSheet("color:#8b949e;font-size:10px;")
        hdr.addWidget(sub)
    hdr.addStretch()
    lay.addLayout(hdr)
    for k, v in fields:
        if v and v != "—":
            row = QHBoxLayout(); row.setSpacing(8)
            row.addWidget(_key(k)); row.addWidget(_val(v), 1)
            lay.addLayout(row)
    return card

def _stat_card(label: str, value: str) -> QFrame:
    card = QFrame()
    card.setStyleSheet(
        "QFrame{background:#161b22;border:1px solid #30363d;"
        "border-radius:3px;margin:2px;}"
    )
    lay = QVBoxLayout(card); lay.setContentsMargins(10, 8, 10, 8); lay.setSpacing(2)
    val_lbl = QLabel(value)
    val_lbl.setStyleSheet(
        "color:#79c0ff;font-size:20px;font-weight:700;qproperty-alignment:AlignCenter;")
    val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    key_lbl = QLabel(label)
    key_lbl.setStyleSheet(
        "color:#6e7681;font-size:8px;font-weight:700;letter-spacing:1.5px;"
        "qproperty-alignment:AlignCenter;")
    key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(val_lbl); lay.addWidget(key_lbl)
    return card
