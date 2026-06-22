# Arrow — NIST Cybersecurity Framework 2.0 Assessment

**Date:** 2026-05-08  
**Framework:** NIST CSF 2.0 (February 2024)  
**Scope:** Backend (FastAPI), Web Dashboard (Flask), Android Client (Kotlin), Infrastructure (Docker + Caddy)

---

## Maturity Summary

| Function | Category | Maturity | Fixed This PR | Key Gap |
|----------|----------|----------|---------------|---------|
| **GV** | GV.OC | Partial | — | No security mission statement |
| **GV** | GV.RM | None | — | No formal risk register or review cadence |
| **GV** | GV.RR | Partial | — | RBAC in code; no RACI matrix |
| **GV** | GV.PO | Partial | — | No data retention or incident policy |
| **GV** | GV.OV | None | ✅ | Audit log table + `/admin/audit` endpoint added |
| **GV** | GV.SC | Partial | — | No SBOM, no CVE scanning in CI |
| **ID** | ID.AM | Partial | — | No data classification schema |
| **ID** | ID.RA | None | — | No formal threat model |
| **ID** | ID.IM | Partial | — | Tracked in SECURITY.md, no SLA |
| **PR** | PR.AA | Implemented | — | No MFA, rate limiting, account lockout |
| **PR** | PR.AT | None | — | No security training docs |
| **PR** | PR.DS | Partial | — | No encryption at rest, no retention policy |
| **PR** | PR.PS | Partial | ✅ | Security headers added (Flask + Caddy) |
| **PR** | PR.PS | Partial | ✅ | XXE protection added to CoT XML parser |
| **PR** | PR.IR | Minimal | — | No backup strategy, no DR plan |
| **DE** | DE.CM | Minimal | ✅ | Security event logging added to auth + admin |
| **DE** | DE.AE | None | — | No log aggregation, no alert rules |
| **RS** | RS.MA | None | — | No incident response plan |
| **RS** | RS.AN | None | — | No forensic capability |
| **RS** | RS.CO | None | — | No incident communication plan |
| **RS** | RS.MI | Partial | — | No runbooks |
| **RS** | RS.IM | Partial | — | No PIR process |
| **RC** | RC.RP | None | — | No backup/recovery procedure |
| **RC** | RC.CO | None | — | No recovery status communication |
| **RC** | RC.IM | None | — | No recovery metrics |

---

## GV — GOVERN

### GV.OC — Organizational Context
**Status:** Partial

Arrow is a tactical situational awareness platform for SOF operations. The system processes
sensitive operational data including operator GPS positions, tactical object markings (enemy
contacts), CASEVAC 9-liners, and live video streams.

**Security mission:** Protect operational data from unauthorized disclosure, maintain service
availability during missions, and ensure data integrity of all tactical reports.

**Gaps:** No formal security governance document. See `GOVERNANCE.md`.

---

### GV.RM — Risk Management
**Status:** None

No formal risk register or risk management strategy. Known risks documented in `SECURITY.md`
(follow-up items) but without scoring, ownership, or SLA.

**Recommendation:** Establish quarterly risk review. Use CVSS + operational impact scoring.
See `GOVERNANCE.md` for risk register template.

---

### GV.RR — Roles & Responsibilities
**Status:** Partial — enforced in code, not documented

RBAC is implemented: `ADMIN`, `BATTLE_CAPTAIN`, `OPERATOR` roles enforced via
`require_role()` dependency in FastAPI. Role assignment restricted to admins via
`POST /auth/register/admin`.

**Gap:** No RACI matrix for security decisions, incident response, or access provisioning.
See `GOVERNANCE.md`.

---

### GV.PO — Policy
**Status:** Partial

Implemented in code:
- Password minimum 8 characters (`backend/auth/router.py`)
- Token expiry 60 minutes (`config.xml`)
- Self-registration always creates OPERATOR role

Not documented:
- Data retention/deletion schedule
- Acceptable use policy
- Incident classification

See `GOVERNANCE.md`.

---

### GV.OV — Oversight ✅ Implemented
**Status:** Implemented (this PR)

`AuditLog` table (`backend/storage/models.py`) records all security events:
- `LOGIN_SUCCESS` / `LOGIN_FAIL`
- `REGISTER` / `REGISTER_ELEVATED`
- `OPERATOR_UPDATE` / `OPERATOR_DELETE` / `PASSWORD_RESET`

Events are queryable via `GET /admin/audit` (ADMIN only), filterable by `event_type`
and `outcome`. Events also emit to the `arrow.security` Python logger for external
log aggregation.

---

### GV.SC — Supply Chain Risk
**Status:** Partial

- Dependencies pinned via `uv.lock`
- Docker base images versioned (`python:3.14-slim`, `caddy:2-alpine`)
- No CVE scanning in CI, no SBOM generated

**Recommendation:** Add `pip-audit` to CI pipeline. Generate SBOM with
`cyclonedx-py` on each release.

---

## ID — IDENTIFY

### ID.AM — Asset Management
**Status:** Partial

Assets in scope:
| Asset | Type | Sensitivity |
|-------|------|-------------|
| Operator positions (GPS) | Operational | HIGH — reveals force disposition |
| Tactical objects (enemy contacts) | Operational | HIGH — intel value |
| Photos (CASEVAC scenes) | Operational | HIGH — medical/tactical |
| 9-liner reports (MEDEVAC/CAS) | Operational | HIGH — mission-critical |
| Messages | Operational | MEDIUM |
| Fire missions | Operational | CRITICAL — kinetic effects |
| PostgreSQL `arrow` DB | Data store | HIGH |
| `/data/photos/` | Data store | HIGH |
| JWT secret (`config.xml`) | Credential | CRITICAL |

**Gap:** No data flow diagram. No formal data classification policy.

---

### ID.RA — Risk Assessment
**Status:** None

No formal threat model. Key attack scenarios not documented:

1. **Credential theft** → Operator impersonation, location spoofing
2. **Token theft (XSS)** → Full session takeover (localStorage vulnerability)
3. **Unauthorized photo access** → Intel exposure (now fixed: auth required)
4. **Self-registration as ADMIN** → Full system compromise (now fixed)
5. **Fire mission PATCH by OPERATOR** → Mission cancellation/manipulation (now fixed)

**Recommendation:** Conduct STRIDE threat model for each component.

---

### ID.IM — Improvement Process
**Status:** Partial

Known gaps tracked in `SECURITY.md` (follow-up items). No formal SLA or ownership.

---

## PR — PROTECT

### PR.AA — Identity & Access Control
**Status:** Implemented (with gaps)

Implemented:
- bcrypt password hashing
- JWT authentication with 60-minute expiry
- RBAC via `require_role()` on all sensitive endpoints
- Self-registration locked to OPERATOR role
- Auto-logout on token expiry (Android: OkHttp interceptor clears token on 401)

Gaps:
- No MFA
- No account lockout after failed attempts
- No rate limiting on `/auth/login` or `/auth/register`
- No token revocation (Redis required)
- JWT in `localStorage` (XSS risk — see SECURITY.md)

---

### PR.DS — Data Security
**Status:** Partial

- Passwords: bcrypt (rounds=12 default)
- Transit: Caddy handles TLS in production
- At rest: **not encrypted** — PostgreSQL data directory plaintext, photos on disk plaintext
- Photos served with auth (fixed in SECURITY.md PR)
- No data retention/deletion policy

**Recommendation:** SQLCipher for DB encryption. AES-256 for photo storage.
Soft-delete + 90-day purge policy.

---

### PR.PS — Platform Security ✅ Partially Implemented
**Status:** Partially implemented (this PR)

Added:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), camera=(), microphone=()`
- `Content-Security-Policy` (Flask web app)
- Server fingerprinting headers removed in Caddy (`-Server`, `-X-Powered-By`)
- XXE protection in CoT XML parser (`resolve_entities=False, no_network=True`)

Remaining:
- No HTTPS enforcement in Caddyfile (`:80` only — production should use HTTPS)
- No `Strict-Transport-Security` header (requires HTTPS)

---

### PR.IR — Infrastructure Resilience
**Status:** Minimal

- Docker `restart: unless-stopped` on all services
- Health check on backend container
- Named Docker volumes for data persistence
- **No backup strategy**
- **No DR plan**

See `RECOVERY_PLAN.md`.

---

## DE — DETECT

### DE.CM — Continuous Monitoring ✅ Implemented
**Status:** Implemented (this PR)

`backend/audit.py` writes security events to:
1. `audit_logs` PostgreSQL table (queryable via `/admin/audit`)
2. `arrow.security` Python logger (structured, for log aggregation)

Events logged:
| Event | Trigger |
|-------|---------|
| `LOGIN_SUCCESS` | Successful authentication |
| `LOGIN_FAIL` | Failed authentication (wrong password or callsign) |
| `REGISTER` | New OPERATOR self-registration |
| `REGISTER_ELEVATED` | Admin creates BATTLE_CAPTAIN/ADMIN account |
| `OPERATOR_UPDATE` | Admin modifies operator fields (role, rank, status) |
| `OPERATOR_DELETE` | Admin deletes operator |
| `PASSWORD_RESET` | Admin resets operator password |

**Gap:** No brute-force detection, no alerting, no log aggregation service.

---

### DE.AE — Adverse Event Analysis
**Status:** None

No automated alerting. Manual review of `/admin/audit` required.

**Recommendation:**
- Alert on 5× `LOGIN_FAIL` from same IP in 5 minutes → suspected brute force
- Alert on `REGISTER_ELEVATED` with `role=ADMIN` → privilege escalation
- Alert on `OPERATOR_DELETE` → potential insider threat

---

## RS — RESPOND

See `INCIDENT_RESPONSE.md` for the full plan.

**Current state:** No formal IRP. SECURITY.md documents vulnerabilities but not response procedures.

---

## RC — RECOVER

See `RECOVERY_PLAN.md` for RTO/RPO definitions and recovery procedures.

**Current state:** No documented backup or recovery procedure.

---

## What Was Implemented in This PR

| Area | Change | CSF Function |
|------|--------|-------------|
| `AuditLog` model | New DB table for security events | GV.OV, DE.CM |
| `backend/audit.py` | Central audit logging helper | GV.OV, DE.CM |
| Auth security logging | Login, register events with IP + outcome | DE.CM |
| Operator mutation logging | PATCH, DELETE, password reset events | GV.OV, DE.CM |
| `GET /admin/audit` | Queryable audit log API endpoint | GV.OV |
| HTTP security headers | Flask `after_request` + Caddy `header {}` | PR.PS |
| XXE protection | `etree.XMLParser(resolve_entities=False)` in CoT | PR.PS |

## What Remains (Tracked Follow-ups)

| Gap | Effort | Dependency |
|-----|--------|-----------|
| Rate limiting on auth | Medium | `slowapi` library |
| Account lockout | Medium | DB counter column |
| Token revocation | High | Redis |
| MFA (TOTP) | High | `pyotp` + UI changes |
| Encryption at rest | High | SQLCipher migration |
| Log aggregation | High | ELK/Splunk/CloudWatch |
| Brute-force alerting | Medium | Log aggregation + rules |
| HTTPS enforcement | Low | DNS + cert setup |
| SBOM + CVE scanning | Low | `pip-audit` in CI |
| Backup automation | Medium | S3 + cron |
