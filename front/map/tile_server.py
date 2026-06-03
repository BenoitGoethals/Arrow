"""Local HTTP server — serves MBTiles offline map tiles AND the map HTML page.

Serving map.html via http://127.0.0.1 instead of file:// fixes the Qt6/macOS
Metal compositor black-screen bug: the file:// protocol uses a different
compositing code-path that cannot composite CSS overlays over the Leaflet map
without losing the GPU framebuffer.

Routes
------
/ping                  → health check
/map                   → map.html
/lib/<file>            → front/map/html/lib/<file>  (Leaflet, milsymbol, mgrs, ...)
/qwebchannel.js        → qwebchannel.js (injected by Qt, but kept here as fallback)
/{z}/{x}/{y}.png       → MBTiles tile (when an MBTiles file is loaded)
"""
from __future__ import annotations

import mimetypes
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

_HTML_DIR = Path(__file__).parent / "html"


class _Handler(BaseHTTPRequestHandler):
    # ── routing ──────────────────────────────────────────────────────────────

    def do_GET(self):
        path = self.path.split("?")[0]   # strip query string

        if path == "/ping":
            return self._text(200, "pong")

        if path in ("/map", "/map.html", "/"):
            return self._file(_HTML_DIR / "map.html")

        if path.startswith("/lib/"):
            return self._file(_HTML_DIR / path.lstrip("/"))

        if path == "/qwebchannel.js":
            return self._file(_HTML_DIR / "qwebchannel.js")

        # MBTiles tile: /{z}/{x}/{y}.png
        try:
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                z, x = int(parts[0]), int(parts[1])
                y    = int(parts[2].split(".")[0])
                tms_y = (1 << z) - 1 - y
                tile = self.server._mbtiles_server.get_tile(z, x, tms_y)  # type: ignore
                if tile:
                    return self._bytes(200, tile, "image/png")
                return self._bytes(204, b"", "image/png")
        except Exception:
            pass

        self._text(404, "not found")

    def do_OPTIONS(self):
        self._text(200, "")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _file(self, p: Path):
        if not p.exists():
            return self._text(404, f"not found: {p.name}")
        mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        self._bytes(200, p.read_bytes(), mime)

    def _text(self, code: int, body: str):
        self._bytes(code, body.encode(), "text/plain")

    def _bytes(self, code: int, body: bytes, mime: str = "application/octet-stream"):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, *args):
        pass  # suppress access log


# ─────────────────────────────────────────────────────────────────────────────

class MBTilesDB:
    def __init__(self, path: str):
        self._path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        meta = dict(self._conn.execute("SELECT name, value FROM metadata").fetchall())
        self.name     = meta.get("name", Path(path).stem)
        self.min_zoom = int(meta.get("minzoom", 0))
        self.max_zoom = int(meta.get("maxzoom", 18))
        self.format   = meta.get("format", "png")

    def get_tile(self, z: int, x: int, tms_y: int) -> Optional[bytes]:
        with self._lock:
            row = self._conn.execute(
                "SELECT tile_data FROM tiles "
                "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, x, tms_y),
            ).fetchone()
        return row[0] if row else None

    def close(self):
        self._conn.close()


class MBTilesServer:
    """HTTP server that serves map.html, Leaflet assets, and MBTile data."""

    def __init__(self, port: int = 8743):
        self._port  = port
        self._db:    Optional[MBTilesDB]  = None
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ── MBTiles ──────────────────────────────────────────────────────────────

    def load(self, path: str) -> str:
        if self._db:
            self._db.close()
        self._db = MBTilesDB(path)
        return self.tile_url

    def unload(self):
        if self._db:
            self._db.close()
            self._db = None

    @property
    def tile_url(self) -> str:
        return f"http://127.0.0.1:{self._port}/{{z}}/{{x}}/{{y}}.png"

    @property
    def map_url(self) -> str:
        return f"http://127.0.0.1:{self._port}/map"

    @property
    def loaded(self) -> bool:
        return self._db is not None

    @property
    def db(self) -> Optional[MBTilesDB]:
        return self._db

    def get_tile(self, z: int, x: int, tms_y: int) -> Optional[bytes]:
        return self._db.get_tile(z, x, tms_y) if self._db else None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> int:
        server = HTTPServer(("127.0.0.1", self._port), _Handler)
        server._mbtiles_server = self   # type: ignore[attr-defined]
        self._httpd  = server
        self._thread = threading.Thread(
            target=server.serve_forever, daemon=True, name="map-http"
        )
        self._thread.start()
        return self._port

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None
