---
name: project_atak_medevac
description: ATAK 9-line MEDEVAC ingested over CoT TCP → saved Report + Alert, full web/MEDCOP visuals
metadata:
  type: project
---

ATAK MEDEVAC/CASEVAC (9-liner) ingestion, DONE 2026-06-11. An ATAK device sends a
9-line MEDEVAC as a CoT event `type="b-r-f-h-c"` with a `<detail><_medevac_ .../>`
element over the native CoT TCP server (port 8087, see [[project_vehicles_ops_status]] sibling work on `position_source`).

Flow:
- `backend/cot/cot.py::parse_medevac(xml)` — detects `_medevac_` (or `b-r-f-h-c`), normalises
  attrs into `line_1..line_9` + labels + `latitude/longitude/callsign/type` (MEDEVAC vs CASEVAC via `casevac` attr). Returns None if not a medevac.
- `backend/cot/tcp_server.py::_handle_frame` calls it BEFORE the position/track path;
  on hit → `_handle_medevac()` saves `Report(type=MEDEVAC, status=RECEIVED)` + `Alert(type=MEDEVAC, ACTIVE)`,
  broadcasts on `report` (event=submitted) and `alert` (event=triggered) channels, relays raw to other ATAK clients, returns.
  `_resolve_operator_id` maps callsign→operator, falls back to lowest-id operator (FKs are NOT NULL).

Reuses existing client machinery — no new web endpoints. Web map.html: showReportToast (toast),
handleAlertTriggered (zoom + pulsing marker; I added a 🚁 divIcon for MEDEVAC/EVAC/MEDICAL = the "medevac arrow"),
loadMapReports/loadMapAlerts (sidebars), and MEDCOP `medcop.html` reads `/reports` filtered to MEDEVAC/CASEVAC,
rendering the 9-liner via `_nineliner` (supports `line_N`/`label_N` shape we emit).

Report payload is broadcast as a JSON *string* so the web's `JSON.parse(msg.data.payload)` auto-zoom works.
Shares the 9-liner vocabulary with [[project_cas_feature]]. Front/Android get the report+alert WS events
through their generic handlers but have no MEDEVAC-specific visual yet.
