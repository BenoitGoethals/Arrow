"""Tab 'Kaart' — Leaflet kaart in QtWebEngine met stukken, merkpunten, FO en doelen."""
from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QHBoxLayout, QLabel,
    QFileDialog, QMessageBox,
)
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from ..battery import Peloton, Group
from ..ballistics import FireTableLibrary
from ..firemission.mission import TargetType, Sheaf
from ..geo import utm_to_latlon, offset, polar, Position
from .mbtiles_server import TileServer
from .position_diagram import AMMO_COLORS, SECTION_COLORS

if TYPE_CHECKING:
    from .mission_panel import MissionPanel


def _latlon(pos) -> tuple[float, float]:
    return utm_to_latlon(pos)


class MapPanel(QWidget):
    """Toont peloton + actieve fire missions op een Leaflet-kaart."""

    def __init__(self, peloton: Peloton, mission_panel: "MissionPanel",
                 library: FireTableLibrary | None = None) -> None:
        super().__init__()
        self.peloton = peloton
        self.mission_panel = mission_panel
        self.library = library
        self.loaded = False
        self._tile_server = TileServer()

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self._mbtiles_label = QLabel("MBTiles: (none)")
        b_mbtiles = QPushButton("Load MBTiles…")
        b_mbtiles.clicked.connect(self._on_load_mbtiles)
        b_clear = QPushButton("Clear MBTiles")
        b_clear.clicked.connect(self._on_clear_mbtiles)
        b_refresh = QPushButton("Refresh")
        b_refresh.clicked.connect(self.refresh)
        bar.addWidget(QLabel("Live overview of platoon and active fire missions."))
        bar.addStretch(1)
        bar.addWidget(self._mbtiles_label)
        bar.addWidget(b_mbtiles)
        bar.addWidget(b_clear)
        bar.addWidget(b_refresh)
        root.addLayout(bar)

        self.view = QWebEngineView()
        # map.html is loaded from a local file:// URL, so by default QtWebEngine
        # blocks the HTTPS tile requests and the canvas stays black. Allow the
        # local page to fetch remote tile URLs (and the local MBTiles server).
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        self.view.loadFinished.connect(self._on_loaded)
        html_path = files("mortarcalc.gui.assets").joinpath("map.html")
        self.view.load(QUrl.fromLocalFile(str(html_path)))
        root.addWidget(self.view, stretch=1)

    # ---------- MBTiles ----------
    def _on_load_mbtiles(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select MBTiles file", "", "MBTiles (*.mbtiles);;All files (*)",
        )
        if not path:
            return
        try:
            self._tile_server.load(Path(path))
        except Exception as e:
            QMessageBox.critical(self, "MBTiles load failed", str(e))
            return
        self._mbtiles_label.setText(f"MBTiles: {Path(path).name}")
        if self.loaded:
            url = self._tile_server.url_template
            js = (
                f"window.mc_set_mbtiles({json.dumps(url)},"
                f"{json.dumps(self._tile_server.store.metadata if self._tile_server.store else {})});"
            )
            self.view.page().runJavaScript(js)
        self.refresh()

    def _on_clear_mbtiles(self) -> None:
        self._tile_server.shutdown()
        self._mbtiles_label.setText("MBTiles: (none)")
        if self.loaded:
            self.view.page().runJavaScript("window.mc_set_mbtiles(null, null);")

    def _on_loaded(self, ok: bool) -> None:
        self.loaded = ok
        if ok:
            # If MBTiles were already loaded, hand them to JS before the first render.
            if self._tile_server.url_template:
                js = (
                    f"window.mc_set_mbtiles({json.dumps(self._tile_server.url_template)},"
                    f"{json.dumps(self._tile_server.store.metadata if self._tile_server.store else {})});"
                )
                self.view.page().runJavaScript(js)
            self.refresh()

    def refresh(self) -> None:
        if not self.loaded:
            return
        payload = self._build_payload()
        js = f"window.mc_render({json.dumps(json.dumps(payload))});"
        self.view.page().runJavaScript(js)

    # ---------- data ----------
    def _build_payload(self) -> dict:
        pieces = []
        pdf_arrows = []
        for p in self.peloton.pieces:
            lat, lon = _latlon(p.position)
            g = self.peloton.group_of(p.name)
            pieces.append({
                "name": p.name, "lat": lat, "lon": lon,
                "mgrs": p.position.to_mgrs(), "is_base": p.is_base,
                "group": g.name if g else None,
            })
            if g is not None:
                # 200 m pijl in PDF-richting vanuit het stuk
                tip = offset(p.position, g.pdf_mils, 200.0)
                tlat, tlon = _latlon(tip)
                pdf_arrows.append({
                    "from_lat": lat, "from_lon": lon,
                    "to_lat": tlat, "to_lon": tlon,
                })

        aps = []
        for ap in self.peloton.aiming_points:
            lat, lon = _latlon(ap.position)
            aps.append({"name": ap.name, "lat": lat, "lon": lon, "mgrs": ap.position.to_mgrs()})

        fos = []
        targets = []
        gt_lines = []
        ot_lines = []
        seen_fos: set[str] = set()
        # All FOs defined in Platoon & Lay show on the map regardless of missions.
        for o in self.peloton.observers:
            seen_fos.add(o.call_sign)
            lat, lon = _latlon(o.position)
            fos.append({"call_sign": o.call_sign, "lat": lat, "lon": lon,
                        "mgrs": o.position.to_mgrs()})
        for group_name, fm in self.mission_panel.active.items():
            if fm is None:
                continue
            if fm.observer.call_sign not in seen_fos:
                seen_fos.add(fm.observer.call_sign)
                lat, lon = _latlon(fm.observer.position)
                fos.append({"call_sign": fm.observer.call_sign, "lat": lat, "lon": lon,
                            "mgrs": fm.observer.position.to_mgrs()})
            if fm.target_position is not None:
                tlat, tlon = _latlon(fm.target_position)
                # FO → target (OT) line: the observer's direction for this mission
                folat, folon = _latlon(fm.observer.position)
                ot = polar(fm.observer.position, fm.target_position)
                ot_lines.append({
                    "from_lat": folat, "from_lon": folon,
                    "to_lat": tlat, "to_lon": tlon,
                    "call_sign": fm.observer.call_sign, "fm_id": fm.id,
                    "azimuth_mils": ot.azimuth_mils, "range_m": ot.range_m,
                })
                target_entry: dict = {
                    "fm_id": fm.id, "group": group_name, "lat": tlat, "lon": tlon,
                    "mgrs": fm.target_position.to_mgrs(),
                    "type": fm.target_type.value,
                    "description": fm.target_description or "",
                    "sheaf": fm.sheaf.value,
                }
                # Voor lijn-doel of LINEAR sheaf: bereken twee eindpunten van de lijn.
                if fm.target_type == TargetType.LINEAR or fm.sheaf == Sheaf.LINEAR:
                    half = max(0.0, fm.line_length_m) / 2.0
                    az = fm.line_azimuth_mils
                    end_a = offset(fm.target_position, az, half)
                    end_b = offset(fm.target_position, (az + 3200.0) % 6400.0, half)
                    a_lat, a_lon = _latlon(end_a)
                    b_lat, b_lon = _latlon(end_b)
                    target_entry["line"] = {
                        "a_lat": a_lat, "a_lon": a_lon,
                        "b_lat": b_lat, "b_lon": b_lon,
                        "length_m": fm.line_length_m,
                        "azimuth_mils": fm.line_azimuth_mils,
                    }
                targets.append(target_entry)
                # GT-lijnen vanaf elk stuk in de groep naar het doel
                try:
                    group = self.peloton.group(group_name)
                except KeyError:
                    continue
                for piece in self.peloton.pieces_in(group):
                    plat, plon = _latlon(piece.position)
                    gt_lines.append({"from_lat": plat, "from_lon": plon,
                                     "to_lat": tlat, "to_lon": tlon})

        return {
            "pieces": pieces,
            "pdf_arrows": pdf_arrows,
            "aiming_points": aps,
            "fos": fos,
            "targets": targets,
            "planned_targets": self._planned_targets(),
            "gt_lines": gt_lines,
            "ot_lines": ot_lines,
            "range_sectors": self._range_sectors(),
            "piece_ranges": self._piece_ranges(),
            "ammo_legend": self._ammo_legend(),
        }

    # ---------- planned (preplotted) targets ----------
    def _planned_targets(self) -> list[dict]:
        """Fire-plan targets shown as ghost markers on the map.

        Visually separated from live-mission targets: hollow style, FPF in red,
        and includes scheduled time so the FDC can plan H-hour coverage.
        """
        out = []
        for t in self.peloton.fire_plan:
            lat, lon = _latlon(t.position)
            entry: dict = {
                "name": t.name,
                "lat": lat, "lon": lon,
                "mgrs": t.position.to_mgrs(),
                "type": t.target_type,
                "sheaf": t.sheaf,
                "shell": t.shell,
                "fuze": t.fuze,
                "rounds": t.rounds_per_piece,
                "description": t.description,
                "is_fpf": bool(t.is_fpf),
                "suggested_group": t.suggested_group or None,
                "timing": t.offset_label(),
                "duration_min": t.duration_min,
            }
            sched = t.scheduled_start(self.peloton.h_hour)
            entry["scheduled"] = (
                sched.astimezone().strftime("%H:%M:%S") if sched else None
            )
            # Linear targets / sheafs get two endpoints for a polyline
            from ..firemission.mission import TargetType as _TT, Sheaf as _Sh
            is_linear = (
                t.target_type == _TT.LINEAR.value
                or t.sheaf == _Sh.LINEAR.value
            )
            if is_linear and t.line_length_m > 0:
                half = t.line_length_m / 2.0
                az = t.line_azimuth_mils
                end_a = offset(t.position, az, half)
                end_b = offset(t.position, (az + 3200.0) % 6400.0, half)
                a_lat, a_lon = _latlon(end_a)
                b_lat, b_lon = _latlon(end_b)
                entry["line"] = {
                    "a_lat": a_lat, "a_lon": a_lon,
                    "b_lat": b_lat, "b_lon": b_lon,
                    "length_m": t.line_length_m,
                    "azimuth_mils": t.line_azimuth_mils,
                }
            out.append(entry)
        return out

    # ---------- per-piece range rings ----------
    def _ammo_legend(self) -> list[dict]:
        """Color key used for both per-piece rings and per-section arcs."""
        if not self.library:
            return []
        out = []
        for i, shell in enumerate(self.library.shells()):
            lo, hi = self.library.tables[shell].range_span_m
            out.append({
                "shell": shell,
                "color": AMMO_COLORS[i % len(AMMO_COLORS)],
                "min_m": lo, "max_m": hi,
            })
        return out

    def _piece_ranges(self) -> list[dict]:
        """For each piece, per-shell max/min range so each gun's envelope is
        immediately visible from its own position. The piece's section caps
        the maximum range if a `max_range_m` is set on that section."""
        if not self.library or not self.peloton.pieces:
            return []
        bands = self._ammo_legend()
        out = []
        for p in self.peloton.pieces:
            lat, lon = _latlon(p.position)
            g = self.peloton.group_of(p.name)
            cap = g.max_range_m if g is not None else 0.0
            out.append({
                "name": p.name,
                "lat": lat, "lon": lon,
                "is_base": p.is_base,
                "group": g.name if g is not None else None,
                "bands": [
                    {"shell": b["shell"], "color": b["color"],
                     "min_m": b["min_m"],
                     "max_m": min(b["max_m"], cap) if cap > 0 else b["max_m"]}
                    for b in bands
                ],
            })
        return out

    # ---------- range sectors ("pies") ----------
    def _centroid_pos(self, names) -> Position | None:
        pts = [p.position for p in self.peloton.pieces if p.name in names]
        if not pts:
            return None
        ref = self.peloton.pieces[0].position
        return Position(
            easting=sum(q.easting for q in pts) / len(pts),
            northing=sum(q.northing for q in pts) / len(pts),
            zone=ref.zone, hemisphere=ref.hemisphere,
        )

    @staticmethod
    def _arc_latlon(center: Position, radius_m: float,
                    start_mils: float, sweep_mils: float) -> list[list[float]]:
        n = max(2, int(sweep_mils / 100) + 1)
        out = []
        for k in range(n + 1):
            az = (start_mils + sweep_mils * k / n) % 6400.0
            lat, lon = _latlon(offset(center, az, radius_m))
            out.append([lat, lon])
        return out

    def _range_sectors(self) -> list[dict]:
        """Per-section coverage sectors (min/max arcs per ammunition, clipped to
        the section's left/right limits). Sections without limits → full rings;
        no sections at all → one unrestricted entry on the battery centroid."""
        if not self.library or not self.peloton.pieces:
            return []
        bands_def = []
        for i, shell in enumerate(self.library.shells()):
            lo, hi = self.library.tables[shell].range_span_m
            bands_def.append((shell, lo, hi, AMMO_COLORS[i % len(AMMO_COLORS)]))
        if not bands_def:
            return []
        overall_max = max(hi for _, _, hi, _ in bands_def)

        sections = [g for g in self.peloton.groups if self._centroid_pos(g.member_names)]
        if not sections:
            center = self._centroid_pos([p.name for p in self.peloton.pieces])
            battery = Group(name="Battery")  # unlimited (full rings)
            return [self._sector_entry(battery, 0, center, bands_def, overall_max)]
        out = []
        for gi, g in enumerate(self.peloton.groups):
            center = self._centroid_pos(g.member_names)
            if center is None:
                continue
            out.append(self._sector_entry(g, gi, center, bands_def, overall_max))
        return out

    def _sector_entry(self, group: Group, gi: int, center: Position,
                      bands_def, overall_max: float) -> dict:
        clat, clon = _latlon(center)
        left = group.left_limit_mils
        sweep = group.sector_width_mils()
        limited = group.has_limits()
        # Section's max-range cap overrides any larger band.
        cap = group.max_range_m
        capped_bands = [
            (shell, lo, min(hi, cap) if cap > 0 else hi, color)
            for shell, lo, hi, color in bands_def
        ]
        capped_overall_max = min(overall_max, cap) if cap > 0 else overall_max
        entry: dict = {
            "section": group.name,
            "color": SECTION_COLORS[gi % len(SECTION_COLORS)],
            "limited": limited,
            "center": [clat, clon],
            "bands": [], "fill": [], "limit_lines": [],
            "max_range_m": cap if cap > 0 else None,
        }
        for shell, lo, hi, color in capped_bands:
            band = {"shell": shell, "color": color,
                    "max_m": hi, "min_m": lo,
                    "max_arc": self._arc_latlon(center, hi, left, sweep)}
            # Per-shell wedge ("pie") for this section — gives the user filled
            # wedges per shell that respect the sector limits, not just open arcs.
            if limited:
                band["wedge"] = (
                    [[clat, clon]]
                    + self._arc_latlon(center, hi, left, sweep)
                    + [[clat, clon]]
                )
            if lo > 0:
                band["min_arc"] = self._arc_latlon(center, lo, left, sweep)
            # Mid-azimuth point at the max-range arc — for a permanent label.
            mid = (left + sweep / 2.0) % 6400.0
            mlat, mlon = _latlon(offset(center, mid, hi))
            band["label_at"] = [mlat, mlon]
            entry["bands"].append(band)
        if limited:
            entry["fill"] = (
                [[clat, clon]]
                + self._arc_latlon(center, capped_overall_max, left, sweep)
                + [[clat, clon]]
            )
            for az in (left, (left + sweep) % 6400.0):
                elat, elon = _latlon(offset(center, az, capped_overall_max))
                entry["limit_lines"].append([[clat, clon], [elat, elon]])
        return entry

    # ---------- cleanup ----------
    def closeEvent(self, event) -> None:  # noqa: N802
        self._tile_server.shutdown()
        super().closeEvent(event)
