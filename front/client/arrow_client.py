"""Synchronous Arrow REST client."""
from typing import Optional
import httpx


class ArrowClient:
    def __init__(self, base_url: str, token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self._token   = token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def _get(self, path: str, **params) -> list | dict:
        r = httpx.get(f"{self.base_url}{path}", headers=self._headers(), params=params, timeout=10.0)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict = None, data: dict = None) -> dict:
        kw = dict(headers=self._headers(), timeout=8.0)
        if data:
            kw["data"] = data
        else:
            kw["json"] = body or {}
        r = httpx.post(f"{self.base_url}{path}", **kw)
        r.raise_for_status()
        return r.json()

    # ---- Auth -------------------------------------------------------
    def login(self, callsign: str, password: str) -> dict:
        r = httpx.post(f"{self.base_url}/auth/login",
                       data={"username": callsign, "password": password}, timeout=8.0)
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        return data

    def me(self) -> dict:
        return self._get("/auth/me")

    # ---- Hierarchy --------------------------------------------------
    def hierarchy(self) -> dict:
        return self._get("/hierarchy")

    def operators(self) -> list:
        return self._get("/operators")

    # ---- Tracking ---------------------------------------------------
    def live_operators(self) -> list:
        return self._get("/tracking/live")

    def cot_tracks(self) -> list:
        return self._get("/cot/tracks")

    # ---- Tactical objects -------------------------------------------
    def tactical_objects(self) -> list:
        return self._get("/tactical-objects")

    def post_tactical_object(self, obj_type: str, geometry: dict, notes: str = "",
                              affiliation: str = "UNKNOWN", symbol_code: str = "",
                              echelon: str = "") -> dict:
        import json as _json
        coords = geometry.get("coords", [])
        lat = float(coords[0][0]) if coords else 0.0
        lon = float(coords[0][1]) if coords else 0.0
        # store geometry string only for non-point shapes
        geom_str = _json.dumps(geometry) if geometry.get("type") in ("line", "polygon") else ""
        return self._post("/tactical-objects", {
            "type":        obj_type,
            "latitude":    lat,
            "longitude":   lon,
            "geometry":    geom_str,
            "notes":       notes,
            "affiliation": affiliation,
            "symbol_code": symbol_code,
            "echelon":     echelon,
        })

    # ---- KML --------------------------------------------------------
    def kml_layers(self) -> list:
        return self._get("/kml-layers")

    def kml_layer(self, layer_id: int) -> dict:
        return self._get(f"/kml-layers/{layer_id}")

    # ---- Fire missions ----------------------------------------------
    def fire_missions(self) -> list:
        return self._get("/fire-missions")

    # ---- Alerts -----------------------------------------------------
    def alerts(self) -> list:
        return self._get("/alerts")

    def send_alert(self, alert_type: str) -> dict:
        return self._post("/alerts", {"type": alert_type})

    # ---- Reports ----------------------------------------------------
    def reports(self, limit: int = 100) -> list:
        return self._get("/reports", limit=limit)

    def post_report(self, report_type: str, payload: dict) -> dict:
        return self._post("/reports", {"type": report_type, "payload": payload})

    # ---- Messages ---------------------------------------------------
    def messages(self, limit: int = 100) -> list:
        return self._get("/messages", limit=limit)

    def send_message(self, content: str, receiver_id: Optional[int] = None) -> dict:
        body = {"content": content, "message_type": "BROADCAST"}
        if receiver_id:
            body["receiver_id"] = receiver_id
            body["message_type"] = "DIRECT"
        return self._post("/messages", body)

    def send_message_group(self, content: str, group_id: int) -> dict:
        return self._post("/messages", {
            "content": content,
            "message_type": "GROUP",
            "group_id": group_id,
        })

    # ---- Missions ---------------------------------------------------
    def missions(self) -> list:
        return self._get("/missions")

    def mission(self, mission_id: int) -> dict:
        return self._get(f"/missions/{mission_id}")

    def mission_operators(self, mission_id: int) -> list:
        return self._get(f"/missions/{mission_id}/operators")

    def delete_mission(self, mission_id: int) -> None:
        r = httpx.delete(
            f"{self.base_url}/missions/{mission_id}",
            headers=self._headers(), timeout=8.0,
        )
        r.raise_for_status()

    def create_mission(self, name: str, description: str = "") -> dict:
        return self._post("/missions", {"name": name, "description": description})

    def start_mission(self, mission_id: int) -> dict:
        return self._post(f"/missions/{mission_id}/start")

    def end_mission(self, mission_id: int) -> dict:
        return self._post(f"/missions/{mission_id}/end")

    # ---- Strike packages --------------------------------------------
    def strike_packages(self) -> list:
        return self._get("/strike-packages")

    def strike_package_bundle(self, pkg_id: int) -> dict:
        """Returns the fully expanded bundle (all IDs resolved to objects)."""
        return self._get(f"/strike-packages/{pkg_id}/bundle")

    # ---- Overlays ---------------------------------------------------
    def overlays(self) -> list:
        return self._get("/overlays")

    def overlay(self, overlay_id: int) -> dict:
        return self._get(f"/overlays/{overlay_id}")

    # ---- Map sources (MBTiles on server) ----------------------------
    def map_sources(self) -> list:
        return self._get("/map/sources")

    # ---- Properties -------------------------------------------------
    @property
    def token(self) -> Optional[str]:
        return self._token

    @property
    def ws_url(self) -> str:
        return self.base_url.replace("http://", "ws://").replace("https://", "wss://")
