---
name: project_tactical_object_atak_sync
description: Web/app map objects sync to ATAK as CoT; ATAK connect snapshot must replay them
metadata:
  type: project
---

Tactical objects placed on the web/app map are mirrored to ATAK as CoT (DONE 2026-06-13, co-developed with user).

`backend/cot/tcp_server.py` (user owns the bridge fns): `_tactical_object_to_cot(obj)` builds a CoT
(`uid=ARROW.TO.{id}`, type from SIDC or `_TO_TYPE_FALLBACK` by type+affiliation); `broadcast_tactical_object_to_atak(obj)`
(create/update) and `broadcast_tactical_object_delete_to_atak(obj)` (stale=now so ATAK drops it).
`backend/api/tactical_objects.py` calls these on create/patch/delete.

KEY FIX (the reported bug "atak device don't show element from the map web"): the live broadcast only
reaches ALREADY-connected clients. `_push_snapshot` (run on every ATAK connect) was sending operators only —
now it ALSO replays every TacticalObject via `_tactical_object_to_cot`, so a freshly-connected device sees the
existing web map picture. Verified: connect AFTER placing an object → snapshot contains `ARROW.TO.<id>`.

Android: `MapScreen` 15s poll now also calls `tacticalRepository.listObjects()` so marks appear even if a WS
event was missed. Inbound ATAK→Arrow: markers already arrive as cot-tracks; user is adding `parse_atak_shape`/
`parse_emergency`/`parse_spot_report`/fileshare-announcement parsers (their work, in progress).

NOTE: web objects are mission-scoped (`X-Mission-ID` header) — a client viewing a different mission won't see
them (by design). If "not syncing" recurs between web and a client, check both are on the same/no mission.
User is actively co-editing tcp_server.py — coordinate; don't clobber their inbound parsers.
