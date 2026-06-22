"""SimFrame — main wxPython simulator window."""

from __future__ import annotations

import dataclasses
import json
import queue
import random
import threading
from typing import Callable

import wx
import wx.stc as stc

from .builder import CotXmlBuilder
from .client import BackendClient, WsMonitor
from .domain import CotEntry
from .messages import (
    MsgAutoStopped,
    MsgAutoTrigger,
    MsgLoginErr,
    MsgLoginOk,
    MsgSendErr,
    MsgSendOk,
    MsgWsBtn,
    MsgWsRaw,
    MsgWsStatus,
    QueueMsg,
)
from .registry import registry
from .strategies import AutoSend, BurstSend, OnceSend
from .theme import (
    C_ACCENT,
    C_BG,
    C_CARD,
    C_DIM,
    C_ERR,
    C_FG,
    C_INFO,
    C_OK,
    C_PANEL,
    C_WARN,
    C_XML,
    CAT_COLOUR,
    WS_STATUS_COLOUR,
    apply_default_font,
    bold,
    mono,
    ts,
)
from .widgets import (
    LOG_STYLE_MAP,
    ST_CHANNEL,
    ST_DATA,
    ST_ERR,
    ST_OK,
    ST_SYS,
    ST_TS,
    ST_XML,
    log_append,
    make_btn,
    make_log,
)


class SimFrame(wx.Frame):
    """Main simulator window.

    Owns a ``CotXmlBuilder``, a ``WsMonitor`` (when connected), and an
    ``AutoSend`` instance (when running).  All cross-thread GUI updates travel
    through a ``queue.Queue`` polled by a ``wx.Timer`` at 40 ms intervals
    (Observer pattern).  Queue messages are dispatched via a typed handler map
    rather than an if/elif chain (Command-map pattern).
    """

    def __init__(self, backend_url: str) -> None:
        super().__init__(
            None,
            title="Arrow CoT Simulator",
            size=(1380, 860),
            style=wx.DEFAULT_FRAME_STYLE,
        )
        self._default_url = backend_url.rstrip("/")
        self._builder = CotXmlBuilder()
        self._token: str | None = None
        self._selected: CotEntry | None = None
        self._visible: list[CotEntry] = []
        self._auto_send: AutoSend | None = None
        self._ws_monitor: WsMonitor | None = None
        self._msg_q: queue.Queue[QueueMsg] = queue.Queue()
        self._sent = self._rx = self._errs = 0

        self.SetBackgroundColour(C_BG)
        self._build_ui()
        apply_default_font(self)  # bump every child font for legibility
        self.Layout()
        self._setup_handlers()

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._poll_queue, self._timer)
        self._timer.Start(40)

        self.Centre()
        self.Show()

    # ── Command-map ───────────────────────────────────────────────────────────

    def _setup_handlers(self) -> None:
        self._handlers: dict[type, Callable] = {
            MsgLoginOk: self._h_login_ok,
            MsgLoginErr: self._h_login_err,
            MsgSendOk: self._h_send_ok,
            MsgSendErr: self._h_send_err,
            MsgAutoTrigger: self._h_auto_trigger,
            MsgAutoStopped: self._h_auto_stopped,
            MsgWsStatus: self._h_ws_status,
            MsgWsBtn: self._h_ws_btn,
            MsgWsRaw: self._h_ws_raw,
        }

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self._build_topbar(), 0, wx.EXPAND | wx.ALL, 4)
        root.Add(self._build_main(), 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        root.Add(
            self._build_statusbar(), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 2
        )
        self.SetSizer(root)

    # ── Top bar ───────────────────────────────────────────────────────────────

    def _build_topbar(self) -> wx.Panel:
        bar = wx.Panel(self)
        bar.SetBackgroundColour(C_PANEL)
        h = wx.BoxSizer(wx.HORIZONTAL)

        def lbl(text: str, fg: wx.Colour = C_FG, b: bool = False) -> wx.StaticText:
            w = wx.StaticText(bar, label=text)
            w.SetForegroundColour(fg)
            w.SetFont(bold(10) if b else mono(10))
            w.SetBackgroundColour(C_PANEL)
            return w

        def entry(val: str, width: int = 160, password: bool = False) -> wx.TextCtrl:
            style = (
                (wx.TE_PASSWORD | wx.BORDER_SIMPLE) if password else wx.BORDER_SIMPLE
            )
            w = wx.TextCtrl(bar, value=val, style=style, size=(width, -1))
            w.SetBackgroundColour(C_CARD)
            w.SetForegroundColour(C_FG)
            w.SetFont(mono(9))
            return w

        def btn(text: str, handler: Callable, bg: wx.Colour = C_ACCENT):
            return make_btn(bar, text, handler, bg=bg)

        h.Add(
            lbl("▶ ARROW CoT SIMULATOR", C_ACCENT, b=True),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT,
            8,
        )
        h.Add(
            wx.StaticLine(bar, style=wx.LI_VERTICAL),
            0,
            wx.EXPAND | wx.TOP | wx.BOTTOM,
            4,
        )

        h.Add(lbl("Backend:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        self._url_ctrl = entry(self._default_url, 200)
        h.Add(self._url_ctrl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        h.Add(lbl("Callsign:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        self._cs_ctrl = entry("benoit", 90)
        h.Add(self._cs_ctrl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        h.Add(lbl("Password:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        self._pw_ctrl = entry("ranger14", 90, password=True)
        h.Add(self._pw_ctrl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        h.Add(
            btn("LOGIN", self._on_login, C_INFO),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            8,
        )
        h.Add(
            wx.StaticLine(bar, style=wx.LI_VERTICAL),
            0,
            wx.EXPAND | wx.TOP | wx.BOTTOM | wx.LEFT | wx.RIGHT,
            6,
        )

        h.Add(lbl("Token:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._token_lbl = lbl("— not authenticated —", C_WARN)
        h.Add(self._token_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)

        h.AddStretchSpacer()

        self._ws_status_lbl = lbl("WS: OFF", C_ERR, b=True)
        h.Add(self._ws_status_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self._ws_btn = btn("WS CONNECT", self._on_toggle_ws, wx.Colour(136, 102, 34))
        h.Add(self._ws_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        bar.SetSizer(h)
        bar.SetMinSize((-1, 44))
        return bar

    # ── Main splitter ─────────────────────────────────────────────────────────

    def _build_main(self) -> wx.SplitterWindow:
        sp = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        sp.SetBackgroundColour(C_BG)
        sp.SplitVertically(self._build_left(sp), self._build_right(sp), 280)
        sp.SetMinimumPaneSize(200)
        sp.SetSashGravity(0.0)
        return sp

    # ── Left column ───────────────────────────────────────────────────────────

    def _build_left(self, parent: wx.Window) -> wx.Panel:
        panel = wx.Panel(parent)
        panel.SetBackgroundColour(C_BG)
        v = wx.BoxSizer(wx.VERTICAL)
        v.Add(self._build_library(panel), 1, wx.EXPAND | wx.BOTTOM, 4)
        v.Add(self._build_send_controls(panel), 0, wx.EXPAND)
        panel.SetSizer(v)
        return panel

    def _build_library(self, parent: wx.Window) -> wx.Panel:
        panel = wx.Panel(parent)
        panel.SetBackgroundColour(C_PANEL)
        v = wx.BoxSizer(wx.VERTICAL)

        hdr = wx.StaticText(panel, label=" ◉ COT LIBRARY")
        hdr.SetForegroundColour(C_ACCENT)
        hdr.SetFont(bold(9))
        hdr.SetBackgroundColour(C_PANEL)
        v.Add(hdr, 0, wx.EXPAND | wx.ALL, 4)
        v.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 2)

        row = wx.BoxSizer(wx.HORIZONTAL)
        cat_lbl = wx.StaticText(panel, label="Category:")
        cat_lbl.SetForegroundColour(C_DIM)
        cat_lbl.SetFont(mono(9))
        cat_lbl.SetBackgroundColour(C_PANEL)
        row.Add(cat_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 4)

        self._cat_choice = wx.Choice(panel, choices=["All"] + registry.categories())
        self._cat_choice.SetSelection(0)
        self._cat_choice.SetFont(mono(9))
        self._cat_choice.Bind(wx.EVT_CHOICE, self._on_filter_change)
        row.Add(self._cat_choice, 1, wx.EXPAND | wx.RIGHT, 4)
        v.Add(row, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 4)

        self._lib_list = wx.ListCtrl(
            panel,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_NO_HEADER | wx.BORDER_NONE,
        )
        self._lib_list.SetBackgroundColour(C_PANEL)
        self._lib_list.SetForegroundColour(C_FG)
        self._lib_list.SetFont(mono(9))
        self._lib_list.InsertColumn(0, "Message", width=240)
        self._lib_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_lib_select)
        v.Add(self._lib_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 2)

        panel.SetSizer(v)
        self._refresh_library()
        return panel

    def _build_send_controls(self, parent: wx.Window) -> wx.Panel:
        panel = wx.Panel(parent)
        panel.SetBackgroundColour(C_PANEL)
        v = wx.BoxSizer(wx.VERTICAL)

        hdr = wx.StaticText(panel, label=" ◈ SEND CONTROLS")
        hdr.SetForegroundColour(C_ACCENT)
        hdr.SetFont(bold(9))
        hdr.SetBackgroundColour(C_PANEL)
        v.Add(hdr, 0, wx.EXPAND | wx.ALL, 4)
        v.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 2)

        def btn(label: str, handler: Callable, bg: wx.Colour = C_ACCENT):
            return make_btn(panel, label, handler, bg=bg)

        # Once / Burst row
        row1 = wx.BoxSizer(wx.HORIZONTAL)
        row1.Add(btn("SEND ONCE", self._on_send_once), 0, wx.RIGHT, 4)
        row1.Add(
            btn("BURST", self._on_send_burst, wx.Colour(136, 102, 34)), 0, wx.RIGHT, 4
        )
        self._burst_spin = wx.SpinCtrl(panel, value="5", min=1, max=100, size=(54, -1))
        self._burst_spin.SetFont(mono(9))
        row1.Add(self._burst_spin, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        m_lbl = wx.StaticText(panel, label="msgs")
        m_lbl.SetForegroundColour(C_DIM)
        m_lbl.SetFont(mono(8))
        m_lbl.SetBackgroundColour(C_PANEL)
        row1.Add(m_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        v.Add(row1, 0, wx.ALL, 4)

        v.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)

        # Auto row
        row2 = wx.BoxSizer(wx.HORIZONTAL)
        row2.Add(btn("AUTO START", self._on_start_auto), 0, wx.RIGHT, 4)
        row2.Add(btn("STOP", self._on_stop_auto, C_ERR), 0, wx.RIGHT, 6)
        self._auto_interval = wx.SpinCtrlDouble(
            panel, value="3.0", min=0.5, max=60.0, inc=0.5, size=(62, -1)
        )
        self._auto_interval.SetFont(mono(9))
        row2.Add(self._auto_interval, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        s_lbl = wx.StaticText(panel, label="s")
        s_lbl.SetForegroundColour(C_DIM)
        s_lbl.SetFont(mono(8))
        s_lbl.SetBackgroundColour(C_PANEL)
        row2.Add(s_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        v.Add(row2, 0, wx.ALL, 4)

        self._auto_lbl = wx.StaticText(panel, label="Auto: OFF")
        self._auto_lbl.SetForegroundColour(C_ERR)
        self._auto_lbl.SetFont(bold(9))
        self._auto_lbl.SetBackgroundColour(C_PANEL)
        v.Add(self._auto_lbl, 0, wx.LEFT | wx.BOTTOM, 6)

        v.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)
        v.Add(
            btn("RANDOMISE POSITION", self._on_randomise, wx.Colour(136, 102, 34)),
            0,
            wx.EXPAND | wx.ALL,
            4,
        )

        panel.SetSizer(v)
        return panel

    # ── Right column ──────────────────────────────────────────────────────────

    def _build_right(self, parent: wx.Window) -> wx.Panel:
        panel = wx.Panel(parent)
        panel.SetBackgroundColour(C_BG)
        v = wx.BoxSizer(wx.VERTICAL)
        v.Add(self._build_edit_pane(panel), 0, wx.EXPAND | wx.BOTTOM, 4)
        v.Add(self._build_io_panes(panel), 1, wx.EXPAND)
        panel.SetSizer(v)
        return panel

    def _build_edit_pane(self, parent: wx.Window) -> wx.Panel:
        panel = wx.Panel(parent)
        panel.SetBackgroundColour(C_PANEL)
        outer = wx.BoxSizer(wx.VERTICAL)

        hdr = wx.StaticText(panel, label=" ◎ EDIT ENTRY")
        hdr.SetForegroundColour(C_ACCENT)
        hdr.SetFont(bold(9))
        hdr.SetBackgroundColour(C_PANEL)
        outer.Add(hdr, 0, wx.EXPAND | wx.ALL, 4)
        outer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 2)

        h = wx.BoxSizer(wx.HORIZONTAL)

        # Field grid
        grid = wx.FlexGridSizer(rows=5, cols=4, hgap=8, vgap=4)
        grid.AddGrowableCol(1)
        grid.AddGrowableCol(3)

        def dim_lbl(text: str) -> wx.StaticText:
            w = wx.StaticText(panel, label=text)
            w.SetForegroundColour(C_DIM)
            w.SetFont(mono(8))
            w.SetBackgroundColour(C_PANEL)
            return w

        def field(attr: str, width: int = 130) -> wx.TextCtrl:
            e = wx.TextCtrl(panel, size=(width, -1), style=wx.BORDER_SIMPLE)
            e.SetBackgroundColour(C_CARD)
            e.SetForegroundColour(C_FG)
            e.SetFont(mono(9))
            setattr(self, attr, e)
            e.Bind(wx.EVT_TEXT, self._on_edit_change)
            return e

        for ll, la, rl, ra in [
            ("UID", "_e_uid", "CoT Type", "_e_type"),
            ("Callsign", "_e_callsign", "Team", "_e_team"),
            ("Latitude", "_e_lat", "Longitude", "_e_lon"),
            ("HAE (m)", "_e_hae", "Role", "_e_role"),
            ("Speed m/s", "_e_speed", "Course °", "_e_course"),
        ]:
            grid.Add(dim_lbl(ll), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(field(la), 1, wx.EXPAND)
            grid.Add(dim_lbl(rl), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(field(ra), 1, wx.EXPAND)

        h.Add(grid, 0, wx.ALL, 6)
        h.Add(
            wx.StaticLine(panel, style=wx.LI_VERTICAL),
            0,
            wx.EXPAND | wx.TOP | wx.BOTTOM,
            4,
        )

        # XML preview
        pv = wx.BoxSizer(wx.VERTICAL)
        pv_lbl = wx.StaticText(panel, label="XML Preview")
        pv_lbl.SetForegroundColour(C_ACCENT)
        pv_lbl.SetFont(bold(9))
        pv_lbl.SetBackgroundColour(C_PANEL)
        pv.Add(pv_lbl, 0, wx.BOTTOM | wx.LEFT, 2)

        self._preview = stc.StyledTextCtrl(panel, size=(-1, 138), style=wx.BORDER_NONE)
        self._preview.SetReadOnly(True)
        self._preview.SetMarginWidth(0, 0)
        self._preview.SetMarginWidth(1, 0)
        self._preview.StyleSetForeground(stc.STC_STYLE_DEFAULT, C_XML)
        self._preview.StyleSetBackground(stc.STC_STYLE_DEFAULT, C_PANEL)
        self._preview.StyleSetFont(stc.STC_STYLE_DEFAULT, mono(9))
        self._preview.StyleClearAll()
        self._preview.SetCaretForeground(C_ACCENT)
        pv.Add(self._preview, 1, wx.EXPAND)

        h.Add(pv, 1, wx.EXPAND | wx.ALL, 6)
        outer.Add(h, 1, wx.EXPAND)
        panel.SetSizer(outer)
        return panel

    def _build_io_panes(self, parent: wx.Window) -> wx.SplitterWindow:
        sp = wx.SplitterWindow(parent, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        sp.SetBackgroundColour(C_BG)
        sp.SplitVertically(
            self._build_log_pane(sp, "out"), self._build_log_pane(sp, "in")
        )
        sp.SetSashGravity(0.5)
        sp.SetMinimumPaneSize(200)
        return sp

    def _build_log_pane(self, parent: wx.Window, side: str) -> wx.Panel:
        is_out = side == "out"
        log_attr = "_out_log" if is_out else "_in_log"
        panel = wx.Panel(parent)
        panel.SetBackgroundColour(C_PANEL)
        v = wx.BoxSizer(wx.VERTICAL)

        title = (
            "◄ OUTGOING  (sent CoT + HTTP responses)"
            if is_out
            else "► INCOMING  (WebSocket / WH feed)"
        )
        hdr = wx.BoxSizer(wx.HORIZONTAL)
        ttl = wx.StaticText(panel, label=f" {title}")
        ttl.SetForegroundColour(C_ACCENT)
        ttl.SetFont(bold(9))
        ttl.SetBackgroundColour(C_PANEL)
        hdr.Add(ttl, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        clr = wx.Button(panel, label="CLEAR", size=(-1, 22))
        clr.SetBackgroundColour(C_ERR)
        clr.SetForegroundColour(wx.WHITE)
        clr.SetFont(bold(8))
        clr.Bind(wx.EVT_BUTTON, lambda _e: self._clear_log(getattr(self, log_attr)))
        hdr.Add(clr, 0, wx.ALL, 2)
        v.Add(hdr, 0, wx.EXPAND | wx.TOP, 2)
        v.Add(wx.StaticLine(panel), 0, wx.EXPAND)

        fg = wx.Colour(136, 220, 136) if is_out else wx.Colour(136, 136, 255)
        log = make_log(panel, fg)
        setattr(self, log_attr, log)
        v.Add(log, 1, wx.EXPAND)

        panel.SetSizer(v)
        return panel

    def _build_statusbar(self) -> wx.Panel:
        panel = wx.Panel(self)
        panel.SetBackgroundColour(C_PANEL)
        h = wx.BoxSizer(wx.HORIZONTAL)

        self._status_lbl = wx.StaticText(
            panel, label="Ready — login then select a message from the library."
        )
        self._status_lbl.SetForegroundColour(C_DIM)
        self._status_lbl.SetFont(mono(9))
        self._status_lbl.SetBackgroundColour(C_PANEL)
        h.Add(self._status_lbl, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)

        self._counter_lbl = wx.StaticText(panel, label="Sent: 0  Rx: 0  Errors: 0")
        self._counter_lbl.SetForegroundColour(C_ACCENT)
        self._counter_lbl.SetFont(bold(9))
        self._counter_lbl.SetBackgroundColour(C_PANEL)
        h.Add(self._counter_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)

        panel.SetSizer(h)
        panel.SetMinSize((-1, 26))
        return panel

    # ── Library helpers ───────────────────────────────────────────────────────

    def _refresh_library(self) -> None:
        # wxChoice.GetSelection() returns wx.NOT_FOUND (-1) when nothing is
        # selected yet — passing that to GetString trips a hard C++ assertion
        # on macOS. Default to the first item if no selection has been made.
        sel = self._cat_choice.GetSelection()
        if sel == wx.NOT_FOUND:
            if self._cat_choice.GetCount() > 0:
                self._cat_choice.SetSelection(0)
                sel = 0
            else:
                cat = ""
        cat = self._cat_choice.GetString(sel) if sel != wx.NOT_FOUND else ""
        self._visible = registry.entries_for(cat)
        lc = self._lib_list
        lc.DeleteAllItems()
        for i, entry in enumerate(self._visible):
            lc.InsertItem(i, entry.label)
            lc.SetItemTextColour(
                i, wx.Colour(*CAT_COLOUR.get(entry.category, (200, 216, 200)))
            )

    def _on_filter_change(self, _event) -> None:
        self._refresh_library()

    def _on_lib_select(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if 0 <= idx < len(self._visible):
            self._selected = self._visible[idx]
            self._load_edit_form()
            self._refresh_preview()

    # ── Edit form ─────────────────────────────────────────────────────────────

    def _load_edit_form(self) -> None:
        if not self._selected:
            return
        e = self._selected
        self._e_uid.ChangeValue(e.uid)
        self._e_type.ChangeValue(e.cot_type)
        self._e_callsign.ChangeValue(e.callsign)
        self._e_lat.ChangeValue(str(e.lat))
        self._e_lon.ChangeValue(str(e.lon))
        self._e_hae.ChangeValue(str(e.hae))
        self._e_speed.ChangeValue(str(e.speed))
        self._e_course.ChangeValue(str(e.course))
        self._e_team.ChangeValue(e.team)
        self._e_role.ChangeValue(e.role)

    def _read_entry(self) -> CotEntry | None:
        """Derive a ``CotEntry`` from current form values."""
        if not self._selected:
            return None

        def _f(ctrl: wx.TextCtrl) -> float:
            try:
                return float(ctrl.GetValue())
            except ValueError:
                return 0.0

        return dataclasses.replace(
            self._selected,
            uid=self._e_uid.GetValue().strip(),
            cot_type=self._e_type.GetValue().strip(),
            callsign=self._e_callsign.GetValue().strip(),
            lat=_f(self._e_lat),
            lon=_f(self._e_lon),
            hae=_f(self._e_hae),
            speed=_f(self._e_speed),
            course=_f(self._e_course),
            team=self._e_team.GetValue().strip(),
            role=self._e_role.GetValue().strip(),
        )

    def _on_edit_change(self, _event) -> None:
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        entry = self._read_entry()
        if entry is None:
            return
        try:
            xml = self._builder.build(entry)
        except Exception as exc:
            xml = f"[XML error: {exc}]"
        self._preview.SetReadOnly(False)
        self._preview.SetText(xml)
        self._preview.SetReadOnly(True)

    def _on_randomise(self, _event) -> None:
        entry = self._read_entry()
        if entry is None:
            return
        jittered = dataclasses.replace(
            entry,
            lat=round(entry.lat + random.uniform(-0.005, 0.005), 7),
            lon=round(entry.lon + random.uniform(-0.005, 0.005), 7),
        )
        self._e_lat.ChangeValue(str(jittered.lat))
        self._e_lon.ChangeValue(str(jittered.lon))
        self._refresh_preview()

    # ── Authentication ────────────────────────────────────────────────────────

    def _on_login(self, _event) -> None:
        url = self._url_ctrl.GetValue().rstrip("/")
        cs = self._cs_ctrl.GetValue().strip()
        pw = self._pw_ctrl.GetValue()
        self._set_status(f"Logging in as {cs} …")

        def _task() -> None:
            try:
                code, body = BackendClient(url).login(cs, pw)
                if code == 200:
                    if body.get("mfa_required"):
                        self._msg_q.put(
                            MsgLoginErr("MFA required — disable for simulator use")
                        )
                    else:
                        self._msg_q.put(MsgLoginOk(token=body.get("access_token", "")))
                else:
                    self._msg_q.put(
                        MsgLoginErr(
                            f"HTTP {code}: {body.get('detail', str(body))[:120]}"
                        )
                    )
            except Exception as exc:
                self._msg_q.put(MsgLoginErr(str(exc)))

        threading.Thread(target=_task, daemon=True).start()

    # ── Send handlers (delegate to Strategy objects) ──────────────────────────

    def _guard(self) -> bool:
        if not self._selected:
            wx.MessageBox(
                "Select a CoT message from the library first.",
                "No selection",
                wx.ICON_WARNING,
            )
            return False
        if not self._token:
            wx.MessageBox("Login first.", "Not authenticated", wx.ICON_WARNING)
            return False
        return True

    def _on_send_once(self, _event) -> None:
        if self._guard():
            OnceSend().execute(self._enqueue_post)

    def _on_send_burst(self, _event) -> None:
        if self._guard():
            BurstSend(self._burst_spin.GetValue()).execute(self._enqueue_post)

    def _on_start_auto(self, _event) -> None:
        if not self._guard():
            return
        interval = self._auto_interval.GetValue()
        self._auto_send = AutoSend(interval)
        self._auto_send.start(
            trigger_fn=lambda: self._msg_q.put(MsgAutoTrigger()),
            on_done=lambda: self._msg_q.put(MsgAutoStopped()),
        )
        self._auto_lbl.SetLabel(f"Auto: ON ({interval:.1f}s)")
        self._auto_lbl.SetForegroundColour(C_OK)
        self._set_status(f"Auto-send: every {interval:.1f}s")

    def _on_stop_auto(self, _event) -> None:
        if self._auto_send:
            self._auto_send.stop()
            self._auto_send = None

    # ── Actual CoT HTTP post ──────────────────────────────────────────────────

    def _enqueue_post(self) -> None:
        """Build XML from the current edit form and spawn an HTTP thread."""
        entry = self._read_entry()
        if entry is None:
            return
        try:
            xml = self._builder.build(entry)
        except Exception as exc:
            log_append(self._out_log, f"\n[{ts()}] XML ERROR: {exc}\n", ST_ERR)
            self._errs += 1
            self._update_counters()
            return

        url = self._url_ctrl.GetValue().rstrip("/")
        token = self._token
        log_append(self._out_log, f"\n[{ts()}] → POST {url}/cot\n", ST_TS)
        log_append(self._out_log, xml, ST_XML)

        def _task() -> None:
            try:
                code, body = BackendClient(url).post_cot(xml, token)
                self._msg_q.put(MsgSendOk(status=code, body=body))
            except Exception as exc:
                self._msg_q.put(MsgSendErr(error=str(exc)))

        threading.Thread(target=_task, daemon=True).start()

    # ── WebSocket toggle ──────────────────────────────────────────────────────

    def _on_toggle_ws(self, _event) -> None:
        if self._ws_monitor and self._ws_monitor.running:
            self._ws_monitor.stop()
            self._ws_monitor = None
            return
        if not self._token:
            wx.MessageBox("Login first.", "Not authenticated", wx.ICON_WARNING)
            return
        token = self._token
        self._ws_monitor = WsMonitor(
            get_url=lambda: self._url_ctrl.GetValue().rstrip("/"),
            get_token=lambda: token,
            on_message=lambda raw: self._msg_q.put(MsgWsRaw(raw=raw)),
            on_status=lambda s: self._msg_q.put(MsgWsStatus(text=s)),
        )
        self._ws_monitor.start()
        self._msg_q.put(MsgWsBtn("WS DISCONNECT"))

    # ── Queue polling (wx.Timer → main thread) ────────────────────────────────

    def _poll_queue(self, _event=None) -> None:
        try:
            while True:
                msg = self._msg_q.get_nowait()
                handler = self._handlers.get(type(msg))
                if handler:
                    handler(msg)
        except queue.Empty:
            pass

    # ── Message handlers ──────────────────────────────────────────────────────

    def _h_login_ok(self, msg: MsgLoginOk) -> None:
        self._token = msg.token
        preview = msg.token[:30] + "…" if len(msg.token) > 30 else msg.token
        self._token_lbl.SetLabel(preview)
        self._token_lbl.SetForegroundColour(C_OK)
        log_append(self._out_log, f"[{ts()}] Logged in — token acquired.\n", ST_OK)
        self._set_status("Authenticated")

    def _h_login_err(self, msg: MsgLoginErr) -> None:
        log_append(self._out_log, f"[{ts()}] LOGIN ERROR: {msg.error}\n", ST_ERR)
        self._set_status("Login failed")
        wx.MessageBox(msg.error, "Login failed", wx.ICON_ERROR)

    def _h_send_ok(self, msg: MsgSendOk) -> None:
        style = ST_OK if msg.status in (200, 201) else ST_ERR
        log_append(self._out_log, f"[{ts()}] ← HTTP {msg.status}\n", style)
        if msg.body.strip().startswith("<"):
            log_append(self._out_log, msg.body + "\n", ST_XML)
        elif msg.body.strip():
            log_append(self._out_log, msg.body[:400] + "\n")
        if style == ST_OK:
            self._sent += 1
        else:
            self._errs += 1
        self._update_counters()
        self._set_status(f"Last send: HTTP {msg.status}")

    def _h_send_err(self, msg: MsgSendErr) -> None:
        log_append(self._out_log, f"[{ts()}] SEND ERROR: {msg.error}\n", ST_ERR)
        self._errs += 1
        self._update_counters()
        self._set_status(f"Error: {msg.error[:80]}")

    def _h_auto_trigger(self, _msg: MsgAutoTrigger) -> None:
        self._enqueue_post()

    def _h_auto_stopped(self, _msg: MsgAutoStopped) -> None:
        self._auto_lbl.SetLabel("Auto: OFF")
        self._auto_lbl.SetForegroundColour(C_ERR)
        self._set_status("Auto-send stopped")

    def _h_ws_status(self, msg: MsgWsStatus) -> None:
        self._ws_status_lbl.SetLabel(f"WS: {msg.text}")
        self._ws_status_lbl.SetForegroundColour(WS_STATUS_COLOUR.get(msg.text, C_DIM))
        if msg.text in ("OFF", "ERR"):
            self._ws_btn.SetLabel("WS CONNECT")

    def _h_ws_btn(self, msg: MsgWsBtn) -> None:
        self._ws_btn.SetLabel(msg.label)

    def _h_ws_raw(self, msg: MsgWsRaw) -> None:
        try:
            obj = json.loads(msg.raw)
        except json.JSONDecodeError:
            log_append(self._in_log, f"[{ts()}] RAW: {msg.raw}\n")
            return

        if obj.get("__log__"):
            style = LOG_STYLE_MAP.get(obj.get("style", ""), ST_SYS)
            log_append(self._in_log, obj.get("text", ""), style)
            return

        self._rx += 1
        self._update_counters()
        channel = obj.get("channel", "?")
        event = obj.get("event", "?")
        log_append(self._in_log, f"[{ts()}] ", ST_TS)
        log_append(self._in_log, f"[{channel}/{event}] ", ST_CHANNEL)
        if cot_xml := obj.get("cot_xml"):
            log_append(self._in_log, "\n" + cot_xml + "\n", ST_XML)
        if data := obj.get("data"):
            log_append(self._in_log, json.dumps(data, indent=2) + "\n", ST_DATA)
        if not obj.get("cot_xml") and not obj.get("data"):
            log_append(self._in_log, json.dumps(obj, indent=2) + "\n", ST_DATA)

    # ── Misc helpers ──────────────────────────────────────────────────────────

    def _clear_log(self, ctrl: stc.StyledTextCtrl) -> None:
        ctrl.SetReadOnly(False)
        ctrl.ClearAll()
        ctrl.SetReadOnly(True)

    def _set_status(self, msg: str) -> None:
        self._status_lbl.SetLabel(msg)

    def _update_counters(self) -> None:
        self._counter_lbl.SetLabel(
            f"Sent: {self._sent}  Rx: {self._rx}  Errors: {self._errs}"
        )
