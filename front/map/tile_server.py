"""Local HTTP tile server for MBTiles offline maps.

Serves tiles at: http://127.0.0.1:{port}/{z}/{x}/{y}.png
MBTiles uses TMS y-axis (flipped), this server handles the conversion.
"""
from __future__ import annotations
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional


class _TileHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ping":
            self._respond(200, b"pong", "text/plain")
            return
        try:
            parts = self.path.strip("/").split("/")
            z, x, y_png = int(parts[0]), int(parts[1]), parts[2]
            y = int(y_png.replace(".png", "").replace(".jpg", ""))
            tms_y = (1 << z) - 1 - y  # flip y for MBTiles TMS convention
            tile = self.server.mbtiles.get_tile(z, x, tms_y)
            if tile:
                self._respond(200, tile, "image/png")
            else:
                self._respond(204, b"", "image/png")
        except Exception:
            self._respond(400, b"", "text/plain")

    def do_OPTIONS(self):
        self._respond(200, b"", "text/plain")

    def _respond(self, code: int, body: bytes, mime: str):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, *args):
        pass  # suppress access log noise


class MBTilesDB:
    def __init__(self, path: str):
        self._path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()

        # Read metadata
        meta = dict(self._conn.execute("SELECT name, value FROM metadata").fetchall())
        self.name      = meta.get("name", Path(path).stem)
        self.min_zoom  = int(meta.get("minzoom", 0))
        self.max_zoom  = int(meta.get("maxzoom", 18))
        self.format    = meta.get("format", "png")

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
    """Manage a single local HTTP tile server that can swap MBTiles databases."""

    def __init__(self, port: int = 8743):
        self._port = port
        self._db: Optional[MBTilesDB] = None
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ---- MBTiles file management -----------------------------------------

    def load(self, path: str) -> str:
        """Load an MBTiles file. Returns the tile URL template."""
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
    def loaded(self) -> bool:
        return self._db is not None

    @property
    def db(self) -> Optional[MBTilesDB]:
        return self._db

    def get_tile(self, z: int, x: int, tms_y: int) -> Optional[bytes]:
        return self._db.get_tile(z, x, tms_y) if self._db else None

    # ---- HTTP server lifecycle -------------------------------------------

    def start(self) -> int:
        """Start the tile server thread. Returns the port number."""
        server = HTTPServer(("127.0.0.1", self._port), _TileHandler)
        server.mbtiles = self  # type: ignore[attr-defined]
        self._httpd = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        return self._port

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None
