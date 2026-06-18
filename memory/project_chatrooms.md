---
name: project_chatrooms
description: Chat rooms with explicit operator membership; replaces role-based GROUP; ATAK named-room interop
metadata:
  type: project
---

Messaging refactor to real chat rooms, DONE 2026-06-13.

Model (`storage/models.py`): `ChatRoom` (id, name, created_by, created_at, mission_id, origin ARROW|ATAK)
+ `ChatRoomMember` (chatroom_id, operator_id). `Message.chatroom_id` added. Additive migration in
`database.py` (CREATE TABLE chatrooms/chatroom_members + ALTER messages). Message types: DIRECT |
BROADCAST | ROOM. The old role-derived "GROUP"/group_id concept is gone (group_id column kept, unused).

Router `backend/chatrooms/router.py` (registered in main.py): GET/POST `/chatrooms`,
GET `/chatrooms/{id}`, POST `/chatrooms/{id}/members`, DELETE `/chatrooms/{id}/members/{op}`,
DELETE `/chatrooms/{id}`. Manage = ADMIN/BATTLE_CAPTAIN or room creator; any operator may self-leave.
Reusable helpers exported for the ATAK bridge: `is_member`, `add_member`, `get_or_create_room`,
`room_out`. Room/member changes broadcast on `chat` channel (events room_created / member_added /
member_removed / room_deleted).

`messaging/router.py`: `send_message` routes ROOM (membership-checked) / DIRECT (receiver_id) /
BROADCAST; `list_messages` shows sender/receiver/BROADCAST + rooms the caller is a member of.
ATAK interop in [[project_atak_chat_bridge]]. Direct messaging unchanged + still bridges to ATAK.
Photo→ATAK (geo-pinned POI base64 image CoT, [[project_atak_photo_bridge]]) re-verified working.

Room management on ALL THREE clients (DONE 2026-06-13):
- web `messaging.html`: sidebar "Chat Rooms" list + ＋ create + per-room ⚙ member manager.
- front: `arrow_client` chatroom methods (+`_delete`, `send_message_room`); MessagesPanel ROOM scope
  + "⚙ Rooms" button → `front/panels/messages/room_manager.py` RoomManagerDialog (create/add-remove/
  delete); main_window `_open_room_manager`/`_load_chatrooms`; WS room events (no message_type) refresh rooms.
- android: `ChatRoomDto`/`ChatRoomIn`/`ChatRoomMemberIn` DTOs + `chatroomId` on Message DTOs;
  `MessageRepository.listRooms/createRoom/addMember/removeMember/deleteRoom` + `send(chatroomId=)`;
  MessagingScreen Recipient.Room + dropdown rooms + "⚙ Manage rooms…" → RoomManagerDialog composable.
Front client chatroom methods verified live end-to-end; Android shares the same endpoints.
All send to rooms via `chatroom_id`; direct + broadcast unchanged.

GOTCHA repeat: kill stale servers by port owner — `lsof -nP -iTCP:8087,6001,6002 -sTCP:LISTEN -t |
xargs -r kill -9` (NOT pkill -f backend.main; and quote/word-split PIDs carefully). A stale server
silently serves old code. Also: when reading ORM objects after `with SessionLocal()` closes you get
"Instance not bound to a Session" — capture ids/attrs inside the block (bit `_handle_cot_image` twice).
