# Arrow — OWASP Top 10 Security Audit

**Date:** 2026-05-08  
**Branch:** security/owasp-fixes  
**Scope:** Full codebase — backend (FastAPI), web dashboard (Flask), Android client

---

## Summary

| Severity | Count | Fixed in this PR |
|----------|-------|-----------------|
| Critical | 2 | 2 |
| High | 4 | 3 |
| Medium | 9 | 5 |
| Low | 2 | 1 |

---

## Findings & Fixes

### A01 — Broken Access Control

#### 1.1 Unauthenticated list endpoints `HIGH` ✅ Fixed
**Files:** `backend/api/teams.py`, `platoons.py`, `sections.py`, `companies.py`, `battle_management/router.py`

`GET /teams`, `GET /platoons`, `GET /sections`, `GET /companies`, and `GET /battles` had **no authentication**.
Any anonymous request could enumerate the full military unit hierarchy and active battles.

```python
# Before — no auth
@router.get("", response_model=list[TeamOut])
def list_teams(db: Session = Depends(get_db)) -> list[Team]:
```

**Fix:** Added `get_current_operator` dependency to all five list endpoints.

---

#### 1.2 Fire mission PATCH lacks role check `MEDIUM` ✅ Fixed
**File:** `backend/fire_missions/router.py`

Any authenticated operator could update the status, FDC assignment, or notes of any fire mission —
including cancelling missions they did not create.

**Fix:** Status transitions and FDC assignment now require `ADMIN` or `BATTLE_CAPTAIN` role.

---

#### 1.3 Inconsistent tactical-object authorization `MEDIUM` — Documented
**File:** `backend/api/tactical_objects.py:51`

BATTLE_CAPTAIN can delete any tactical object regardless of creator; an OPERATOR can only delete their own.
The asymmetry is intentional for command-and-control but should be explicitly documented.  
No code change made — current behavior is acceptable by design.

---

### A02 — Cryptographic Failures

#### 2.1 Default JWT secret `"change-me-in-production"` `CRITICAL` ✅ Fixed
**Files:** `config.xml`, `backend/auth/jwt_auth.py`

If the operator forgets to change the JWT secret, any attacker who knows the default can forge tokens for
any role — including ADMIN — without knowing any credentials.

**Fix:** Added startup validation: the backend now refuses to start in production when the secret is the
known-weak default. A `ARROW_INSECURE_SECRET_OK=1` env var is required to override in dev/CI.

---

#### 2.2 JWT tokens stored in `localStorage` `HIGH` — Documented
**File:** `web/templates/login.html`

Tokens in `localStorage` are accessible to any JavaScript on the page. An XSS exploit immediately
yields a working session token. Migrating to `httpOnly; Secure; SameSite=Strict` cookies requires a
significant auth architecture change and is tracked as a follow-up issue.

---

#### 2.3 Token expiry 24 hours (1440 min) `MEDIUM` ✅ Fixed
**File:** `config.xml`, `backend/config/xml_config.py`

A stolen token was valid for 24 hours.  
**Fix:** Default reduced to **60 minutes** (still configurable in `config.xml`).

---

#### 2.4 No token revocation `MEDIUM` — Documented
Issued JWTs cannot be invalidated before expiry. Requires a Redis-backed token blacklist.
Tracked as a follow-up infrastructure task.

---

### A03 — Injection

#### 3.1 Raw SQL with `__import__` in admin stats `MEDIUM` ✅ Fixed
**File:** `backend/admin/router.py:59-63`

```python
# Before — raw SQL via obfuscated import
role_rows = db.execute(
    __import__("sqlalchemy").text("SELECT role, COUNT(*) FROM operators GROUP BY role")
).fetchall()
```

While the query itself is not user-controlled, raw SQL is fragile and the `__import__` pattern obscures
the dependency. **Fix:** Replaced with a proper SQLAlchemy `group_by` query.

---

### A04 — Insecure Design

#### 4.1 No rate limiting on auth endpoints `HIGH` — Documented
**File:** `backend/auth/router.py`

`/auth/login` and `/auth/register` accept unlimited requests per IP. An attacker can:
- Brute-force passwords indefinitely
- Enumerate callsigns via 409 vs 201 response codes on `/auth/register`

**Recommendation:** Add `slowapi` (FastAPI rate-limiting library). Suggested limits:
- Login: 10 requests / minute / IP
- Register: 3 requests / minute / IP

Not implemented in this PR — requires infrastructure decision (in-process vs Redis).

---

#### 4.2 No account lockout `HIGH` — Documented
No failed-attempt counter. Brute-force attack has unlimited attempts.  
Requires persistent state (DB counter + last-attempt timestamp or Redis).

---

#### 4.3 No backend password policy `MEDIUM` ✅ Fixed
**File:** `backend/auth/router.py`

Frontend enforced `minlength="6"` but the backend accepted single-character passwords via direct API calls.

**Fix:** Backend now rejects passwords shorter than 8 characters.

---

#### 4.4 Hardcoded seed credentials `MEDIUM` — Documented
**File:** `backend/storage/seed.py`

Default accounts `benoit` / `ranger14` and `capt` / `ranger14` are created on first boot.
These credentials are public in the source code.  
**Recommendation:** Change passwords immediately after first boot, or pass seed credentials via env vars.

---

### A05 — Security Misconfiguration

#### 5.1 CORS `allow_origin_regex=".*"` with `allow_credentials=True` `CRITICAL` ✅ Fixed
**File:** `backend/main.py`

```python
# Before — allows any origin to make credentialed requests
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    ...
)
```

An attacker's website could make authenticated API requests on behalf of any logged-in user.

**Fix:** CORS origins are now controlled by `ARROW_ALLOWED_ORIGINS` env var (comma-separated list).
Default: `http://localhost:6002` (dev only). Production must set this explicitly.

---

#### 5.2 Flask `debug=True` in standalone `run()` `HIGH` ✅ Fixed
**File:** `web/app.py`

The `run()` function (used by `uv run arrow-web`) enabled debug mode, which:
- Shows interactive tracebacks in the browser on 500 errors
- Exposes the Werkzeug debugger PIN (code execution if accessed)
- Auto-reloads on file changes

**Fix:** `debug` is now driven by the `FLASK_DEBUG` env var, defaulting to `False`.

---

#### 5.3 Exception detail leaked in CoT endpoint `MEDIUM` ✅ Fixed
**File:** `backend/cot/router.py`

Raw exception messages were returned to clients, exposing internal parsing details.

**Fix:** Error message is now sanitized to a generic string; the original exception is logged server-side.

---

#### 5.4 Name fields have no length constraints `LOW` ✅ Fixed
**Files:** `backend/api/schemas.py`

`CompanyIn`, `PlatoonIn`, `SectionIn`, `TeamIn` accepted names of arbitrary length — allowing
oversized inputs to stress the database and UI rendering.

**Fix:** Added `min_length=1, max_length=120` constraints.

---

### A08 — Software and Data Integrity Failures

#### 8.1 No CSRF protection `MEDIUM` — Documented
The Flask web app has no CSRF middleware. A malicious page could submit state-changing requests
cross-origin. Mitigated partially by JWT Bearer tokens (not sent in browser-initiated cross-site
requests), but form-based flows are unprotected.  
**Recommendation:** Add `flask-talisman` with appropriate CSP and `SameSite` cookie policy as part of
the localStorage→cookie migration.

---

### A09 — Security Logging and Monitoring Failures

#### 9.1 No security event logging `MEDIUM` — Documented
Failed logins, role changes, operator creation, and admin actions are not logged.
**Recommendation:** Add structured log entries for all auth events and admin mutations using Python's
`logging` module at `WARNING` level.

---

### A10 — Server-Side Request Forgery

#### 10.1 Flask proxy subpath forwarding `MEDIUM` — Documented
**File:** `web/app.py`

The Flask `/api/<path:subpath>` proxy forwards to `BACKEND_URL/{subpath}` without an endpoint
allowlist. Currently safe because `BACKEND_URL` is hardcoded, but fragile by design.  
**Recommendation:** Add explicit allowlist of proxied path prefixes if the backend URL ever becomes
configurable.

---

## What Was Not Fixed (Tracked Follow-ups)

| Issue | Reason |
|-------|---------|
| JWT in `localStorage` → `httpOnly` cookies | Major auth architecture refactor |
| Rate limiting on auth endpoints | Requires `slowapi` + Redis decision |
| Account lockout | Requires persistent attempt counter |
| Token revocation / blacklist | Requires Redis |
| CSRF middleware | Coupled to cookie migration |
| Security event logging | Requires logging infrastructure decision |
| Audit trail for admin actions | Requires separate audit log table |
