# Proposal — JDSS / STANAG 4677 Gateway for Arrow

**Status:** Draft for review · **Author:** (Benoit) · **Scope:** Bidirectional interoperability
between Arrow and NATO Dismounted Soldier Systems (DSS) that speak **STANAG 4677**, via a
**separate gateway service** rather than changes to Arrow's core.

> ⚠️ **Schema caveat.** STANAG 4677 (Allied Engineering Publication **AEP-4677**, "Dismounted
> Soldier Systems Standards") is a controlled NATO document. The exact message names, XSD element
> names, transport binding and conformance rules **must be taken from the edition you are
> certifying against** — this proposal designs the *adapter architecture* and the *Arrow-side
> mapping*; the on-the-wire codec is schema-driven and built from the official XSDs. Anywhere this
> doc names a 4677 message/field it is a **placeholder to be bound to the real schema**.

---

## 1. Goal

Let Arrow exchange tactical information **both ways** with any STANAG 4677-conformant DSS / JDSS
node — without coupling Arrow's FastAPI core to the standard. Concretely:

- **Inbound (4677 → Arrow):** foreign blue-force positions, messages, alerts, reports and
  overlays appear in Arrow (web / front / Android / ATAK bridge) like any native entity.
- **Outbound (Arrow → 4677):** Arrow operator tracks, chat, alerts, reports and tactical graphics
  are published to the 4677 network for other DSS nodes.

## 2. Design principle — a pluggable gateway, not a core change

This mirrors how the existing ATAK/CoT bridge and the web/front/android clients already work:
**everything integrates through Arrow's public REST + WebSocket API.** The README's §11
"pluggable / SOLID" rule applies — Arrow's core should not learn a second tactical standard.

So we add a **standalone gateway service** (`jdss/`, console script `arrow-jdss`, its own
container) that:

- speaks **STANAG 4677** on its *north* side (to JDSS peers), and
- speaks **Arrow's existing API** on its *south* side (HTTP `:6001` + `/ws`), authenticating with a
  dedicated **service-account JWT**.

Arrow itself needs only two small, optional additions (see §7): a service role and an
`external_id` correlation column. Everything else is unchanged.

```
        NATO DSS / JDSS network                 Arrow
   ┌───────────────────────────┐        ┌──────────────────────────┐
   │  Peer DSS nodes (4677)     │        │  FastAPI backend :6001    │
   │  BFT · msg · alert · CoP   │        │  REST + WebSocket /ws     │
   └─────────────▲─────────────┘        └─────────▲────────────────┘
                 │ STANAG 4677 (XML/PKI)           │ HTTPS + WS (service JWT)
                 │                                  │
        ┌────────┴──────────────────────────────────┴────────┐
        │                 arrow-jdss  (separate service)       │
        │                                                      │
        │  transport/  ← 4677 binding (TCP/TLS, pub-sub, …)    │
        │  codec/      ← XSD-generated 4677 ⇄ python (xsdata)  │
        │  translate/  ← 4677 entity  ⇄  Arrow model           │
        │  state/      ← correlation store (UUID ⇄ Arrow id)   │
        │  arrow_io/   ← REST client + WS subscriber           │
        └──────────────────────────────────────────────────────┘
```

Independently deployable, independently **certifiable**, and it can be killed/restarted without
touching the COP.

## 3. What STANAG 4677 carries (capability areas)

AEP-4677 defines an information-exchange data model + message set for dismounted soldier systems.
The functional areas relevant to Arrow (confirm exact message catalogue against the edition):

| 4677 capability area        | Arrow counterpart                          | Arrow channel / endpoint |
|-----------------------------|--------------------------------------------|--------------------------|
| Blue-force tracking (position, identity, status) | `Operator` track / presence | `tracking`, `presence` · `POST /tracking` |
| Text / C2 messaging         | `Message`                                  | `chat` · `POST /messages` |
| Alerts / warnings (man-down, contact, NBC) | `Alert`                          | `alert` · `POST /alerts` |
| Reports (incl. 9-liners)    | `Report` (CASEVAC/MEDEVAC/CONTACT/SPOT/…)  | `report` · `POST /reports` |
| Overlays / tactical graphics| `TacticalObject` (APP-6 + geometry)        | `tactical-object` · `POST /tactical-objects` |
| Imagery / attachments       | `Photo` + pinned POI                       | `POST /photos`, `tactical-object` |
| Tasking / orders (optional) | OPORD / missions                           | `missions`, `opord` |

The first three rows are the **high-value core**; overlays/imagery/tasking are later phases.

## 4. Bidirectional message flows

### 4.1 Inbound — JDSS → Arrow
1. `transport/` receives a 4677 message (e.g. a position report).
2. `codec/` parses XML → typed python object (xsdata bindings from the official XSD).
3. `translate/` maps it to an Arrow call, resolving the foreign entity via `state/` (UUID ⇄ Arrow id).
4. `arrow_io/` calls the matching Arrow REST endpoint with the service JWT; Arrow persists +
   broadcasts on its WS channel → it shows up everywhere (web/front/android/ATAK) for free.

### 4.2 Outbound — Arrow → JDSS
1. `arrow_io/` holds a long-lived authenticated WebSocket to Arrow `/ws`.
2. On each event (`tracking`, `chat`, `alert`, `report`, `tactical-object`, `presence`):
3. `translate/` builds the corresponding 4677 message, `codec/` serialises it,
4. `transport/` publishes it to the 4677 peers.

### 4.3 Loop prevention & correlation
Same discipline as the CoT bridge:
- Tag the **origin** of every entity (`external_id` / origin field) so a message that came *from*
  4677 is never re-emitted *back* to 4677, and vice-versa.
- `state/` keeps a stable bidirectional map **4677 URN/UUID ⇄ Arrow id** (backed by the Arrow
  PostgreSQL database), so updates correlate instead of creating duplicates, and identity is
  consistent across restarts.

## 5. Proposed module layout (`jdss/`, sibling of `backend/` `web/` `front/`)

```
jdss/
  __init__.py
  main.py            # asyncio entrypoint; console script `arrow-jdss`
  config.py          # reads <jdss> block from config.xml + env
  transport/         # 4677 binding: TCP/TLS server+client / pub-sub adapter
  codec/             # xsdata-generated bindings from official AEP-4677 XSDs + (de)serialise
  translate/
      bft.py         # position/status  ⇄  tracking/presence
      messaging.py   # text             ⇄  chat
      alerts.py      # warnings         ⇄  alert
      reports.py     # reports/9-liners ⇄  report
      overlays.py    # graphics         ⇄  tactical-object
  state/             # correlation store (PostgreSQL): UUID ⇄ Arrow id, origin tags
  arrow_io/
      rest.py        # authenticated REST client (service JWT)
      ws.py          # resilient WS subscriber (auto-reconnect, backpressure)
  tests/             # golden-file codec tests + translate round-trips
```

Consistent with the repo's multi-app pattern (shared `pyproject.toml`, `arrow-backend` /
`arrow-web` / `arrow-front` console scripts → add **`arrow-jdss`**).

## 6. Transport & security (confirm against the standard)

- **Binding:** 4677 typically runs over IP. Decide TCP/TLS vs UDP vs a web-service/pub-sub binding
  per the edition/profile you target. The `transport/` package isolates this so the codec and
  translators don't care.
- **PKI / mTLS:** dismounted-system interop usually mandates mutual-TLS with a NATO/national PKI.
  Plan certificate provisioning + validation in `transport/`.
- **Bandwidth:** tactical radio is low-bandwidth — position reporting needs rate-limiting /
  delta-encoding / dead-reckoning thresholds. Make publish cadence configurable.
- **Arrow side:** dedicated **service account** + a new minimal **`GATEWAY` role** (or reuse a
  scoped token) so gateway traffic is auditable and least-privilege.

## 7. Minimal Arrow-core additions (small, optional)

1. **`external_id` columns** on `operators`, `messages`, `alerts`, `reports`, `tactical_objects`
   (nullable string) — stores the originating 4677 URN so the gateway correlates without a side
   table, and clients can show provenance. Additive migration (same pattern as `position_source`).
2. **Service role / token** for the gateway (audited, least-privilege).
3. *(Optional)* a small **batch ingest** endpoint for BFT bursts, if per-call REST proves too chatty
   at scale (otherwise reuse existing endpoints).

Everything else is gateway-only. **No change to Arrow's COP, ATAK bridge, or clients.**

## 8. Delivery phases

| Phase | Deliverable | Why first |
|-------|-------------|-----------|
| **0 — Foundation** | XSD intake → `codec/` gen; `state/` store; service account; skeleton service + health; docker-compose `jdss` service; golden-file codec tests | De-risks the wire format early |
| **1 — BFT both ways** | Position/identity/status ⇄ `tracking`/`presence` | Highest value, simplest mapping |
| **2 — Messaging + Alerts** | text ⇄ `chat`; warnings ⇄ `alert` | Operational comms |
| **3 — Reports + Overlays** | reports/9-liners ⇄ `report`; graphics ⇄ `tactical-object` (APP-6 ↔ 4677 symbology) | Richer COP |
| **4 — Hardening / Certification** | PKI/mTLS, conformance test vs reference peer, soak/bandwidth tuning, audit | Fielding readiness |

Each phase is shippable on its own; Phase 1 already gives a working two-way blue-force picture.

## 9. Testing strategy

- **Codec golden files:** real 4677 sample messages ⇄ python, byte-stable round-trips.
- **Translate round-trips:** Arrow entity → 4677 → Arrow entity equality (and reverse).
- **Loopback integration:** run `arrow-jdss` against a dev Arrow + a stub 4677 peer; assert a peer
  position shows in Arrow and an Arrow track reaches the peer.
- **Conformance:** validate against the official AEP-4677 test vectors / reference implementation if
  available to you.

## 10. Open questions (need your input)

1. **Which AEP-4677 edition** are you certifying against, and **do you have the XSDs / message
   catalogue**? (Drives `codec/`.)
2. **Transport/profile:** TCP/TLS? UDP? a web-service or pub-sub binding? unicast vs multicast?
3. **Interaction model:** push (pub/sub) vs request/response/pull for BFT and overlays?
4. **Identity scheme:** how are entities named (URN/UUID), and is there an agreed national/coalition
   namespace to map Arrow operators into?
5. **Security:** required PKI / mTLS / classification handling?
6. **Scale:** expected node count + BFT rate (sets the batch-ingest / rate-limit decisions)?
7. **Is there a reference peer or conformance harness** we can integration-test against?

## 11. Recommendation

Build `arrow-jdss` as a **standalone, schema-driven gateway** that bridges STANAG 4677 to Arrow's
existing REST + WS API, with a tiny `external_id` correlation addition to the core. Start with
**Phase 0 + Phase 1 (BFT both ways)** to prove the wire format and the loop-safe correlation end to
end, then layer messaging/alerts/reports/overlays. This keeps Arrow's COP, the ATAK/CoT bridge and
all clients untouched while giving NATO DSS interoperability that can be certified independently.
