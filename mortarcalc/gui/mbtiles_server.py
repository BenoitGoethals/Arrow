"""Lokale HTTP-tegelserver voor MBTiles — voor offline kaart in QtWebEngine.

MBTiles is een SQLite-bestand met (zoom_level, tile_column, tile_row, tile_data).
Y is opgeslagen in TMS-conventie (oorsprong onderaan); Leaflet/XYZ verwacht
oorsprong bovenaan. We flippen Y bij het uitserveren.
"""
from __future__ import annotations

import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class MBTilesStore:
    """Read-only toegang tot een MBTiles-bestand (thread-safe via per-thread connecties)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._local = threading.local()
        # metadata eenmaal laden (en valideren dat het echt MBTiles is)
        conn = sqlite3.connect(str(path))
        try:
            rows = conn.execute("SELECT name, value FROM metadata").fetchall()
        except sqlite3.DatabaseError as e:
            conn.close()
            raise ValueError(f"Geen geldig MBTiles-bestand: {path} ({e})") from e
        finally:
            conn.close()
        self.metadata = {k: v for k, v in rows}
        self.tile_format = self.metadata.get("format", "png").lower()

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(str(self.path), check_same_thread=False)
            self._local.conn = c
        return c

    def tile(self, z: int, x: int, y: int) -> bytes | None:
        # XYZ → TMS Y-flip
        tms_y = (1 << z) - 1 - y
        row = self._conn().execute(
            "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
            (z, x, tms_y),
        ).fetchone()
        return row[0] if row else None

    def content_type(self) -> str:
        f = self.tile_format
        if f in ("jpg", "jpeg"):
            return "image/jpeg"
        if f == "webp":
            return "image/webp"
        if f == "pbf":
            return "application/x-protobuf"
        return "image/png"


class _Handler(BaseHTTPRequestHandler):
    store: MBTilesStore | None = None

    # silence default logging to stderr
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        store = self.server.store  # type: ignore[attr-defined]
        if store is None:
            self.send_error(503, "no MBTiles loaded")
            return
        # verwacht /{z}/{x}/{y}.{ext}
        parts = self.path.strip("/").split("?")[0].split("/")
        if len(parts) != 3:
            self.send_error(404)
            return
        try:
            z = int(parts[0])
            x = int(parts[1])
            y_part = parts[2].rsplit(".", 1)[0]
            y = int(y_part)
        except ValueError:
            self.send_error(400, "bad tile path")
            return
        data = store.tile(z, x, y)
        if data is None:
            self.send_error(404, "tile not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", store.content_type())
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=86400")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)


class TileServer:
    """Achtergrond-HTTP-server die MBTiles-tegels uitlevert op 127.0.0.1."""

    def __init__(self) -> None:
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._store: MBTilesStore | None = None

    @property
    def store(self) -> MBTilesStore | None:
        return self._store

    @property
    def port(self) -> int | None:
        return self._httpd.server_address[1] if self._httpd else None

    @property
    def url_template(self) -> str | None:
        if self._httpd is None:
            return None
        ext = self._store.tile_format if self._store else "png"
        return f"http://127.0.0.1:{self.port}/{{z}}/{{x}}/{{y}}.{ext}"

    def load(self, path: Path) -> None:
        """Vervang de actieve MBTiles. Start de server indien nog niet gestart."""
        self._store = MBTilesStore(path)
        if self._httpd is None:
            self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
            self._thread = threading.Thread(
                target=self._httpd.serve_forever,
                name="mc-mbtiles",
                daemon=True,
            )
            self._thread.start()
        self._httpd.store = self._store  # type: ignore[attr-defined]

    def shutdown(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            self._thread = None
        self._store = None
