"""Local HTTP server — serves MBTiles offline map tiles AND the map HTML page.

Routes
------
/ping                       → health check
/map                        → map.html
/lib/<file>                 → front/map/html/lib/<file>  (Leaflet, milsymbol, mgrs, ...)
/qwebchannel.js             → qwebchannel.js
/{mbt_id}/{z}/{x}/{y}.png   → MBTiles tile for the given layer id
"""

from __future__ import annotations

import mimetypes
import sqlite3
import threading
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

_HTML_DIR = Path(__file__).parent / "html"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/ping":
            return self._text(200, "pong")

        if path in ("/map", "/map.html", "/"):
            return self._file(_HTML_DIR / "map.html")

        if path.startswith("/lib/"):
            return self._file(_HTML_DIR / path.lstrip("/"))

        if path == "/qwebchannel.js":
            return self._file(_HTML_DIR / "qwebchannel.js")

        # MBTiles tile: /{mbt_id}/{z}/{x}/{y}.png
        try:
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                mbt_id = parts[0]
                z, x = int(parts[1]), int(parts[2])
                y = int(parts[3].split(".")[0])
                tms_y = (1 << z) - 1 - y
                srv: MBTilesServer = self.server._mbtiles_server  # type: ignore
                tile = srv.get_tile(mbt_id, z, x, tms_y)
                if tile:
                    return self._bytes(200, tile, srv.tile_mime(mbt_id))
                return self._bytes(204, b"", srv.tile_mime(mbt_id))
        except Exception:
            pass

        self._text(404, "not found")

    def do_OPTIONS(self):
        self._text(200, "")

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
        # No-store so QtWebEngine's persistent disk cache can never serve a
        # stale map.html / lib asset across restarts — edits always take effect.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            # A client (QtWebEngine/Chromium) may close a speculative or
            # superseded connection mid-write; that surfaces as a benign
            # ConnectionAbortedError/BrokenPipe — swallow it instead of letting
            # the threading server dump a traceback.
            try:
                self.wfile.write(body)
            except ConnectionError, OSError:
                pass

    def log_message(self, *args):
        pass


class MBTilesDB:
    def __init__(self, path: str):
        self._path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        meta = dict(self._conn.execute("SELECT name, value FROM metadata").fetchall())
        self.name = meta.get("name", Path(path).stem)
        self.min_zoom = int(meta.get("minzoom", 0))
        self.max_zoom = int(meta.get("maxzoom", 18))
        self.format = meta.get("format", "png")

    def get_tile(self, z: int, x: int, tms_y: int) -> Optional[bytes]:
        with self._lock:
            row = self._conn.execute(
                "SELECT tile_data FROM tiles "
                "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, x, tms_y),
            ).fetchone()
        return row[0] if row else None

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


class MBTilesServer:
    """HTTP server that serves map.html, Leaflet assets, and MBTile data.

    Multiple MBTiles files are supported simultaneously; each gets a short UUID
    as its URL prefix: http://127.0.0.1:{port}/{mbt_id}/{z}/{x}/{y}.png
    """

    def __init__(self, port: int = 8743):
        self._port = port
        self._dbs: dict[str, MBTilesDB] = {}  # mbt_id → db
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ── MBTiles ──────────────────────────────────────────────────────────────

    def load(self, path: str) -> tuple[str, str, int, int, str]:
        """Load an MBTiles file.  Returns (mbt_id, tile_url, min_zoom, max_zoom, name)."""
        # Reuse if already loaded
        for mbt_id, db in self._dbs.items():
            if db._path == path:
                return mbt_id, self._tile_url(mbt_id), db.min_zoom, db.max_zoom, db.name
        db = MBTilesDB(path)
        mbt_id = uuid.uuid4().hex[:8]
        self._dbs[mbt_id] = db
        return mbt_id, self._tile_url(mbt_id), db.min_zoom, db.max_zoom, db.name

    def unload(self, mbt_id: str):
        db = self._dbs.pop(mbt_id, None)
        if db:
            db.close()

    def unload_all(self):
        for db in self._dbs.values():
            db.close()
        self._dbs.clear()

    def get_tile(self, mbt_id: str, z: int, x: int, tms_y: int) -> Optional[bytes]:
        db = self._dbs.get(mbt_id)
        return db.get_tile(z, x, tms_y) if db else None

    def tile_mime(self, mbt_id: str) -> str:
        """Content-Type for a layer's tiles, honouring the MBTiles image format
        (JPEG atlases exist alongside PNG ones)."""
        db = self._dbs.get(mbt_id)
        fmt = (db.format if db else "png").lower()
        return "image/jpeg" if fmt in ("jpg", "jpeg") else "image/png"

    def _tile_url(self, mbt_id: str) -> str:
        return f"http://127.0.0.1:{self._port}/{mbt_id}/{{z}}/{{x}}/{{y}}.png"

    @property
    def map_url(self) -> str:
        return f"http://127.0.0.1:{self._port}/map"

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> int:
        # ThreadingHTTPServer (not HTTPServer): Chromium opens speculative /
        # preconnect sockets while loading the page. A single-threaded server
        # blocks its only thread reading a request that never arrives on such a
        # socket, starving the real leaflet.js / milsymbol.js requests — the page
        # then renders with `L` undefined ("Leaflet not loaded"). One thread per
        # connection keeps asset loads from stalling each other.
        server = ThreadingHTTPServer(("127.0.0.1", self._port), _Handler)
        server.daemon_threads = True
        server._mbtiles_server = self  # type: ignore[attr-defined]
        self._httpd = server
        self._thread = threading.Thread(
            target=server.serve_forever, daemon=True, name="map-http"
        )
        self._thread.start()
        return self._port

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None
