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

3. **Backend Services**

   * FastAPI backend
   * WebSocket realtime communication
   * REST APIs
   * CoT (Cursor on Target) messaging
   * SQLite storage

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

Android tactical user.

Capabilities:

* View tactical map
* View teammates
* Send GPS position
* Plot enemy positions
* Create markers
* Send contact reports
* Send enemy spot reports
* Send 9-liners
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

---

## 5.4 9-Liners

Support structured tactical forms:

* CASEVAC
* MEDEVAC
* CAS requests
* Tactical support requests

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
SQLite
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
 ├── map/
 ├── tracking/
 ├── messaging/
 ├── reports/
 ├── alerts/
 ├── cot/
 ├── offline/
 ├── auth/
 └── settings/
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
* SQLite
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
* Maps SDK
* WebSocket client
* Offline tile caching

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

* Drone integration
* ATAK interoperability
* Mesh networking
* Voice communication
* Video streaming
* Blue force tracking
* AI threat detection
* GIS analysis
* Mission replay
* Geofencing
* Sensor fusion
