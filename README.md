# Soldier System Platform — AI Agent Development Specification

## 1. Project Overview

### Goal

Build a military-style situational awareness platform similar to Android Team Awareness Kit / Tactical Assault Kit for Special Operations Forces (SOF).

The system consists of:

1. **Web Platform**

   * Used by Battle Captains and Admins
   * Browser-based operational map
   * Real-time monitoring and command interface

2. **Android Tactical App**

   * Used by Operators/Soldiers
   * Real-time tactical awareness
   * Messaging and battlefield reporting
   * Adapts to phone and tablet form factors (`WindowSize` class-based scaling)
   * Both landscape and portrait orientations

3. **Desktop Client** (`desktop/`, .NET 10 + Avalonia)

   * Cross-platform native client (macOS, Windows, Linux); AOT-publishable
   * Battle-captain / operator desktop UI parallel to the Android app
   * Mapsui-based tactical map with MIL-STD-2525C affiliation frames
   * Same WebSocket realtime bus + REST surface as the Android client
   * Tabs: Map · Chat · Alerts · Objectives · Reports · Fire missions · CBRN · Photos · OPORD · Streams · Hierarchy · Admin (role-gated) · Settings
   * MFA-aware login, persisted token, configurable backend URL with path-prefix support for reverse-proxied deployments

4. **Backend Services**

   * FastAPI backend
   * WebSocket realtime communication
   * REST APIs
   * CoT (Cursor on Target) messaging
   * PostgreSQL + PostGIS storage (Docker volume `postgres-data`; connection via `ARROW_DATABASE_URL`)

---

## Documentation

Sibling documents that go deeper than this spec:

| Document | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System context, component map, layered backend & web modules, real-time bus, data model, deployment topology, sequence diagrams for login/MFA and tracking. |
| [CLAUDE.md](CLAUDE.md) | Codebase conventions: module layout, cross-cutting patterns, import rules, how to add new realtime channels and roles. |
| [SECURITY.md](SECURITY.md) | Security posture, threat model, controls. |
| [NIST_CSF2.md](NIST_CSF2.md) | NIST Cybersecurity Framework 2.0 mapping. |
| [GOVERNANCE.md](GOVERNANCE.md) | Roles, decision rights, change-management policy. |
| [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) | On-call runbook for security and outage incidents. |
| [RECOVERY_PLAN.md](RECOVERY_PLAN.md) | Backup, restore, and disaster-recovery procedures. |
| [USERS.md](USERS.md) | User roles, account lifecycle, MFA enrolment. |

For interop and pitch material: `PITCH.txt`, `Arrow_Pitch.pdf`.

---

## Quick Start

On a fresh deploy (`docker compose up -d` or `uv run arrow-backend` locally) the backend
auto-seeds the following accounts so you can log in immediately. **All passwords are `ranger14`.**

| Callsign | Role             | Notes                                  |
| -------- | ---------------- | -------------------------------------- |
| `benoit` | ADMIN            | Full admin (hierarchy + audit + maps)  |
| `capt`   | BATTLE_CAPTAIN   | Web dashboard / S-3 cell               |
| `ops1`   | OPERATOR         | Android / desktop end-user             |
| `ops2`   | OPERATOR         |                                        |
| `ops3`   | OPERATOR         |                                        |

The seed is per-row idempotent — restarts top up missing accounts without disturbing the rest.

Default backend URLs:

| Tier         | Default                          | Override                                  |
| ------------ | -------------------------------- | ----------------------------------------- |
| Direct       | `http://localhost:6001`          | `ARROW_BACKEND_URL` env / `--backend` CLI |
| Behind Caddy | `http://localhost:6200/api`      | same                                      |

The Python simulators (`simulate_*.py`) remember the last successful URL under
`~/.config/arrow/simulator.json`, so re-runs without `--backend` use the same target.
The Desktop and Android clients accept a path-prefix on the backend URL
(`http://host:6200/api`), so they work transparently behind a reverse proxy.

---

# 2. Core Functional Requirements

## Essential Capabilities

### 2.1 Tactical Map

The system must:

* Display a map
* Display live operators
* Display military objects
* Share objects in realtime
* Support MIL-STD-2525 military symbology
* Allow map annotations and markers
* Allow tactical overlays
* Allow offline map zones

---

### 2.2 Real-Time Awareness

The system must support:

* Live GPS tracking
* Live movement updates
* Real-time tactical objects
* Real-time alerts
* Realtime messaging
* Group visibility

Communication technologies:

* WebSockets
* REST API
* CoT (Cursor on Target)

---

### 2.3 Military Hierarchy

## Structure

```text
Company
 ├── Platoons
 │    ├── Sections
 │    │     ├── Teams
 │    │     │     ├── Operators (Soldiers)
```

---

## Definitions

### Operator

A soldier/user operating the Android tactical device.

### Team

Small tactical unit containing operators.

### Section

Contains multiple teams.

### Platoon

Contains multiple sections.

### Company

Contains multiple platoons, sections and teams.

---

# 3. Roles and Permissions

## 3.1 Admin

Responsibilities:

* System configuration
* User management
* Server configuration
* Team structure management
* Device management
* Global settings

Capabilities:

* CRUD operators
* CRUD teams
* CRUD sections
* CRUD platoons
* CRUD company structure
* Manage offline maps
* Configure CoT settings
* Configure WebSocket server

---

## 3.2 Battle Captain

Web application operational user.

Capabilities:

* View all operators
* Track operators live
* Create/manage battles
* Create tactical overlays
* Plot enemy units
* Plot POIs
* View alerts
* Send messages
* Receive contact reports
* Receive enemy spot reports
* View operational groups

---

## 3.3 Operator

Android tactical user (and parallel desktop client).

Capabilities:

* View tactical map (with MIL-STD-2525C symbology)
* View teammates
* Send GPS position (5 s heartbeat broadcast)
* Plot enemy positions
* Create markers via radial menu (Enemy / Fire Mission / Report / Mortar / POI / Measure / Drone Spot)
* Measure tool: distance + azimuth (° and mils) between two map points
* Submit drone-spot reports with type / altitude / direction / behavior
* Send contact and spot reports
* Send 9-liners (CASEVAC / MEDEVAC / CAS)
* Send messages
* Trigger alerts
* Download offline maps

---

# 4. Tactical Features

## 4.1 Map Features

### Required

* Interactive tactical map
* Zoom/pan
* Layer system
* Offline map support
* Tactical overlays
* Object clustering
* Group visualization

### Objects

The map must display:

* Operators
* Teams
* Sections
* Platoons
* Enemy units
* POIs
* Tactical markers
* Alerts
* Routes
* Operational zones

---

## 4.2 Military Symbology

Use:

```text
MIL-STD-2525
```

Objects requiring military symbols:

* Friendly operators
* Enemy forces
* Unknown contacts
* Vehicles
* POIs
* Tactical control measures

---

## 4.3 Tactical Grouping

The system must allow visualization of:

* Entire company
* Platoon groups
* Section groups
* Team groups

Example:

```text
Show all operators of:
- Team Alpha
- Section Bravo
- Platoon Charlie
```

---

# 5. Reporting System

## 5.1 Contact Report

Operators must be able to send:

* Enemy contact reports
* Contact location
* Contact size
* Contact direction
* Threat assessment

---

## 5.2 Enemy Spot Report

Operators must be able to:

* Mark enemy position
* Attach military symbol
* Add notes
* Share instantly

---

## 5.3 Alerts

Operators must have an emergency alert button.

When activated:

* Broadcast to entire company
* Display on all maps
* Generate visual alert
* Generate sound/vibration
* Store event in database

Examples:

* TROOPS IN CONTACT
* MEDICAL
* EVAC
* LOST COMMS
* DRONE SPOTTED (auto-raised on drone-spot submission — see §5.5)

---

## 5.4 9-Liners

Support structured tactical forms:

* CASEVAC
* MEDEVAC
* CAS requests
* Tactical support requests

---

## 5.5 Drone Spot Report

Operators must be able to report drone observations (UAV / loitering munition /
FPV / ISR / fixed-wing) with structured detail:

* Location (lat/lon)
* Drone type (QUADCOPTER, FIXED_WING, FPV, LOITERING_MUNITION, ISR, SHAHED-136, MAVIC, …)
* Estimated altitude (m)
* Direction of travel (°)
* Estimated speed (kt, optional)
* Behavior (HOVERING, TRANSITING, ATTACK_RUN, RECONNAISSANCE, LOITERING, EVADING)
* Free-text notes (colour, markings, intent)

A single `POST /reports/drone-spot` stores a `DRONE_SPOT` report **and** raises a
`DRONE_SPOTTED` alert. The web dashboard plays a distinctive drone-buzz tone, voices
"Drone spotted", and shows a purple toast with all fields. Android exposes it via the
radial menu (🛸 Drone Spot) and a dedicated top-bar FAB that drops the report at the
current map centre with one tap.

---

## 5.6 NATO CBRN Messages

Full support for STANAG 2103 / ATP-45 CBRN reporting (`CBRN_1` initial observation
through `CBRN_6`), submitted as structured `/reports` POSTs **or** parsed from raw
NATO message text via `/reports/cbrn/import`. The map renders Zone I (immediate
hazard radius) and Zone II (downwind sector) overlays per incident.

---

# 6. Messaging System

## Required Messaging Features

* Direct messages
* Group messages
* Broadcast messages
* Tactical reports
* Attach coordinates
* Attach tactical objects

Participants:

* Operator ↔ Operator
* Operator ↔ Battle Captain
* Battle Captain ↔ Teams
* Company-wide broadcast

---

# 7. Realtime Communication

## 7.1 Technologies

### WebSocket

Used for:

* Live GPS
* Tactical objects
* Alerts
* Presence
* Chat

### REST API

Used for:

* CRUD operations
* Authentication
* Configurations
* Historical data

### CoT (Cursor on Target)

Used for:

* Tactical interoperability
* Standardized battlefield messaging

---

# 8. Web Platform (Flask)

## Main Features

### Operational Dashboard

Displays:

* Tactical map
* Live operators
* Alerts
* Active battles
* Tactical reports

---

## Admin Panel

Manage:

* Users
* Teams
* Structure
* Configurations
* Devices
* Maps

---

## Tactical Map

Must show:

* Operator name
* Status
* Coordinates
* Team
* Section
* Platoon
* Live movement trail

---

# 9. Android Tactical App

## Core Features

### Live Tactical Map

Displays:

* Friendly operators
* Enemy markers
* POIs
* Alerts
* Team overlays

---

## Messaging

Support:

* Tactical chat
* 9-liners
* Reports
* Group messaging

---

## Configuration Menu

Operator must configure:

* Device operator
* Team
* Section
* Server address
* Authentication
* Offline maps

---

## Offline Capabilities

Must support:

* Offline map zones
* Cached tactical data
* Delayed synchronization

---

# 10. Backend Architecture

## Backend Stack

### API

```text
FastAPI
```

### Database

```text
PostgreSQL 16 + PostGIS 3.4
```

### Realtime

```text
WebSockets
```

### Tactical Protocol

```text
CoT
```

---

# 11. System Architecture Requirements

## Design Principles

### SOLID

Architecture must follow SOLID principles.

### Plugable

Components/modules must be replaceable.

### Scalable

Architecture must support:

* More operators
* Multiple companies
* Multiple battle captains
* Multiple servers

---

# 12. Suggested Architecture

## Backend Modules

```text
backend/
 ├── api/
 ├── websocket/
 ├── cot/
 ├── auth/
 ├── messaging/
 ├── tracking/
 ├── battle_management/
 ├── map/
 ├── alerts/
 ├── reports/
 ├── storage/
 └── config/
```

---

## Android Modules

```text
android/
 ├── map/         (incl. measure tool + radial menu + MIL-STD-2525)
 ├── tracking/
 ├── messaging/
 ├── reports/    (contact, spot, 9-liners, drone-spot, CBRN)
 ├── alerts/
 ├── objectives/
 ├── firemission/
 ├── opord/
 ├── photos/
 ├── stream/
 ├── cbrn/
 ├── cot/
 ├── offline/
 ├── auth/       (incl. MFA TOTP)
 └── settings/
```

---

## Desktop Modules (.NET 10 / Avalonia)

```text
desktop/
 ├── src/
 │   ├── Arrow.Core/             (POCOs + STJ source-gen)
 │   ├── Arrow.Net/              (ApiClient, BroadcastClient, RealtimeBus)
 │   ├── Arrow.Platform/         (ILocationService, ISecureStorage abstractions)
 │   ├── Arrow.Platform.MacOS/   (Keychain + CoreLocation)
 │   ├── Arrow.Platform.Linux/   (libsecret + GeoClue2)
 │   ├── Arrow.Platform.Windows/ (DPAPI + WinRT Geolocator)
 │   ├── Arrow.Stream/           (WebRTC client via SIPSorcery)
 │   └── Arrow.Domain/           (Auth, Tracking, Alerts, Messaging, Reports,
 │                                TacticalObjects, Cot, Hierarchy, Admin,
 │                                Battles, Map, FireMissions, Opord, Photos,
 │                                Streams, Settings, Offline)
 └── host/
     ├── Arrow.Host.Console/     (smoke-test CLI, AOT-publishable)
     └── Arrow.Ui.Avalonia/      (Avalonia desktop UI + Mapsui map)
```

---

## Web Modules

```text
web/
 ├── dashboard/
 ├── tactical_map/
 ├── operator_management/
 ├── battle_management/
 ├── reports/
 ├── alerts/
 ├── messaging/
 └── admin/
```

---

# 13. Database Core Entities

## Entities

### Operator

```text
id
callsign
rank
status
team_id
section_id
platoon_id
company_id
gps_position
last_seen
role
```

---

### Team

```text
id
name
section_id
```

---

### Section

```text
id
name
platoon_id
```

---

### Platoon

```text
id
name
company_id
```

---

### Company

```text
id
name
```

---

### TacticalObject

```text
id
type
symbol_code
created_by
position
timestamp
notes
visibility
```

---

### Alert

```text
id
type
operator_id
position
timestamp
status
```

---

### Message

```text
id
sender_id
receiver_id
group_id
content
timestamp
message_type
```

---

# 14. XML Configuration

## Configuration File

Format:

```xml
<config>
    <server>
        <host>192.168.1.10</host>
        <port>8000</port>
    </server>

    <operator>
        <callsign>ALPHA-1</callsign>
        <team>Alpha</team>
    </operator>

    <maps>
        <offline>true</offline>
    </maps>
</config>
```

---

# 15. Suggested Technology Stack

## Backend

* FastAPI
* SQLAlchemy
* PostgreSQL 16 + PostGIS 3.4
* MapServer (OGC WMS/WFS)
* WebSockets
* Pydantic

---

## Web

* Flask
* Leaflet/OpenLayers
* WebSocket client
* MIL-STD-2525 rendering library

---

## Android

* Kotlin
* Jetpack Compose
* OSMdroid map + MIL-STD-2525C symbology
* WebSocket client (auto-reconnect, 3 s backoff)
* Offline MBTiles caching
* Foreground GPS tracking service

---

## Desktop

* .NET 10 (`PublishAot=true` on the executable)
* Avalonia 11.3 with FluentTheme and `DataGrid`
* Mapsui 5 for the tactical map + tile layers
* SIPSorcery for WebRTC stream support
* CommunityToolkit.Mvvm for source-generated VM properties / commands
* `Microsoft.Extensions.DependencyInjection` composition root
* Per-OS `ILocationService` / `ISecureStorage` skeletons (CoreLocation / Keychain on macOS, GeoClue2 / libsecret on Linux, WinRT / DPAPI on Windows)

---

# 16. Security Requirements

## Authentication

* JWT authentication
* Role-based access control
* Device registration

---

## Tactical Security

* Encrypted communication
* Secure WebSockets
* Audit logging
* Tactical event history

---

# 17. Future Expansion Possibilities

Potential future modules:

* Mesh networking
* Voice communication
* AI threat detection
* GIS analysis
* Mission replay
* Geofencing
* Sensor fusion
* Federated multi-TOC sync (no central server)
* Coalition data-partitioning + auto-redaction

Already shipped (no longer "future"):

* Drone Spot Report (§5.5)
* ATAK / Cursor-on-Target bridge
* Video streaming (camera publisher + recordings)
* Blue-force tracking (live operator GPS)
* MIL-STD-2525C symbology
* MFA TOTP authentication
