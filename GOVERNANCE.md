# Arrow — Security Governance

**CSF 2.0:** GV.OC, GV.RM, GV.RR, GV.PO  
**Last reviewed:** 2026-05-08

---

## Security Mission

Arrow processes sensitive operational data for tactical field units. The security mission is:

> **Protect operational data from unauthorized disclosure, ensure data integrity of all tactical reporting, and maintain service availability during active missions.**

Any compromise of operator positions, enemy contact data, or fire mission requests has direct operational consequences (force protection, fratricide risk). Security is a mission-critical function, not a compliance exercise.

---

## Roles & Responsibilities

| Role | System Role | Security Responsibilities |
|------|-------------|--------------------------|
| System Owner | — | Approves security policy, owns risk register, authorizes ADMIN account creation |
| Security Lead | ADMIN | Reviews audit log weekly, manages access provisioning, approves BATTLE_CAPTAIN/ADMIN registrations |
| Battle Captain | BATTLE_CAPTAIN | Manages operational data, acknowledges alerts, closes fire missions |
| Operator | OPERATOR | Maintains device security, reports anomalies, follows OPSEC |

**Account provisioning:** Only an ADMIN may create BATTLE_CAPTAIN or ADMIN accounts via `POST /auth/register/admin`. Self-registration (`POST /auth/register`) always creates OPERATOR role.

---

## Risk Register

| ID | Risk | Likelihood | Impact | Current Controls | Owner | Status |
|----|------|-----------|--------|-----------------|-------|--------|
| R-01 | Brute-force on `/auth/login` | High | High | None | Security Lead | **Open** |
| R-02 | JWT token theft via XSS | Medium | Critical | localStorage (known gap) | Security Lead | **Open** |
| R-03 | Token valid 60 min after compromise | High | High | None (no revocation) | Security Lead | **Open** |
| R-04 | SQLite DB unencrypted at rest | Low | High | File-system access controls | Security Lead | **Open** |
| R-05 | Photos unencrypted at rest | Low | High | Auth required for access | Security Lead | **Open** |
| R-06 | No account lockout | High | Medium | Password policy (8 chars min) | Security Lead | **Open** |
| R-07 | Default JWT secret deployed | Low | Critical | Startup validation blocks it | Security Lead | **Mitigated** |
| R-08 | CORS misconfiguration | Low | High | `ARROW_ALLOWED_ORIGINS` env var | Security Lead | **Mitigated** |
| R-09 | Self-registration as ADMIN | Low | Critical | Role forced to OPERATOR | Security Lead | **Mitigated** |
| R-10 | Unauth photo access | Low | High | JWT required on GET /photos | Security Lead | **Mitigated** |

**Review cadence:** Risk register reviewed quarterly or after any security incident.

---

## Security Policies

### Password Policy
- Minimum length: 8 characters (enforced at backend, not just frontend)
- No maximum length restriction
- Rotation: Recommended every 90 days for ADMIN/BATTLE_CAPTAIN accounts
- Enforcement: `backend/auth/router.py`

### Access Control Policy
- Principle of least privilege: operators receive OPERATOR role by default
- Elevated roles (BATTLE_CAPTAIN, ADMIN) require explicit admin approval
- Account deprovisioning: ADMIN must delete accounts within 24h of personnel departure
- No shared accounts: one callsign per person

### Token Policy
- Expiry: 60 minutes (configurable in `config.xml`)
- Storage: browser localStorage (known XSS risk — migration to httpOnly cookies tracked as R-02)
- Revocation: none (tracked as R-03) — compromise requires password reset + operator re-login
- JWT secret: must not be the default `"change-me-in-production"` value

### Data Retention
- Messages: no automated purge (manual admin action required)
- Reports: no automated purge
- Photos: no automated purge
- Audit logs: no automated purge — retain minimum 90 days
- **Recommendation:** Implement soft-delete + 90-day purge for messages and photos

### Supply Chain
- All dependencies pinned via `uv.lock`
- New dependencies require Security Lead approval
- CVE scanning: manual `pip-audit` before each release (CI automation tracked)
- Docker base images: versioned, reviewed quarterly

---

## Improvement Process

Known security gaps are tracked in `SECURITY.md` (follow-up items) and `NIST_CSF2.md`.

**Remediation SLA by severity:**
| Severity | SLA |
|----------|-----|
| Critical | 48 hours |
| High | 1 week |
| Medium | 1 month |
| Low | Next quarterly review |

**Quarterly security review agenda:**
1. Review risk register — close mitigated items, add new risks
2. Review audit log for anomalies
3. Review and update access list (remove departed personnel)
4. Review dependency CVEs (`pip-audit`)
5. Update `NIST_CSF2.md` maturity scores
