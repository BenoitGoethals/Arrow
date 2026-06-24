"""Top-down plan-view: gun positions + PDF direction arrow for one section."""
from __future__ import annotations

import math

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF, QPainterPath
from PyQt6.QtWidgets import QWidget, QSizePolicy

from ..battery import Peloton, Group
from ..ballistics import FireTableLibrary

_BG    = QColor("#1a2535")
_FG    = QColor("#ecf0f1")
_RED   = QColor("#e74c3c")
_GREEN = QColor("#27ae60")
_BLUE  = QColor("#2980b9")
_GREY  = QColor("#7f8c8d")
_FO_COLOR = QColor("#e056fd")   # FO / observer posts

# Per-section PDF arrow colours (cycled). Limited to 4 sections by domain rule.
SECTION_COLORS = ["#e74c3c", "#3498db", "#f39c12", "#9b59b6"]
_SECTION_COLORS = [QColor(c) for c in SECTION_COLORS]

# Range-ring colours per ammunition (cycled), as hex so map_panel can reuse them.
AMMO_COLORS = ["#1abc9c", "#e67e22", "#9b59b6", "#f1c40f", "#16a085", "#d35400"]


def ammo_color(index: int) -> QColor:
    return QColor(AMMO_COLORS[index % len(AMMO_COLORS)])


class SectionDiagram(QWidget):
    """Plan-view diagram of one section: pieces, PDF, optional range arcs.

    `visible_shells` controls which munition envelopes are drawn:
      * None  → no range arcs (default)
      * set() → no range arcs
      * a populated set → only those shells (case-insensitive match against
        ``library.shells()``)
    """

    _PAD       = 32    # pixels of padding around the plot area
    _GUN_R     = 7     # gun circle radius in px
    _ARROW_LEN = 54    # PDF arrow length in px

    def __init__(self, peloton: Peloton, group: Group,
                 library: FireTableLibrary | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.peloton = peloton
        self.group   = group
        self.library = library
        self.visible_shells: set[str] | None = None
        self.setMinimumSize(180, 220)
        self.setMaximumHeight(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_visible_shells(self, shells: set[str] | None) -> None:
        """Set which range envelopes are drawn (None / empty = none)."""
        self.visible_shells = (
            None if shells is None else {s.upper() for s in shells}
        )
        self.update()

    def _rings(self) -> list[tuple[str, float, float, QColor]]:
        if not self.library or self.visible_shells is None or not self.visible_shells:
            return []
        out: list[tuple[str, float, float, QColor]] = []
        for i, shell in enumerate(self.library.shells()):
            if shell.upper() not in self.visible_shells:
                continue
            lo, hi = self.library.tables[shell].range_span_m
            # Section's max-range cap, if any
            hi = self.group.effective_max_m(hi)
            out.append((shell, lo, hi, ammo_color(i)))
        return out

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), _BG)

        pieces = [pc for pc in self.peloton.pieces
                  if pc.name in self.group.member_names]
        w, h = float(self.width()), float(self.height())

        if not pieces:
            p.setPen(_GREY)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No pieces assigned")
            self._north(p, w - 18.0, 14.0)
            return

        # ---- coordinate → screen mapping ----
        es = [pc.position.easting  for pc in pieces]
        ns = [pc.position.northing for pc in pieces]
        ce = sum(es) / len(es)
        cn = sum(ns) / len(ns)
        span = max(
            (max(es) - min(es)) if len(pieces) > 1 else 0.0,
            (max(ns) - min(ns)) if len(pieces) > 1 else 0.0,
            50.0,
        )
        # Range rings expand the view so the largest selected max fits.
        rings = self._rings()
        if rings:
            max_r = max(hi for _, _, hi, _ in rings)
            span = max(span, 2.0 * max_r * 1.08)
        usable = min(w, h) - 2.0 * self._PAD
        scale  = usable / span
        cx, cy = w / 2.0, h / 2.0

        def sc(e: float, n: float) -> QPointF:
            return QPointF(cx + (e - ce) * scale,
                           cy - (n - cn) * scale)   # north = up

        # ---- range arcs/rings per ammunition (drawn behind everything) ----
        if rings:
            self._draw_section_ranges(p, sc, scale, rings)

        # ---- PDF arrows (drawn behind guns) ----
        rad  = self.group.pdf_mils * 2.0 * math.pi / 6400.0
        udx  =  math.sin(rad)
        udy  = -math.cos(rad)   # screen Y is flipped
        p.setPen(QPen(_RED, 2))
        for pc in pieces:
            origin = sc(pc.position.easting, pc.position.northing)
            tip    = QPointF(origin.x() + udx * self._ARROW_LEN,
                             origin.y() + udy * self._ARROW_LEN)
            p.drawLine(origin, tip)
            _arrowhead(p, origin, tip, _RED)

        # ---- left/right limit lines (sector of fire) ----
        if self.group.has_limits():
            for limit_mils in (self.group.left_limit_mils, self.group.right_limit_mils):
                lrad = limit_mils * 2.0 * math.pi / 6400.0
                ldx, ldy = math.sin(lrad), -math.cos(lrad)
                pen = QPen(QColor("#f39c12"), 1); pen.setStyle(Qt.PenStyle.DashLine)
                p.setPen(pen)
                for pc in pieces:
                    origin = sc(pc.position.easting, pc.position.northing)
                    end = QPointF(origin.x() + ldx * self._ARROW_LEN * 0.95,
                                  origin.y() + ldy * self._ARROW_LEN * 0.95)
                    p.drawLine(origin, end)

        # ---- gun symbols ----
        for pc in pieces:
            pos   = sc(pc.position.easting, pc.position.northing)
            color = _GREEN if pc.is_base else _BLUE
            p.setBrush(QBrush(color))
            p.setPen(QPen(_FG, 1))
            p.drawEllipse(pos, float(self._GUN_R), float(self._GUN_R))
            font = p.font(); font.setPointSize(8); p.setFont(font)
            p.setPen(_FG)
            p.drawText(QPointF(pos.x() + self._GUN_R + 3, pos.y() + 4), pc.name)

        # ---- decorations ----
        self._north(p, w - 18.0, 14.0)
        self._scale_bar(p, scale, h)

        # PDF label bottom-right
        font = p.font(); font.setPointSize(8); p.setFont(font)
        p.setPen(_RED)
        p.drawText(QRectF(w / 2, h - 16, w / 2 - 4, 14),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"PDF  {int(self.group.pdf_mils)} mils ▶")

        # legend bottom-left
        font.setPointSize(7); p.setFont(font)
        p.setPen(_GREEN)
        p.drawText(QRectF(4, h - 28, 60, 12), Qt.AlignmentFlag.AlignLeft, "● basisstuk")
        p.setPen(_BLUE)
        p.drawText(QRectF(4, h - 16, 60, 12), Qt.AlignmentFlag.AlignLeft, "● stuk")
        # range legend top-left when rings are on — larger font, plus a
        # `(capped)` marker when the group's max_range_m is in effect.
        if rings:
            font.setPointSize(10); font.setBold(True); p.setFont(font)
            cap = self.group.max_range_m
            for i, (shell, lo, hi, color) in enumerate(rings):
                p.setPen(color)
                tag = "  (capped)" if cap > 0 and hi <= cap + 0.5 else ""
                p.drawText(QPointF(6, 18 + i * 16),
                           f"● {shell}  {lo:.0f}–{hi:.0f} m{tag}")
            font.setBold(False); p.setFont(font)

    # ------------------------------------------------------------------ helpers
    def _draw_section_ranges(self, p: QPainter, sc, scale: float,
                             rings: list[tuple[str, float, float, QColor]]) -> None:
        """Range arcs centered on this section's centroid, clipped to the
        section's sector of fire if limits are set."""
        pts = [pc.position for pc in self.peloton.pieces
               if pc.name in self.group.member_names]
        if not pts:
            return
        c_e = sum(q.easting  for q in pts) / len(pts)
        c_n = sum(q.northing for q in pts) / len(pts)
        center = sc(c_e, c_n)

        limited = self.group.has_limits()
        left = self.group.left_limit_mils
        sweep = self.group.sector_width_mils()
        overall_max = max(hi for _, _, hi, _ in rings)

        if limited:
            # faint filled wedge for sector of fire
            outer = BatteryDiagram._arc_points(center, overall_max * scale, left, sweep)
            path = QPainterPath(center)
            for pt in outer:
                path.lineTo(pt)
            path.lineTo(center)
            fill = QColor("#f39c12"); fill.setAlpha(22)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(fill); p.drawPath(path)

        p.setBrush(Qt.BrushStyle.NoBrush)
        font = p.font(); font.setPointSize(9); font.setBold(True); p.setFont(font)
        for shell, lo, hi, color in rings:
            if limited:
                p.setPen(QPen(color, 1.8))
                p.drawPolyline(BatteryDiagram._arc_points(center, hi * scale, left, sweep))
                if lo > 0:
                    pen = QPen(color, 1.0); pen.setStyle(Qt.PenStyle.DashLine); p.setPen(pen)
                    p.drawPolyline(BatteryDiagram._arc_points(center, lo * scale, left, sweep))
                # max-range label at the centre azimuth of the sector
                self._label_at_azimuth(
                    p, center, hi * scale,
                    (left + sweep / 2.0) % 6400.0,
                    f"{shell} {hi:.0f} m", color,
                )
            else:
                p.setPen(QPen(color, 1.8))
                p.drawEllipse(center, hi * scale, hi * scale)
                if lo > 0:
                    pen = QPen(color, 1.0); pen.setStyle(Qt.PenStyle.DashLine); p.setPen(pen)
                    p.drawEllipse(center, lo * scale, lo * scale)
                # max-range label at the section's PDF azimuth
                self._label_at_azimuth(
                    p, center, hi * scale, self.group.pdf_mils,
                    f"{shell} {hi:.0f} m", color,
                )
        font.setBold(False); p.setFont(font)

    @staticmethod
    def _label_at_azimuth(p: QPainter, center: QPointF, radius_px: float,
                          azimuth_mils: float, text: str, color: QColor) -> None:
        rad = azimuth_mils * 2.0 * math.pi / 6400.0
        x = center.x() + radius_px * math.sin(rad)
        y = center.y() - radius_px * math.cos(rad)
        # nudge slightly outward
        nx = math.sin(rad); ny = -math.cos(rad)
        x += nx * 4; y += ny * 4
        p.setPen(color)
        p.drawText(QPointF(x - 14, y - 2), text)

    @staticmethod
    def _scale_bar(p: QPainter, scale: float, h: float) -> None:
        for metres in (3000, 2000, 1000, 500, 200, 100, 50, 20, 10):
            px = metres * scale
            if px >= 24:
                break
        else:
            return
        x0, y0 = 70.0, h - 20.0
        p.setPen(QPen(_GREY, 2))
        p.drawLine(QPointF(x0, y0), QPointF(x0 + px, y0))
        p.drawLine(QPointF(x0,      y0 - 3), QPointF(x0,      y0 + 3))
        p.drawLine(QPointF(x0 + px, y0 - 3), QPointF(x0 + px, y0 + 3))
        font = p.font(); font.setPointSize(7); p.setFont(font)
        p.setPen(_GREY)
        p.drawText(QRectF(x0, y0 - 13, px + 40, 11), Qt.AlignmentFlag.AlignLeft,
                   f"{metres} m")

    @staticmethod
    def _north(p: QPainter, x: float, y: float) -> None:
        shaft = 14.0
        tip   = QPointF(x, y)
        base  = QPointF(x, y + shaft)
        p.setPen(QPen(_GREY, 1))
        p.drawLine(base, tip)
        _arrowhead(p, base, tip, _GREY, size=6)
        font = p.font(); font.setPointSize(7); p.setFont(font)
        p.setPen(_GREY)
        p.drawText(QRectF(x - 5, y + shaft + 1, 10, 10), Qt.AlignmentFlag.AlignCenter, "N")


class BatteryDiagram(QWidget):
    """Plan view of the whole platoon: every piece + every section's PDF.

    - Pieces are dots labeled with their name (green=base, blue=slave,
      grey=unassigned to any section).
    - For every section, a coloured arrow is drawn from every member piece
      in the section's PDF direction.
    - An optional `highlight_group` name draws that section's arrows thicker.
    """

    _PAD       = 36
    _GUN_R     = 7
    _ARROW_LEN = 60

    def __init__(self, peloton: Peloton, library: FireTableLibrary | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.peloton = peloton
        self.library = library
        self.highlight_group: str | None = None
        # None / empty = no rings; otherwise only the named shells.
        self.visible_shells: set[str] | None = None
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_highlight(self, group_name: str | None) -> None:
        self.highlight_group = group_name
        self.update()

    def set_visible_shells(self, shells: set[str] | None) -> None:
        """Pick which shells contribute range envelopes (None / empty = none)."""
        self.visible_shells = (
            None if shells is None else {s.upper() for s in shells}
        )
        self.update()

    def set_show_ranges(self, flag: bool) -> None:
        """Convenience: show all shells (True) or none (False)."""
        if flag and self.library:
            self.set_visible_shells({s.upper() for s in self.library.shells()})
        else:
            self.set_visible_shells(None)

    def _rings(self) -> list[tuple[str, float, float, QColor]]:
        """(shell, min_m, max_m, colour) per selected ammunition.

        The hi value is the absolute firing-table max; per-section caps are
        applied inside ``_draw_sector`` (each section can override).
        """
        if (not self.library
                or self.visible_shells is None
                or not self.visible_shells):
            return []
        out: list[tuple[str, float, float, QColor]] = []
        for i, shell in enumerate(self.library.shells()):
            if shell.upper() not in self.visible_shells:
                continue
            lo, hi = self.library.tables[shell].range_span_m
            out.append((shell, lo, hi, ammo_color(i)))
        return out

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), _BG)

        w, h = float(self.width()), float(self.height())
        pieces = list(self.peloton.pieces)

        if not pieces:
            p.setPen(_GREY)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "No pieces yet — Add piece…")
            self._north(p, w - 18.0, 14.0)
            return

        # ---- coordinate → screen mapping (centred on the gun centroid) ----
        es = [pc.position.easting  for pc in pieces]
        ns = [pc.position.northing for pc in pieces]
        ce = sum(es) / len(es)
        cn = sum(ns) / len(ns)
        # Fit guns + FOs: span must cover the farthest point from the centroid.
        observers = list(self.peloton.observers)
        off_e = [abs(e - ce) for e in es] + [abs(o.position.easting - ce) for o in observers]
        off_n = [abs(n - cn) for n in ns] + [abs(o.position.northing - cn) for o in observers]
        span = max(2.0 * max(off_e + off_n + [50.0]), 100.0)
        # When range rings are shown, zoom out so the largest max-range fits.
        rings = self._rings()
        if rings:
            max_r = max(hi for _, _, hi, _ in rings)
            span = max(span, 2.0 * max_r * 1.08)
        usable = min(w, h) - 2.0 * self._PAD
        scale  = usable / span
        cx, cy = w / 2.0, h / 2.0

        def sc(e: float, n: float) -> QPointF:
            return QPointF(cx + (e - ce) * scale,
                           cy - (n - cn) * scale)

        # ---- range sectors/rings per ammunition (drawn first, behind everything) ----
        if rings:
            self._draw_ranges(p, sc, scale, ce, cn, rings)

        # ---- PDF arrows per section (behind guns) ----
        for gi, group in enumerate(self.peloton.groups):
            color = _SECTION_COLORS[gi % len(_SECTION_COLORS)]
            is_hi = (group.name == self.highlight_group)
            pen_w = 3 if is_hi else 2
            p.setPen(QPen(color, pen_w))
            rad = group.pdf_mils * 2.0 * math.pi / 6400.0
            udx =  math.sin(rad)
            udy = -math.cos(rad)
            length = self._ARROW_LEN if is_hi else int(self._ARROW_LEN * 0.85)
            for pname in group.member_names:
                pc = next((x for x in pieces if x.name == pname), None)
                if pc is None:
                    continue
                origin = sc(pc.position.easting, pc.position.northing)
                tip    = QPointF(origin.x() + udx * length,
                                 origin.y() + udy * length)
                p.drawLine(origin, tip)
                _arrowhead(p, origin, tip, color,
                           size=10 if is_hi else 8)

        # ---- gun symbols ----
        for pc in pieces:
            pos = sc(pc.position.easting, pc.position.northing)
            in_section = self.peloton.group_of(pc.name) is not None
            if pc.is_base:
                color = _GREEN
            elif in_section:
                color = _BLUE
            else:
                color = _GREY
            p.setBrush(QBrush(color))
            p.setPen(QPen(_FG, 1))
            p.drawEllipse(pos, float(self._GUN_R), float(self._GUN_R))
            font = p.font(); font.setPointSize(8); p.setFont(font)
            p.setPen(_FG)
            p.drawText(QPointF(pos.x() + self._GUN_R + 3, pos.y() + 4), pc.name)

        # ---- FO posts (diamond markers) ----
        for o in observers:
            pos = sc(o.position.easting, o.position.northing)
            r = float(self._GUN_R)
            diamond = QPolygonF([
                QPointF(pos.x(), pos.y() - r), QPointF(pos.x() + r, pos.y()),
                QPointF(pos.x(), pos.y() + r), QPointF(pos.x() - r, pos.y()),
            ])
            p.setBrush(QBrush(_FO_COLOR)); p.setPen(QPen(_FG, 1))
            p.drawPolygon(diamond)
            font = p.font(); font.setPointSize(8); p.setFont(font)
            p.setPen(_FO_COLOR)
            p.drawText(QPointF(pos.x() + r + 3, pos.y() + 4), o.call_sign)

        # ---- decorations ----
        self._north(p, w - 18.0, 14.0)
        self._scale_bar(p, scale, h)
        self._legend(p, w, h)

    # ------------------------------------------------------------------ helpers
    def _centroid(self, names) -> tuple[float, float] | None:
        pts = [pc.position for pc in self.peloton.pieces if pc.name in names]
        if not pts:
            return None
        return (sum(q.easting for q in pts) / len(pts),
                sum(q.northing for q in pts) / len(pts))

    def _draw_ranges(self, p: QPainter, sc, scale: float, ce: float, cn: float,
                     rings: list[tuple[str, float, float, QColor]]) -> None:
        """Draw range coverage: a sector ('pie') per section with limits, else
        full rings centred on the battery."""
        sections = [g for g in self.peloton.groups if self._centroid(g.member_names)]
        if sections:
            for gi, g in enumerate(self.peloton.groups):
                c = self._centroid(g.member_names)
                if c is None:
                    continue
                sec_color = _SECTION_COLORS[gi % len(_SECTION_COLORS)]
                self._draw_sector(p, sc(c[0], c[1]), scale, rings, g, sec_color)
        else:
            self._draw_full_rings(p, sc(ce, cn), scale, rings)
        self._ammo_legend(p, rings)

    @staticmethod
    def _arc_points(center: QPointF, radius_px: float,
                    start_mils: float, sweep_mils: float) -> QPolygonF:
        n = max(2, int(sweep_mils / 40) + 1)
        poly = QPolygonF()
        for k in range(n + 1):
            rad = (start_mils + sweep_mils * k / n) * 2.0 * math.pi / 6400.0
            poly.append(QPointF(center.x() + radius_px * math.sin(rad),
                                center.y() - radius_px * math.cos(rad)))
        return poly

    @classmethod
    def _draw_sector(cls, p: QPainter, center: QPointF, scale: float,
                     rings: list[tuple[str, float, float, QColor]],
                     group: Group, sec_color: QColor) -> None:
        # Apply this group's max-range cap (if any) to the ring set.
        capped = [
            (shell, lo, group.effective_max_m(hi), color)
            for shell, lo, hi, color in rings
        ]
        if not group.has_limits():
            cls._draw_full_rings(p, center, scale, capped, group)
            return
        left = group.left_limit_mils
        sweep = group.sector_width_mils()
        overall_max = max(hi for _, _, hi, _ in capped)

        # Strong filled wedge = the sector of fire (the "pie")
        outer = cls._arc_points(center, overall_max * scale, left, sweep)
        path = QPainterPath(center)
        for pt in outer:
            path.lineTo(pt)
        path.lineTo(center)
        fill = QColor(sec_color); fill.setAlpha(55)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(fill); p.drawPath(path)

        # ammo arcs: max solid, min dashed — only across the sector
        p.setBrush(Qt.BrushStyle.NoBrush)
        font = p.font(); font.setPointSize(9); font.setBold(True); p.setFont(font)
        for shell, lo, hi, color in capped:
            p.setPen(QPen(color, 1.8))
            p.drawPolyline(cls._arc_points(center, hi * scale, left, sweep))
            if lo > 0:
                pen = QPen(color, 1.0); pen.setStyle(Qt.PenStyle.DashLine); p.setPen(pen)
                p.drawPolyline(cls._arc_points(center, lo * scale, left, sweep))
            # max-range label at the sector's mid-azimuth
            mid = (left + sweep / 2.0) % 6400.0
            cls._label_arc(p, center, hi * scale, mid, f"{shell} {hi:.0f} m", color)

        # left / right limit lines + bigger L/R labels
        font.setPointSize(11); font.setBold(True); p.setFont(font)
        for a, lab in ((left, "L"), ((left + sweep) % 6400.0, "R")):
            rad = a * 2.0 * math.pi / 6400.0
            end = QPointF(center.x() + overall_max * scale * math.sin(rad),
                          center.y() - overall_max * scale * math.cos(rad))
            p.setPen(QPen(sec_color, 2)); p.drawLine(center, end)
            p.setPen(sec_color); p.drawText(end, lab)
        font.setBold(False); p.setFont(font)

    @classmethod
    def _draw_full_rings(cls, p: QPainter, center: QPointF, scale: float,
                         rings: list[tuple[str, float, float, QColor]],
                         group: Group | None = None) -> None:
        """Concentric min (dashed) / max (solid) full circles per ammunition."""
        p.setBrush(Qt.BrushStyle.NoBrush)
        font = p.font(); font.setPointSize(9); font.setBold(True); p.setFont(font)
        pdf_mils = group.pdf_mils if group is not None else 0.0
        for shell, lo, hi, color in rings:
            p.setPen(QPen(color, 1.8))
            p.drawEllipse(center, hi * scale, hi * scale)
            if lo > 0:
                pen = QPen(color, 1.0); pen.setStyle(Qt.PenStyle.DashLine); p.setPen(pen)
                p.drawEllipse(center, lo * scale, lo * scale)
            cls._label_arc(p, center, hi * scale, pdf_mils,
                           f"{shell} {hi:.0f} m", color)
        font.setBold(False); p.setFont(font)

    @staticmethod
    def _label_arc(p: QPainter, center: QPointF, radius_px: float,
                   azimuth_mils: float, text: str, color: QColor) -> None:
        rad = azimuth_mils * 2.0 * math.pi / 6400.0
        x = center.x() + radius_px * math.sin(rad)
        y = center.y() - radius_px * math.cos(rad)
        nx, ny = math.sin(rad), -math.cos(rad)
        x += nx * 5; y += ny * 5
        p.setPen(color)
        p.drawText(QPointF(x - 16, y - 2), text)

    @staticmethod
    def _ammo_legend(p: QPainter, rings: list[tuple[str, float, float, QColor]]) -> None:
        font = p.font(); font.setPointSize(10); font.setBold(True); p.setFont(font)
        for i, (shell, lo, hi, color) in enumerate(rings):
            p.setPen(color)
            p.drawText(QPointF(6, 18 + i * 16), f"● {shell}  {lo:.0f}–{hi:.0f} m")
        font.setBold(False); p.setFont(font)

    @staticmethod
    def _scale_bar(p: QPainter, scale: float, h: float) -> None:
        for metres in (3000, 2000, 1000, 500, 200, 100, 50, 20, 10):
            px = metres * scale
            if px >= 28:
                break
        else:
            return
        x0, y0 = 70.0, h - 22.0
        p.setPen(QPen(_GREY, 2))
        p.drawLine(QPointF(x0, y0), QPointF(x0 + px, y0))
        p.drawLine(QPointF(x0,      y0 - 3), QPointF(x0,      y0 + 3))
        p.drawLine(QPointF(x0 + px, y0 - 3), QPointF(x0 + px, y0 + 3))
        font = p.font(); font.setPointSize(7); p.setFont(font)
        p.setPen(_GREY)
        p.drawText(QRectF(x0, y0 - 13, px + 40, 11), Qt.AlignmentFlag.AlignLeft, f"{metres} m")

    @staticmethod
    def _north(p: QPainter, x: float, y: float) -> None:
        shaft = 14.0
        tip   = QPointF(x, y)
        base  = QPointF(x, y + shaft)
        p.setPen(QPen(_GREY, 1))
        p.drawLine(base, tip)
        _arrowhead(p, base, tip, _GREY, size=6)
        font = p.font(); font.setPointSize(7); p.setFont(font)
        p.setPen(_GREY)
        p.drawText(QRectF(x - 5, y + shaft + 1, 10, 10), Qt.AlignmentFlag.AlignCenter, "N")

    def _legend(self, p: QPainter, w: float, h: float) -> None:
        font = p.font(); font.setPointSize(7); p.setFont(font)
        x = w - 6
        y = h - 6
        # piece legend along bottom-right (right→left)
        for label, color in (
            ("● unassigned", _GREY),
            ("● slave", _BLUE),
            ("● basisstuk", _GREEN),
        ):
            p.setPen(color)
            r = p.fontMetrics().boundingRect(label)
            p.drawText(QPointF(x - r.width(), y), label)
            x -= r.width() + 10
        # PDF colour key bottom-left
        x = 8
        font.setPointSize(7); p.setFont(font)
        for gi, group in enumerate(self.peloton.groups):
            color = _SECTION_COLORS[gi % len(_SECTION_COLORS)]
            label = f"▶ {group.name} {int(group.pdf_mils)} mils"
            p.setPen(color)
            r = p.fontMetrics().boundingRect(label)
            p.drawText(QPointF(x, y), label)
            x += r.width() + 12
            if x > w - 240:
                break


def _arrowhead(p: QPainter, start: QPointF, tip: QPointF,
               color: QColor, size: int = 9) -> None:
    dx = tip.x() - start.x()
    dy = tip.y() - start.y()
    length = math.hypot(dx, dy)
    if length < 1.0:
        return
    ux, uy = dx / length, dy / length
    left  = QPointF(tip.x() - size * ux + size * 0.42 * uy,
                    tip.y() - size * uy - size * 0.42 * ux)
    right = QPointF(tip.x() - size * ux - size * 0.42 * uy,
                    tip.y() - size * uy + size * 0.42 * ux)
    p.setBrush(QBrush(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(QPolygonF([tip, left, right]))
