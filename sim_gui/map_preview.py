"""Map preview pane — a QWebEngineView hosting a small Leaflet HTML.

The view re-centres on the selected scenario's AOR. If the backend URL + JWT
are available, it also opens a WebSocket to `/ws?token=…` and drops a simple
coloured marker for every `tactical-object` and `alert` event so the operator
can watch the scenario populate without leaving the launcher.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Arrow Sim Map</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    html,body,#map {height:100%;margin:0;padding:0;background:#0f1419;color:#e2e8f0;
                    font-family:-apple-system,'SF Pro Text','Inter',sans-serif;}
    .leaflet-control-attribution {background:rgba(15,20,25,0.85)!important; color:#94a3b8!important;
                                  font-size:10px!important;}
    .leaflet-control-attribution a {color:#38bdf8!important;}
    .leaflet-control-zoom a {background:#161b22!important; color:#e2e8f0!important;
                             border-color:#2a323d!important;}
    .leaflet-control-zoom a:hover {background:#1f2630!important;}
  </style>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/milsymbol@3.0.1/dist/milsymbol.js"></script>
</head>
<body>
  <div id="map"></div>
  <script>
    const map = L.map('map', {zoomControl: true, attributionControl: true}).setView([50.0, 4.0], 5);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
        attribution: '© OSM · © CARTO',
        subdomains: 'abcd',
    }).addTo(map);

    // Per-channel layers.
    const tacticalLayer = L.layerGroup().addTo(map);
    const trackingLayer = L.layerGroup().addTo(map);
    const vehicleLayer  = L.layerGroup().addTo(map);
    const eventLayer    = L.layerGroup().addTo(map);
    const fmLayer       = L.layerGroup().addTo(map);

    // Sticky markers keyed by id.
    const tacticalMarkers = new Map();  // tactical_object_id → marker
    const opMarkers       = new Map();  // operator_id        → marker
    const vehMarkers      = new Map();  // vehicle_id         → marker
    let socket = null;

    function setCentre(lat, lng, zoom) { map.setView([lat, lng], zoom || 13); }
    function clearOverlay() {
      tacticalLayer.clearLayers(); trackingLayer.clearLayers();
      vehicleLayer.clearLayers();  eventLayer.clearLayers();
      fmLayer.clearLayers();
      tacticalMarkers.clear(); opMarkers.clear(); vehMarkers.clear();
    }

    // ── MIL-STD-2525 rendering via milsymbol.js ────────────────────────────
    const HAS_MS = typeof ms !== 'undefined' && ms && typeof ms.Symbol === 'function';

    // CoT type → SIDC mapping. Defaults to friendly ground combat infantry.
    function affChar(aff) {
      if (!aff) return 'F';
      if (aff === 'ENEMY' || aff === 'HOSTILE') return 'H';
      if (aff === 'UNKNOWN') return 'U';
      if (aff === 'NEUTRAL') return 'N';
      return 'F';
    }
    function cotToSidc(cot, fallback) {
      if (!cot) return fallback || 'SFGPUCI------';
      const parts = cot.split('-');
      if (parts[0] !== 'a' || parts.length < 2) return fallback || 'SFGPUCI------';
      const aff = (parts[1] || 'f').toUpperCase();
      const dim = (parts[2] || 'G').toUpperCase(); // G,S,A,P
      // a-f-G-U-C-I  →  S F G P U C I ------
      // a-f-G-U-C-A  →  S F G P U C A ------
      const rest = parts.slice(3).join('').toUpperCase();
      const body = (rest || 'UCI').padEnd(6, '-');
      return 'S' + aff + dim + 'P' + body.slice(0, 6);
    }

    // milsymbol caches by (sidc, callsign) — symbol creation is expensive.
    const symCache = new Map();
    function makeMilIcon(sidc, callsign, size) {
      const key = sidc + '|' + (callsign || '') + '|' + (size || 26);
      let cached = symCache.get(key);
      if (cached) return cached;
      try {
        const sym = new ms.Symbol(sidc, {
          size: size || 26,
          uniqueDesignation: callsign || '',
          infoBackground: '#0f1419CC',
          infoColor: '#e2e8f0',
          outlineColor: '#0f1419',
          outlineWidth: 2,
          monoColor: undefined,
        });
        const w = sym.getSize().width;
        const h = sym.getSize().height;
        const anchor = sym.getAnchor();
        const icon = L.divIcon({
          className: 'mil-icon',
          html: sym.asSVG(),
          iconSize: [w, h],
          iconAnchor: [anchor.x, anchor.y],
        });
        symCache.set(key, icon);
        return icon;
      } catch (e) {
        return null;
      }
    }

    function colorFor(aff) {
      if (aff === 'ENEMY')   return '#ef4444';
      if (aff === 'UNKNOWN') return '#f59e0b';
      return '#38bdf8';
    }

    function upsertMil(map_, id, layer, lat, lng, sidc, callsign, size) {
      let m = map_.get(id);
      const icon = HAS_MS ? makeMilIcon(sidc, callsign, size) : null;
      if (!m) {
        if (icon) {
          m = L.marker([lat, lng], {icon: icon}).addTo(layer);
        } else {
          // Fallback: coloured dot keyed off affiliation char.
          const ac = sidc && sidc[1];
          const color = (ac === 'H') ? '#ef4444' :
                        (ac === 'U') ? '#f59e0b' :
                        (ac === 'N') ? '#a3a3a3' : '#38bdf8';
          m = L.circleMarker([lat, lng], {radius: 6, color: color,
                              fillColor: color, fillOpacity: 0.85,
                              weight: 1.5}).addTo(layer);
        }
        if (callsign) m.bindTooltip(callsign);
        map_.set(id, m);
      } else {
        m.setLatLng([lat, lng]);
        if (icon && m.setIcon) m.setIcon(icon);
      }
      return m;
    }

    function tempMarker(lat, lng, layer, opts, tip, ttlMs) {
      const m = L.circleMarker([lat, lng], opts).addTo(layer);
      if (tip) m.bindTooltip(tip);
      setTimeout(() => { try { layer.removeLayer(m); } catch(_){} }, ttlMs || 8000);
      return m;
    }

    function isPointType(t) {
      // Polygon/line tactical-objects don't render well as point icons.
      if (!t) return true;
      return !(t === 'OBJ_AREA' || t === 'BOUNDARY' || t === 'PHASE_LINE' ||
               t === 'FLOT' || t === 'FLET' || t === 'ROUTE');
    }
    function tacticalSidc(d) {
      // Prefer the row's stored SIDC; else derive a sensible default per type+aff.
      if (d.symbol_code && d.symbol_code.length >= 10) return d.symbol_code;
      const aff = affChar(d.affiliation);
      if (d.type === 'ENEMY') return 'S' + aff + 'GPUCI------';
      if (d.type === 'POI' || d.type === 'MARKER') return 'S' + aff + 'GPI-------';
      return 'S' + aff + 'GPUCI------';
    }

    function onMessage(m) {
      const d = m.data || {};
      const ch = m.channel;
      if (ch === 'tactical-object') {
        if (m.event === 'deleted' && d.id != null) {
          const mk = tacticalMarkers.get(d.id);
          if (mk) { tacticalLayer.removeLayer(mk); tacticalMarkers.delete(d.id); }
          return;
        }
        if (d.latitude == null || d.longitude == null) return;
        if (!isPointType(d.type)) return;  // line/poly graphics: skip for now
        const sidc = tacticalSidc(d);
        const tip  = (d.type || '') + ' · ' + (d.notes || '');
        upsertMil(tacticalMarkers, d.id, tacticalLayer,
                  d.latitude, d.longitude, sidc, d.notes || d.type, 30);
        const mk = tacticalMarkers.get(d.id);
        if (mk) mk.bindTooltip(tip);
      } else if (ch === 'tracking' && d.latitude != null && d.longitude != null) {
        const sidc = cotToSidc(d.cot_type, 'SFGPUCI------');
        upsertMil(opMarkers, d.operator_id || d.callsign, trackingLayer,
                  d.latitude, d.longitude, sidc, d.callsign, 22);
      } else if (ch === 'vehicle' && d.latitude != null && d.longitude != null) {
        const sidc = (d.symbol_code && d.symbol_code.length >= 10)
                     ? d.symbol_code : 'SFGPEVU------';
        upsertMil(vehMarkers, d.id, vehicleLayer,
                  d.latitude, d.longitude, sidc, d.callsign, 26);
      } else if (ch === 'alert' && d.latitude != null && d.longitude != null) {
        tempMarker(d.latitude, d.longitude, eventLayer,
                   {radius:11, color:'#ef4444', fillColor:'#ef4444',
                    fillOpacity:0.7, weight:2},
                   'ALERT ' + (d.type || ''), 12000);
      } else if (ch === 'report' && d.latitude != null && d.longitude != null) {
        tempMarker(d.latitude, d.longitude, eventLayer,
                   {radius:7, color:'#f59e0b', fillColor:'#f59e0b',
                    fillOpacity:0.7, weight:1},
                   'REPORT ' + (d.type || ''), 12000);
      } else if (ch === 'fire-mission' && d.latitude != null && d.longitude != null) {
        tempMarker(d.latitude, d.longitude, fmLayer,
                   {radius:12, color:'#fb923c', fillColor:'#fb923c',
                    fillOpacity:0.6, weight:2},
                   'FM ' + (d.mission_type || '') + ' ' + (d.ammunition || ''),
                   15000);
      } else if (ch === 'cas') {
        if (d.line_5_lat != null && d.line_5_lon != null) {
          tempMarker(d.line_5_lat, d.line_5_lon, fmLayer,
                     {radius:13, color:'#e879f9', fillColor:'#a21caf',
                      fillOpacity:0.6, weight:2},
                     'CAS · ' + (d.line_6 || ''), 18000);
        }
      }
    }

    function connectWs(wsUrl) {
      if (socket) { try { socket.close(); } catch(_) {} }
      try {
        socket = new WebSocket(wsUrl);
        socket.onmessage = (ev) => {
          try { onMessage(JSON.parse(ev.data)); } catch (_) {}
        };
      } catch (e) { /* ignore */ }
    }
  </script>
</body>
</html>
"""


class MapPreview(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._view = QWebEngineView()
        self._view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._view.setHtml(_HTML, QUrl("about:blank"))
        layout.addWidget(self._view)
        self._loaded = False
        self._view.loadFinished.connect(self._on_load)

    def _on_load(self, ok: bool) -> None:
        self._loaded = bool(ok)

    def centre_on(self, lat: float, lon: float, zoom: int) -> None:
        if not self._loaded:
            # Defer until the page finishes loading.
            self._view.loadFinished.connect(
                lambda _ok, ll=(lat, lon, zoom): self._centre_now(*ll)
            )
            return
        self._centre_now(lat, lon, zoom)

    def _run_js(self, js: str) -> None:
        page = self._view.page()
        if page is not None:
            page.runJavaScript(js)

    def _centre_now(self, lat: float, lon: float, zoom: int) -> None:
        self._run_js(f"setCentre({lat}, {lon}, {zoom});")

    def clear_overlay(self) -> None:
        if self._loaded:
            self._run_js("clearOverlay();")

    def subscribe(self, base_url: str, token: str) -> None:
        """Open the backend WebSocket so injects appear live."""
        if not token or not self._loaded:
            return
        parts = urlsplit(base_url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        path_prefix = (parts.path or "").rstrip("/")
        ws_url = f"{scheme}://{parts.netloc}{path_prefix}/ws?token={token}"
        # Strip back-ticks just in case; we control the input but be safe.
        ws_url = ws_url.replace("`", "")
        self._run_js(f"connectWs(`{ws_url}`);")
