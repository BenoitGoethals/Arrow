---
name: project_atak_chat_bridge
description: Two-way Arrow messaging ↔ ATAK GeoChat bridge over the CoT TCP server
metadata:
  type: project
---

Two-way Arrow chat ↔ ATAK GeoChat bridge, DONE 2026-06-11. ATAK chat = CoT type
`b-t-f` with `<detail><__chat>` + `<remarks>` (text). Rides the native CoT TCP
server (port 8087); see [[project_atak_medevac]] for the same ingestion pattern.

`backend/cot/cot.py`:
- `parse_geochat(xml)` → `{sender_callsign, sender_uid, text, chatroom, source, uid}` or None.
- `build_geochat(sender_callsign, text, room=ALL_CHAT_ROOMS, recipient_uid=None)` → GeoChat CoT bytes.
- Arrow-originated GeoChat is tagged: uid prefix `GeoChat.ARROW.` + remarks source `Arrow.<cs>`. `is_arrow_geochat()` detects our own echo to prevent loops.

`backend/cot/tcp_server.py`:
- inbound: `_handle_frame` calls `parse_geochat`; if not `is_arrow_geochat`, `_handle_geochat` saves a `Message` (BROADCAST for "All Chat Rooms", else GROUP w/ group_id=room) and broadcasts on the `chat` channel (adds `sender_callsign` + `source:"ATAK"`). Relays raw to other ATAK clients. `_resolve_operator_id` (shared with medevac) maps callsign→operator, falls back to lowest id.
- outbound: `broadcast_chat_to_atak(msg, sender)` builds GeoChat to "All Chat Rooms" (BROADCAST/group) or the recipient callsign room (DIRECT w/ receiver_id; DIRECT w/o recipient is skipped).

`backend/messaging/router.py::send_message` calls `broadcast_chat_to_atak` (lazy import) after its `chat` broadcast.

Clients need no change for basic chat — they react to `chat` events by re-fetching `/messages`.
Limitation: an ATAK sender with no matching operator is persisted under the fallback operator_id
(live event still carries the real `sender_callsign`).

CHATROOMS refactor (2026-06-13): real `ChatRoom` + `ChatRoomMember` tables (see [[project_chatrooms]]).
Message types now DIRECT | BROADCAST | ROOM (was the role-based GROUP). ROOM ⇄ ATAK named GeoChat
room (room name == ChatRoom.name; `build_geochat(member_uids=[...])` lists members as chatgrp uid1..N;
`parse_geochat` returns `members`/`room_id`). Inbound ATAK named room → get-or-create ChatRoom (origin
ATAK) via `_handle_geochat`; room name matching an operator callsign → DIRECT. Verified both directions.
