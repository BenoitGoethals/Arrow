"""Synchronous Arrow REST client."""

import logging
import time
from typing import Optional
import httpx

log = logging.getLogger(__name__)

# Self-signed certs are used in production — disable verification globally.
_VERIFY = False


class ArrowClient:
    def __init__(self, base_url: str, token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self._token = token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def _get(self, path: str, **params) -> list | dict:
        t0 = time.monotonic()
        r = httpx.get(
            f"{self.base_url}{path}",
            headers=self._headers(),
            params=params,
            timeout=10.0,
            verify=_VERIFY,
        )
        ms = int((time.monotonic() - t0) * 1000)
        log.debug("GET %s → %d  (%d ms)", path, r.status_code, ms)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict = None, data: dict = None) -> dict:
        t0 = time.monotonic()
        kw = dict(headers=self._headers(), timeout=8.0, verify=_VERIFY)
        if data:
            kw["data"] = data
        else:
            kw["json"] = body or {}
        r = httpx.post(f"{self.base_url}{path}", **kw)
        ms = int((time.monotonic() - t0) * 1000)
        log.debug("POST %s → %d  (%d ms)", path, r.status_code, ms)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str) -> None:
        r = httpx.request(
            "DELETE",
            f"{self.base_url}{path}",
            headers=self._headers(),
            timeout=8.0,
            verify=_VERIFY,
        )
        log.debug("DELETE %s → %d", path, r.status_code)
        r.raise_for_status()

    # ---- Auth -------------------------------------------------------
    def login(self, callsign: str, password: str) -> dict:
        log.info("Login: callsign=%s  server=%s", callsign, self.base_url)
        r = httpx.post(
            f"{self.base_url}/auth/login",
            data={"username": callsign, "password": password},
            timeout=8.0,
            verify=_VERIFY,
        )
        log.info("Login response: %d", r.status_code)
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

    def vehicles(self) -> list:
        return self._get("/vehicles")

    # ---- Tracking ---------------------------------------------------
    def push_position(
        self, lat: float, lon: float, altitude: Optional[float] = None
    ) -> dict:
        """Report this operator's own GPS fix to the backend.

        Persists lat/lon on the Operator row (marking it ONLINE) and broadcasts
        on the `tracking` channel so the web COP can render and zoom to us.
        """
        body: dict = {"latitude": float(lat), "longitude": float(lon)}
        if altitude is not None:
            body["altitude"] = float(altitude)
        return self._post("/tracking/position", body)

    def live_operators(self) -> list:
        return self._get("/tracking/live")

    def cot_tracks(self) -> list:
        return self._get("/cot/tracks")

    # ---- Tactical objects -------------------------------------------
    def tactical_objects(self) -> list:
        return self._get("/tactical-objects")

    def post_tactical_object(
        self,
        obj_type: str,
        geometry: dict,
        notes: str = "",
        affiliation: str = "UNKNOWN",
        symbol_code: str = "",
        echelon: str = "",
        photo_id: Optional[int] = None,
    ) -> dict:
        import json as _json

        coords = geometry.get("coords", [])
        lat = float(coords[0][0]) if coords else 0.0
        lon = float(coords[0][1]) if coords else 0.0
        geom_str = (
            _json.dumps(geometry)
            if geometry.get("type") in ("line", "polygon", "point")
            else ""
        )
        body: dict = {
            "type": obj_type,
            "latitude": lat,
            "longitude": lon,
            "geometry": geom_str,
            "notes": notes,
            "affiliation": affiliation,
            "symbol_code": symbol_code,
            "echelon": echelon,
        }
        if photo_id is not None:
            body["photo_id"] = photo_id
        return self._post("/tactical-objects", body)

    def delete_tactical_object(self, obj_id: int) -> None:
        r = httpx.delete(
            f"{self.base_url}/tactical-objects/{obj_id}",
            headers=self._headers(),
            timeout=8.0,
            verify=_VERIFY,
        )
        r.raise_for_status()

    def patch_tactical_object(
        self, obj_id: int, lat: float, lon: float, geometry: str | None = None
    ) -> dict:
        body = {"latitude": lat, "longitude": lon}
        if geometry is not None:
            body["geometry"] = geometry
        r = httpx.patch(
            f"{self.base_url}/tactical-objects/{obj_id}",
            json=body,
            headers=self._headers(),
            timeout=8.0,
            verify=_VERIFY,
        )
        r.raise_for_status()
        return r.json()

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

    def send_alert(
        self, alert_type: str, lat: Optional[float] = None, lon: Optional[float] = None
    ) -> dict:
        body: dict = {"type": alert_type}
        if lat is not None:
            body["latitude"] = lat
        if lon is not None:
            body["longitude"] = lon
        return self._post("/alerts", body)

    # ---- Reports ----------------------------------------------------
    def reports(self, limit: int = 100) -> list:
        return self._get("/reports", limit=limit)

    def post_report(self, report_type: str, payload: dict) -> dict:
        return self._post("/reports", {"type": report_type, "payload": payload})

    # ---- Photos / media ---------------------------------------------
    def upload_media(self, file_path: str) -> int:
        """Upload an image or video file; returns the photo ID."""
        import mimetypes
        import os

        mime = mimetypes.guess_type(file_path)[0] or "image/jpeg"
        with open(file_path, "rb") as f:
            data = f.read()
        files = {"file": (os.path.basename(file_path), data, mime)}
        r = httpx.post(
            f"{self.base_url}/photos",
            headers=self._headers(),
            files=files,
            timeout=60.0,
            verify=_VERIFY,
        )
        r.raise_for_status()
        return r.json()["id"]

    def photos(self) -> list:
        return self._get("/photos")

    def photo_url(self, photo_id: int) -> str:
        return f"{self.base_url}/photos/{photo_id}"

    # ---- Messages ---------------------------------------------------
    def messages(self, limit: int = 100) -> list:
        return self._get("/messages", limit=limit)

    def send_message(
        self,
        content: str,
        receiver_id: Optional[int] = None,
        photo_id: Optional[int] = None,
    ) -> dict:
        body: dict = {"content": content, "message_type": "BROADCAST"}
        if receiver_id:
            body["receiver_id"] = receiver_id
            body["message_type"] = "DIRECT"
        if photo_id is not None:
            body["photo_id"] = photo_id
        return self._post("/messages", body)

    def send_message_room(
        self, content: str, chatroom_id: int, photo_id: Optional[int] = None
    ) -> dict:
        body: dict = {
            "content": content,
            "message_type": "ROOM",
            "chatroom_id": chatroom_id,
        }
        if photo_id is not None:
            body["photo_id"] = photo_id
        return self._post("/messages", body)

    # ---- Chat rooms -------------------------------------------------
    def chatrooms(self) -> list:
        return self._get("/chatrooms")

    def create_chatroom(
        self, name: str, member_ids: Optional[list[int]] = None
    ) -> dict:
        return self._post("/chatrooms", {"name": name, "member_ids": member_ids or []})

    def add_chatroom_member(self, room_id: int, operator_id: int) -> dict:
        return self._post(f"/chatrooms/{room_id}/members", {"operator_id": operator_id})

    def remove_chatroom_member(self, room_id: int, operator_id: int) -> None:
        self._delete(f"/chatrooms/{room_id}/members/{operator_id}")

    def delete_chatroom(self, room_id: int) -> None:
        self._delete(f"/chatrooms/{room_id}")

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
            headers=self._headers(),
            timeout=8.0,
            verify=_VERIFY,
        )
        r.raise_for_status()

    def create_mission(self, name: str, description: str = "") -> dict:
        return self._post("/missions", {"name": name, "description": description})

    def start_mission(self, mission_id: int) -> dict:
        return self._post(f"/missions/{mission_id}/start")

    def end_mission(self, mission_id: int) -> dict:
        return self._post(f"/missions/{mission_id}/end")

    # ---- Streams ----------------------------------------------------
    def live_streams(self) -> list:
        return self._get("/streams")

    def external_streams(self) -> list:
        return self._get("/streams/external")

    def add_external_stream(
        self, name: str, url: str, stream_type: str, description: str = ""
    ) -> dict:
        return self._post(
            "/streams/external",
            {
                "name": name,
                "url": url,
                "stream_type": stream_type,
                "description": description,
            },
        )

    def recordings(self) -> list:
        return self._get("/streams/recordings")

    def octopus_streams(self) -> list:
        try:
            return self._get("/octopus/streams")
        except Exception:
            return []

    # ---- OPORDs -----------------------------------------------------
    # ---- OPORD snapshots --------------------------------------------
    def add_opord_snapshot(
        self,
        opord_id: int,
        label: str,
        image_b64: str,
        bbox: list = None,
        center: list = None,
        zoom: float = 0.0,
    ) -> dict:
        return self._post(
            f"/opord/{opord_id}/snapshots",
            {
                "label": label,
                "image_b64": image_b64,
                "bbox": bbox or [],
                "center": center or [],
                "zoom": zoom,
                "annotations": "",
            },
        )

    def delete_opord_snapshot(self, opord_id: int, snap_id: int) -> dict:
        r = httpx.delete(
            f"{self.base_url}/opord/{opord_id}/snapshots/{snap_id}",
            headers=self._headers(),
            timeout=8.0,
            verify=_VERIFY,
        )
        r.raise_for_status()
        return r.json()

    def opords(self) -> list:
        return self._get("/opord")

    def opord(self, opord_id: int) -> dict:
        return self._get(f"/opord/{opord_id}")

    def create_opord(self, data: dict) -> dict:
        return self._post("/opord", data)

    def update_opord(self, opord_id: int, data: dict) -> dict:
        r = httpx.put(
            f"{self.base_url}/opord/{opord_id}",
            json=data,
            headers=self._headers(),
            timeout=10.0,
            verify=_VERIFY,
        )
        r.raise_for_status()
        return r.json()

    def publish_opord(self, opord_id: int) -> dict:
        return self._post(f"/opord/{opord_id}/publish")

    def send_opord(self, opord_id: int, recipient_ids: list) -> dict:
        return self._post(f"/opord/{opord_id}/send", {"recipient_ids": recipient_ids})

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
        """Return list of MapSource dicts from the server (includes downloadable flag)."""
        return self._get("/map/sources")

    def download_mbtiles(
        self,
        name: str,
        dest_path: str,
        on_progress=None,  # callable(done_bytes: int, total_bytes: int)
        stop_event=None,  # threading.Event — set it to abort
    ) -> None:
        """Stream /map/sources/{name}/download to dest_path.

        Calls on_progress periodically; raises on HTTP or I/O error.
        Aborts cleanly when stop_event is set.
        """
        import os

        url = f"{self.base_url}/map/sources/{name}/download"
        with httpx.stream(
            "GET",
            url,
            headers=self._headers(),
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=60.0, pool=5.0),
            verify=_VERIFY,
        ) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done = 0
            tmp = dest_path + ".part"
            try:
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=65_536):
                        if stop_event and stop_event.is_set():
                            raise InterruptedError("Download cancelled")
                        f.write(chunk)
                        done += len(chunk)
                        if on_progress:
                            on_progress(done, total)
                os.replace(tmp, dest_path)
            except Exception:
                if os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                raise

    # ---- Properties -------------------------------------------------
    @property
    def token(self) -> Optional[str]:
        return self._token

    @property
    def ws_url(self) -> str:
        return self.base_url.replace("http://", "ws://").replace("https://", "wss://")
