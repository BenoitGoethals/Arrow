"""LocalStore — SQLite-backed store for LOCAL drawing layers and their elements.

A *layer* groups drawn elements (tactical graphics, MIL-STD-2525 symbols,
free-draw). A local layer lives only on this device; its elements are rendered
again on launch and can be pushed to the server later via "Distribute" (each
element is replayed through ``ArrowClient.post_tactical_object`` into a server
overlay). Distributed layers ARE server overlays and are not stored here.

Elements may also be saved loose (``layer_id = NULL``) — the "Map · Local"
target. Each element holds exactly the fields ``post_tactical_object`` needs,
so distribution is a straight replay. Rendered elements get a STRING id of the
form ``"L<rowid>"`` which never collides with the integer ids the server
assigns — the map JS keys on ``obj.id`` either way.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class LocalStore:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            path = Path.home() / ".arrow_front" / "local_objects.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        # check_same_thread=False: the Qt GUI thread is the only writer, but the
        # connection may be touched from signal callbacks dispatched elsewhere.
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS local_layers ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "name TEXT NOT NULL, "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS local_objects ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "layer_id INTEGER, "
            "obj_type TEXT NOT NULL, "
            "geometry TEXT NOT NULL DEFAULT '', "
            "notes TEXT NOT NULL DEFAULT '', "
            "affiliation TEXT NOT NULL DEFAULT 'UNKNOWN', "
            "symbol_code TEXT NOT NULL DEFAULT '', "
            "echelon TEXT NOT NULL DEFAULT '', "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        # Migrate a v1 objects table (no layer_id column) in place.
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(local_objects)")]
        if "layer_id" not in cols:
            self._conn.execute("ALTER TABLE local_objects ADD COLUMN layer_id INTEGER")
        self._conn.commit()

    # ---- layers ---------------------------------------------------------
    def create_layer(self, name: str) -> dict:
        cur = self._conn.execute(
            "INSERT INTO local_layers(name) VALUES (?)", (name or "Layer",)
        )
        self._conn.commit()
        return self.layer(int(cur.lastrowid or 0))

    def rename_layer(self, layer_id: int, name: str) -> None:
        self._conn.execute(
            "UPDATE local_layers SET name = ? WHERE id = ?",
            (name or "Layer", layer_id),
        )
        self._conn.commit()

    def delete_layer(self, layer_id: int) -> None:
        """Delete a layer and every element it owns."""
        self._conn.execute("DELETE FROM local_objects WHERE layer_id = ?", (layer_id,))
        self._conn.execute("DELETE FROM local_layers WHERE id = ?", (layer_id,))
        self._conn.commit()

    def layer(self, layer_id: int) -> dict:
        row = self._conn.execute(
            "SELECT id, name FROM local_layers WHERE id = ?", (layer_id,)
        ).fetchone()
        if not row:
            return {}
        return {"id": int(row[0]), "name": row[1], "count": self._layer_count(row[0])}

    def list_layers(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name FROM local_layers ORDER BY id"
        ).fetchall()
        return [
            {"id": int(r[0]), "name": r[1], "count": self._layer_count(r[0])}
            for r in rows
        ]

    def _layer_count(self, layer_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM local_objects WHERE layer_id = ?", (layer_id,)
        ).fetchone()
        return int(row[0]) if row else 0

    # ---- elements -------------------------------------------------------
    def add(
        self,
        obj_type: str,
        geometry: dict,
        notes: str = "",
        affiliation: str = "UNKNOWN",
        symbol_code: str = "",
        echelon: str = "",
        layer_id: int | None = None,
    ) -> dict:
        """Insert one element; returns its render-ready dict (with string id)."""
        cur = self._conn.execute(
            "INSERT INTO local_objects"
            "(layer_id, obj_type, geometry, notes, affiliation, symbol_code, echelon) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                layer_id,
                obj_type,
                json.dumps(geometry or {}),
                notes or "",
                affiliation or "UNKNOWN",
                symbol_code or "",
                echelon or "",
            ),
        )
        self._conn.commit()
        return self.get(int(cur.lastrowid or 0))

    def delete(self, rowid: int) -> None:
        self._conn.execute("DELETE FROM local_objects WHERE id = ?", (rowid,))
        self._conn.commit()

    def clear(self) -> None:
        """Wipe ALL local layers and elements (full reset)."""
        self._conn.execute("DELETE FROM local_objects")
        self._conn.execute("DELETE FROM local_layers")
        self._conn.commit()

    # ---- reads ----------------------------------------------------------
    _COLS = "id, layer_id, obj_type, geometry, notes, affiliation, symbol_code, echelon"

    def get(self, rowid: int) -> dict:
        row = self._conn.execute(
            f"SELECT {self._COLS} FROM local_objects WHERE id = ?", (rowid,)
        ).fetchone()
        return self._row_to_dict(row) if row else {}

    def all(self) -> list[dict]:
        rows = self._conn.execute(
            f"SELECT {self._COLS} FROM local_objects ORDER BY id"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def objects_for_layer(self, layer_id: int) -> list[dict]:
        rows = self._conn.execute(
            f"SELECT {self._COLS} FROM local_objects WHERE layer_id = ? ORDER BY id",
            (layer_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM local_objects").fetchone()
        return int(row[0]) if row else 0

    # ---- helpers --------------------------------------------------------
    @staticmethod
    def _row_to_dict(row: Any) -> dict:
        rid, layer_id, obj_type, geometry, notes, aff, sidc, ech = row
        try:
            geom = json.loads(geometry) if geometry else {}
        except ValueError, TypeError:
            geom = {}
        coords = geom.get("coords") or []
        lat = float(coords[0][0]) if coords and coords[0] else 0.0
        lon = float(coords[0][1]) if coords and coords[0] else 0.0
        return {
            "id": f"L{rid}",  # string id → never clashes with server int ids
            "local_id": int(rid),
            "local": True,
            "layer_id": int(layer_id) if layer_id is not None else None,
            "type": obj_type,
            "geometry": json.dumps(geom) if geom else "",
            "latitude": lat,
            "longitude": lon,
            "notes": notes,
            "affiliation": aff,
            "symbol_code": sidc,
            "echelon": ech,
        }

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
