---
name: project_admin_logs
description: Admin Logs viewer — in-app log aggregation across backend/cot/connections/web
metadata:
  type: project
---

Admin Logs viewer, DONE 2026-06-14. Unified in-app log view in the web admin menu, all levels,
categorised: connections / cot / backend / web.

`backend/logbuffer.py`: ring buffer (deque 5000) + `RingBufferHandler` attached to the root logger
in `_configure_logging` (captures everything at DEBUG). `category_for(logger, explicit)` →
backend.cot* = "cot", backend.websocket* = "connections", web* = "web", else "backend"; a record can
override via `extra={"cat": ...}`. `query(category, level, q, since, limit)` for incremental polling
(`since`=last id); `ingest(records)` for the web process; `categories()` for counts.

`backend/admin/router.py`: `GET /admin/logs` (ADMIN) + `POST /admin/logs/ingest` (token-gated by
`ARROW_LOG_TOKEN` header `X-Log-Token`, open if unset). `backend/main.py`: HTTP access-log middleware
(`backend.request`, every request method/path/status/ms/client). cot TCP connect/disconnect +
`backend/websocket/manager.py` WS connect/disconnect tagged `extra={"cat":"connections"}`.

`web/log_shipper.py`: buffering handler + daemon thread POSTs Flask-process records (incl. werkzeug)
to `{ARROW_BACKEND_URL}/admin/logs/ingest` as category "web"; skips httpx/httpcore/urllib3 to avoid a
feedback loop. Wired in `web/app.py` create_app + a Flask `after_request` access log.

Web UI: `web/templates/admin.html` "📜 Logs" nav → `renderLogs()`: category chips (counts), level
filter, search, pause, clear, colour-by-level, 1.5s incremental poll (`window._logTimer`, cleared on
tab change). Admin-only.

Verified live: all 4 categories populate (connections/cot/backend/web), level filter works, web
werkzeug logs reach the backend buffer. 279 tests pass.

LIMITATION: nginx/proxy logs are NOT in this viewer (separate container, stdout). For proxy + full
multi-service aggregation use the existing Loki/Promtail/Grafana stack (docker-compose `--profile logging`).
Set `ARROW_LOG_TOKEN` in prod for both backend+web so ingest is authenticated.
