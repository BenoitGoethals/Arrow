---
name: project_photo_storage_marti
description: All photos (web/front/android/ATAK) stored centrally on server; ATAK transfer is binary via TAK Marti file-share
metadata:
  type: project
---

Central binary photo storage + TAK Marti file-share, DONE 2026-06-13.

Requirement: photos from ANY source must be stored on the server, sent as BINARY (not base64).
Web/Front/Android already upload binary multipart → `POST /photos` → `data/photos/` (Photo row holds a
filename, not a blob). ATAK was the gap (it embedded base64 in CoT).

Changes:
- `Photo.sha256` column (+migration) — plaintext SHA-256 so files are retrievable by hash.
- `backend/photos/router.py`: shared `store_photo_bytes` / `read_photo_bytes` / `find_photo_by_hash` /
  `ensure_photo_hash`; `/photos` upload now records sha256. NOTE: `store_photo_bytes` does NOT dedupe
  (a back-ref test relies on distinct rows per upload); inbound ATAK paths dedupe via `find_photo_by_hash`.
- `backend/marti/router.py` (prefix `/Marti`, registered in main.py, UNAUTHENTICATED — ATAK has no Arrow
  JWT): `POST /sync/missionupload`|`/sync/upload` (binary body or multipart assetfile/file) → store →
  returns content URL as text/plain; `GET`/`HEAD /sync/content?hash=` → raw binary; `GET /sync/search`
  (empty). `marti_base_url()` from env `ARROW_MARTI_URL` (device-reachable, e.g. http://78.21.255.210:6001);
  `content_url(sha)`. Disable with `ARROW_MARTI_DISABLED=1`. Restrict this path to the TAK net at the proxy.
- `backend/cot/cot.py`: `build_fileshare` (`b-f-t-r` CoT with `<fileshare senderUrl=content_url sha256 sizeInBytes>`),
  `parse_fileshare`, `is_arrow_fileshare` (uid prefix `ARROW.FSHARE.`). Old base64 `build_image_cot`/`parse_cot_image`
  kept only as inbound legacy fallback.
- `backend/cot/tcp_server.py`: `broadcast_photo_to_atak` now sends a **fileshare CoT** (binary via senderUrl),
  NOT base64. Inbound `_handle_fileshare` (file already in store from the upload, else fetch senderUrl) stores
  centrally + pins a POI when coords present. `_handle_cot_image` (base64) retained as fallback.

Verified live: Marti binary upload↔content roundtrip (no-JWT), web upload→sha256→Marti HEAD, Arrow photo→ATAK
fileshare CoT (no base64), ATAK fileshare→stored+POI with byte-identical file. pytest 179 passed.
See also [[project_atak_photo_bridge]] (superseded base64 path), [[project_atak_chat_bridge]].
ATAK Marti endpoint paths/params vary by version — validate against the fielded build.
