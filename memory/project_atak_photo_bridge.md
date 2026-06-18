---
name: project_atak_photo_bridge
description: Two-way geo-pinned photo bridge between Arrow and ATAK over CoT TCP
metadata:
  type: project
---

Two-way geo-pinned photo bridge Arrow ↔ ATAK, DONE 2026-06-12. Photos travel as a
point CoT carrying a base64 `<detail><image>` element (self-contained over the CoT
TCP stream on 8087 — no TAK Server file API). ATAK renders it on the marker; Arrow
stores it as a Photo + a POI `TacticalObject` at the same grid (= "pinned on location").

`backend/cot/cot.py`:
- `parse_cot_image(xml)` → `{lat, lon, callsign, mime, image_bytes, caption, uid}` or None.
- `build_image_cot(lat, lon, callsign, image_bytes, mime, caption, cot_type="b-m-p-s-p-i")`.
- Loop guard: Arrow photo uid prefix `ARROW.PHOTO.`; `is_arrow_photo()` skips our own echo. `PHOTO_COT_MAX_BYTES=512KB` cap for outbound (huge base64 breaks ATAK frames).

`backend/cot/tcp_server.py`:
- inbound: `_handle_frame` → `parse_cot_image`; if not arrow, `_handle_cot_image` encrypts+writes the blob (reuses `backend.photos.router._encrypt/_get_aesgcm/PHOTO_DIR/MIME_TO_EXT`), creates a `Photo` + a POI `TacticalObject(photo_id=...)`, broadcasts `tactical-object created`. Relays raw to other ATAK.
- outbound: `broadcast_photo_to_atak(obj, sender)` — reads+decrypts the photo INSIDE the session (`_load_photo_bytes`), builds image CoT, `_Pool.broadcast`. CRITICAL: read all Photo attrs while session-bound or you get "Instance not bound to a Session".
- needed `import uuid` at top of tcp_server.

`backend/api/tactical_objects.py::create_object` calls `broadcast_photo_to_atak` (lazy import) when `obj.photo_id`.

Client photo display on the pinned POI (all three):
- web map.html — already rendered the POI photo in its popup (`obj.photo_id` → `<img data-photo-id>`).
- front map.html — `buildObjPopup` now shows the image; `objPhotos`/`tobjData` caches + `setObjPhoto(id,uri)` JS. Python `MapView.set_auth()` + `_fetch_obj_photo` fetch with Bearer via `_ImageFetchThread` (reused from messages panel) → inject base64 data-URI. main_window calls `_map.set_auth(...)`.
- android MapScreen — a POI with `photoId != null` now routes its tap to `ObjectiveDetailDialog` (already renders the photo via Coil AsyncImage `/photos/{id}`) instead of the action radial; dialog title is type-aware (📍 vs 🚩).
Front & Android already supported CREATING a photo'd POI, so their outbound→ATAK bridge worked from day one.

Same ATAK-CoT pattern as [[project_atak_chat_bridge]] / [[project_atak_medevac]].

GOTCHA that cost an hour: `pkill -f "backend.main:app"` does NOT kill `uv run arrow` workers
(they're multiprocessing `spawn_main` cmdlines). Kill by port owner instead:
`kill -9 $(lsof -nP -iTCP:8087,6001,6002 -sTCP:LISTEN -t)` + the `/.venv/bin/arrow` parent.
A stale server silently served old code through many "restarts".
