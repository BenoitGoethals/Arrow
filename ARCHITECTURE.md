# Arrow — Architecture, Design & Flow

This document describes the Arrow platform end-to-end: what the pieces are,
how they fit together, how data flows at runtime, and how the codebase is
laid out. All diagrams are Mermaid; render in GitHub or any Mermaid-aware
viewer.

> See `README.md` for the product spec, `CLAUDE.md` for codebase conventions,
> and `SECURITY.md` / `NIST_CSF2.md` for security posture.

---

## 1. System context

Arrow is a TAK-style situational-awareness platform with three deployable
artifacts that talk to a single source of truth (the backend).

```mermaid
flowchart LR
  subgraph Field["Field operators"]
    A1[Android client<br/>Jetpack Compose]
    A2[ATAK / external CoT]
  end

  subgraph TOC["Tactical operations centre"]
    W[Web dashboard<br/>Flask + Leaflet]
  end

  subgraph Core["Arrow core stack"]
    P[Caddy reverse proxy<br/>:6200]
    B[FastAPI backend<br/>:6001]
    R[(Redis<br/>token blacklist<br/>rate-limit state)]
    D[(SQLite<br/>arrow.db)]
    F[/data volume<br/>photos, streams, backups/]
  end

  A1 -- HTTPS REST + WSS --> P
  A2 -- CoT XML over HTTPS --> P
  W  -- HTTPS REST + WSS --> P
  P  --> B
  B  <--> R
  B  <--> D
  B  <--> F
```

**Trust boundary:** everything outside `Core` is untrusted; the only
authenticated entrypoint is the backend, fronted by Caddy.

---

## 2. Component map

```mermaid
flowchart TB
  subgraph backend["backend/ — FastAPI (port 6001)"]
    direction TB
    main[main.py<br/>create_app + lifespan]
    main --> auth_r[auth/router]
    main --> api_r[api/* routers<br/>companies, platoons,<br/>sections, teams,<br/>operators, hierarchy,<br/>tactical_objects]
    main --> track_r[tracking/router]
    main --> alert_r[alerts/router]
    main --> rep_r[reports/router]
    main --> msg_r[messaging/router]
    main --> bm_r[battle_management/router]
    main --> map_r[map/router]
    main --> cot_r[cot/router]
    main --> str_r[streams/router]
    main --> ph_r[photos/router]
    main --> hist_r[history/router]
    main --> op_r[opord/router]
    main --> fm_r[fire_missions/router]
    main --> ws_r[websocket/router<br/>/ws?token=...]

    storage[(storage/<br/>SQLAlchemy models<br/>+ SessionLocal)]
    bus[[websocket/manager<br/>broadcaster singleton]]
    audit[audit.py<br/>append-only log]

    api_r & track_r & alert_r & rep_r & msg_r & cot_r --> storage
    track_r & alert_r & rep_r & msg_r & cot_r --> bus
    ws_r <--> bus
    auth_r & track_r & alert_r --> audit
  end

  subgraph web["web/ — Flask (port 6002)"]
    direction TB
    wapp[app.py<br/>create_app composition root]
    wapp --> wpres[presentation/<br/>blueprints + shell + proxy]
    wpres --> wapp_svc[application/<br/>PageService]
    wapp_svc --> wdom[domain/<br/>PageView]
    wpres --> winfra[infrastructure/<br/>FlaskTemplateRenderer<br/>HttpxBackendClient<br/>security_headers]
  end

  subgraph android["android/ — Kotlin / Compose"]
    direction TB
    di[di/AppContainer]
    di --> a_auth[auth/]
    di --> a_track[tracking/]
    di --> a_map[map/]
    di --> a_msg[messaging/]
    di --> a_alerts[alerts/]
    di --> a_rep[reports/]
    di --> a_cot[cot/]
    di --> a_off[offline/]
    di --> a_set[settings/]
  end

  android -- HTTPS + WSS --> backend
  web     -- HTTPS + WSS --> backend
```

The web dashboard is intentionally **thin**: Python only renders HTML
shells; all live data is fetched by the browser via the `/api/*` proxy
and the WebSocket.

---

## 3. Backend module layering (Clean Architecture)

Each domain module is being progressively split into four layers:

```mermaid
flowchart TB
  pres[presentation<br/>router.py + schemas.py + dependencies.py<br/>FastAPI-aware, thin]
  app[application<br/>service.py<br/>orchestrates use-cases]
  dom[domain<br/>policies / value objects<br/>pure values, no I/O]
  infra[infrastructure<br/>hashers, JWT, HTTP, ORM adapters]

  pres --> app
  app  --> dom
  app  --> infra
  infra -.implements ports.-> dom
```

**Rule of dependencies:** outer layers depend inward only. `domain` never
imports framework or database code. The router never decodes tokens or
hashes passwords directly — it asks the service.

The `auth/` module is fully refactored to this shape:

```
auth/
  router.py             presentation — FastAPI handlers
  schemas.py            Pydantic DTOs (TokenOut, RegisterIn, ...)
  dependencies.py       get_current_operator, require_role
  jwt_auth.py           compat re-exports for legacy import paths
  domain/policies.py    VALID_ROLES, LOCK_ATTEMPTS, LOCK_MINUTES, ...
  application/
    auth_service.py     register / login / logout + lockout policy
    mfa_service.py      setup / enable / disable / verify
  infrastructure/
    password_hasher.py  bcrypt wrapper
    token_service.py    JWT encode/decode (owns rebound _cfg)
    totp_provider.py    pyotp wrapper
```

Other backend modules (`tracking`, `alerts`, `reports`, `messaging`, ...)
follow the same target shape; today they are typically a single
`router.py` plus implicit ORM use, and will be split module-by-module
without breaking the public import surface.

---

## 4. The real-time bus

A single in-process broadcaster fans out events from every domain router
to every connected WebSocket client. The interface is small on purpose:
swapping for Redis Pub/Sub or NATS later means replacing one class.

```mermaid
flowchart LR
  subgraph emitters["Event emitters"]
    T[tracking/router<br/>position updates]
    A[alerts/router<br/>TIC, MEDICAL, EVAC, LOST_COMMS]
    R[reports/router<br/>CASEVAC, MEDEVAC, CAS, ...]
    M[messaging/router<br/>chat]
    C[cot/router<br/>CoT XML in]
    TO[tactical_objects<br/>graphics edits]
  end

  BUS[[websocket/manager<br/>ConnectionManager<br/>broadcaster.broadcast]]
  WS[/ws?token=...]
  CLIENTS["Connected clients<br/>web browsers · Android · ATAK"]

  T  -- channel=tracking         --> BUS
  A  -- channel=alert            --> BUS
  R  -- channel=report           --> BUS
  M  -- channel=chat             --> BUS
  TO -- channel=tactical-object  --> BUS
  C  -- channel=tracking         --> BUS

  BUS --> WS --> CLIENTS
  BUS -- channel=presence --> WS
```

**Channels in use:** `presence`, `tracking`, `tactical-object`, `alert`,
`chat`, `report`. New channels are added via
`broadcaster.broadcast({"channel": "...", "event": "...", "data": ...})`.

**Auth on the socket:** the WebSocket endpoint requires a valid JWT
(same secret as the REST API). MFA-pending tokens are rejected.

---

## 5. Data model (key entities)

```mermaid
erDiagram
  COMPANY ||--o{ PLATOON : has
  PLATOON ||--o{ SECTION : has
  SECTION ||--o{ TEAM : has
  TEAM    ||--o{ OPERATOR : has

  OPERATOR ||--o{ POSITION_HISTORY : "emits GPS"
  OPERATOR ||--o{ ALERT  : raises
  OPERATOR ||--o{ REPORT : files
  OPERATOR ||--o{ MESSAGE : sends
  OPERATOR ||--o{ AUDIT_EVENT : logged

  BATTLE ||--o{ TACTICAL_OBJECT : contains
  BATTLE ||--o{ OPORD           : "operates under"
  BATTLE ||--o{ FIRE_MISSION    : "schedules"

  TACTICAL_OBJECT }o--|| OPERATOR : "created by"
  STREAM ||--o{ STREAM_RECORDING : produces
  STREAM }o--|| OPERATOR : "owned by"

  OPERATOR {
    int    id
    string callsign  "UK — unique"
    string rank
    string role      "OPERATOR | BATTLE_CAPTAIN | ADMIN"
    string status    "ONLINE | OFFLINE | TIC | ..."
    int    team_id   "FK"
    string password_hash
    bool   mfa_enabled
    string totp_secret
    int    failed_login_count
    datetime locked_until
    datetime last_seen
  }
```

`Operator.role` is enforced by `require_role(...)`. `last_seen` drives the
90-second online/offline computation in `GET /hierarchy`.

---

## 6. Login + MFA flow

The full second-factor path, including lockout and audit hooks.

```mermaid
sequenceDiagram
  autonumber
  participant C as Client (browser / Android)
  participant API as FastAPI /auth
  participant SVC as auth_service
  participant DB as SQLite (Operator)
  participant JWT as token_service
  participant LOG as audit

  C->>API: POST /auth/login (username, password)
  API->>SVC: login(username, password, ip)
  SVC->>DB: SELECT Operator WHERE callsign=?
  alt locked_until > now
    SVC-->>API: 423 Locked
  else bad credentials
    SVC->>DB: failed_login_count++  (lock at 5)
    SVC->>LOG: LOGIN_FAIL (+ ACCOUNT_LOCKED)
    SVC-->>API: 401 Bad credentials
  else MFA enabled
    SVC->>JWT: create_mfa_session(sub)
    SVC->>LOG: LOGIN_MFA_REQUIRED
    SVC-->>API: { mfa_required, mfa_session }
    C->>API: POST /auth/mfa/verify (mfa_session, code)
    API->>SVC: verify_second_step(...)
    SVC->>JWT: decode_token(mfa_session)
    SVC->>DB: load Operator
    SVC->>JWT: TOTP.verify(secret, code)
    alt TOTP ok
      SVC->>JWT: create_access_token(sub, role)
      SVC->>LOG: LOGIN_SUCCESS (via MFA)
      SVC-->>API: { access_token, role }
    else TOTP bad
      SVC->>LOG: MFA_FAIL
      SVC-->>API: 401 Invalid TOTP
    end
  else password ok, no MFA
    SVC->>JWT: create_access_token(sub, role)
    SVC->>LOG: LOGIN_SUCCESS
    SVC-->>API: { access_token, role }
  end
```

The router stays a thin pass-through; the service owns lockout policy and
audit. The infrastructure layer owns bcrypt, JWT, and pyotp — the service
never touches those libraries directly.

---

## 7. Real-time tracking flow

How a GPS ping from an Android device reaches every connected dashboard.

```mermaid
sequenceDiagram
  autonumber
  participant A as Android (tracking/)
  participant API as POST /tracking
  participant DB as Operator row
  participant BUS as broadcaster
  participant WS as /ws subscribers
  participant W as Web dashboard

  loop every N seconds (FG service)
    A->>API: { lat, lon, ts } + JWT
    API->>API: get_current_operator (auth)
    API->>DB: UPDATE operators SET last_seen, lat, lon
    API->>BUS: broadcast(channel="tracking", data=...)
    BUS->>WS: fanout to all sockets
    WS->>W: ws message → marker moves
  end
```

The same path is used by the CoT bridge (`/cot` POST → `cot/router` decodes
XML → broadcaster), which makes ATAK clients first-class peers.

---

## 8. Web dashboard layering

After the recent refactor, the Flask side has the same four-layer shape
as the backend modules. Every blueprint is a thin shell that calls
`PageService` → returns a `PageView` → `FlaskTemplateRenderer` renders it.

```mermaid
flowchart LR
  browser["Browser"]
  subgraph flask["web/ Flask app"]
    direction TB
    P1["presentation<br/>blueprints/* + shell + proxy"]
    A1["application/pages.py<br/>PageService"]
    D1["domain/page.py<br/>PageView"]
    I1["infrastructure<br/>FlaskTemplateRenderer<br/>HttpxBackendClient<br/>security_headers"]
    P1 --> A1 --> D1
    P1 --> I1
  end
  backend["FastAPI backend"]
  browser -- HTML/JS shells --> P1
  browser -- "fetch /api/*<br/>WS /api/ws"  --> P1
  P1 -- httpx forward --> backend
```

`create_app(...)` is the composition root and accepts overrides for
`config`, `service`, `renderer`, and `backend_client`, so tests can swap
in fakes without spinning up the FastAPI server.

---

## 9. Deployment topology

```mermaid
flowchart TB
  subgraph host["Docker host"]
    proxy[caddy<br/>:6200<br/>arrow-proxy]
    web[arrow-web<br/>Flask :6002]
    api[arrow-backend<br/>FastAPI :6001]
    redis[(redis:7-alpine<br/>arrow-redis)]
    backup[arrow-backup<br/>sqlite3 .dump + tar]
    subgraph optional["docker compose --profile logging"]
      loki[loki]
      promtail[promtail]
      grafana[grafana :3000]
    end

    proxy --> web
    proxy --> api
    web   --> api
    api   --> redis
    api   --- arrow_data[("arrow-data volume<br/>arrow.db + photos + streams")]
    backup -. read .- arrow_data
    backup --- arrow_backups[("arrow-backups volume")]
    promtail -.- loki -.- grafana
  end

  internet((Internet)) --> proxy
```

Lifecycle is managed by `deploy.sh`:

| Command | Effect |
|---|---|
| `./deploy.sh up` | build + start (removes leftover containers first) |
| `./deploy.sh rebuild` | `--no-cache` build + force-recreate |
| `./deploy.sh down` | stop & remove |
| `./deploy.sh logs` | tail compose logs |
| `./deploy.sh status` | `docker compose ps` |

---

## 10. Security architecture

```mermaid
flowchart LR
  subgraph edge["Edge"]
    csp[CSP + security headers<br/>web after_request]
    caddy[Caddy TLS]
  end
  subgraph authn["Authentication"]
    pw[bcrypt password_hasher]
    jwt[JWT token_service<br/>HS algo + jti + exp]
    totp[TOTP totp_provider]
    bl[(token_blacklist<br/>Redis-backed)]
  end
  subgraph authz["Authorization"]
    dep[get_current_operator]
    role[require_role ADMIN / BC / OP]
  end
  subgraph quota["Abuse-control"]
    rl[slowapi limiter<br/>3/min register · 10/min login]
    lockout[Account lockout<br/>5 fails → 15 min]
  end
  subgraph audit["Audit"]
    ev[audit_events table<br/>append-only]
  end

  caddy --> csp --> dep
  dep --> jwt --> bl
  dep --> role
  pw --> jwt
  totp --> jwt
  rl --> dep
  lockout --> ev
  dep --> ev
```

**Key invariants:**

- Every protected route depends on `get_current_operator` (or `require_role`).
  Routers never decode tokens themselves.
- MFA-session tokens (`mfa_pending=true`) cannot authenticate API calls —
  only `POST /auth/mfa/verify`.
- `/auth/logout` writes the JWT's `jti` to the blacklist; expired entries
  age out naturally.
- The JWT secret is auto-generated on first boot if config still holds the
  default, persisted under `data/jwt_secret.key` in the `arrow-data`
  volume. The lifespan rebinds `token_service._cfg` after resolution.

---

## 11. Test architecture

Tests are split by kind, not by feature:

```
tests/
  conftest.py            # shared fixtures — in-memory SQLite, seeded admin,
                         # rate-limiter disabled
  unit/                  # pure, no network
    test_cot.py          # CoT encoder/decoder
    test_pages.py        # web PageService
    test_proxy.py        # web proxy with fake BackendClient
  integration/           # FastAPI TestClient + real SQLite (in-memory)
    test_auth_and_tracking.py
    test_messaging.py
    test_tactical_graphics.py
    test_streams.py
    test_photos_list.py
    test_map_snapshots.py
  e2e/
    test_full_flow.py    # full multi-role scenario
```

```mermaid
flowchart LR
  u[unit<br/>~1s] --> i[integration<br/>~10s] --> e[e2e<br/>~30s]
  click u "tests/unit"
  click i "tests/integration"
  click e "tests/e2e"
```

`pytest tests/unit -q` is fast enough to run on every save; the full suite
runs in ~46s.

---

## 12. Configuration & startup

```mermaid
sequenceDiagram
  autonumber
  participant uvicorn
  participant App as FastAPI create_app
  participant LS as lifespan
  participant CFG as load_config(config.xml)
  participant DB as init_db / seed_db
  participant TS as token_service
  participant BL as token_blacklist

  uvicorn->>App: build
  App-->>uvicorn: app (routers wired)
  uvicorn->>LS: enter
  LS->>CFG: parse XML
  LS->>TS: rebind _cfg (real secret)
  LS->>DB: init schema + seed
  LS->>BL: init(redis_url)
  LS-->>uvicorn: ready
  Note over uvicorn: serving requests
  uvicorn->>LS: shutdown
```

`config.xml` is read at **import time** in `storage/database.py` and
`auth/infrastructure/token_service.py`. The lifespan then patches the
JWT cfg with the resolved secret. Restart the process to pick up
`config.xml` edits during development.

---

## 13. Where to start reading

| If you want to understand... | Start at |
|---|---|
| How a request is authenticated | `backend/auth/dependencies.py` → `auth_service` |
| The realtime bus | `backend/websocket/manager.py` |
| How GPS reaches the web map | `backend/tracking/router.py` then `web/templates/map.html` |
| ATAK / CoT interop | `backend/cot/cot.py` and `backend/cot/router.py` |
| How to add a new domain module | Copy `auth/`'s layered shape: domain → infra → application → router |
| How the dashboard wires layers | `web/app.py` (composition root) |
| How the stack runs in prod | `docker-compose.yml`, `Caddyfile`, `deploy.sh` |

---

*Last updated: refactor pass that introduced layered architecture in
`web/` and `backend/auth/`, plus the unit/integration/e2e test split.*
