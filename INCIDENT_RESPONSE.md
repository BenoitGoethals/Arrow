# Arrow — Incident Response Plan

**CSF 2.0:** RS.MA, RS.AN, RS.CO, RS.MI, RS.IM  
**Last reviewed:** 2026-05-08

---

## Severity Classification

| Level | Definition | Examples | Response SLA |
|-------|-----------|---------|-------------|
| **P1 — Critical** | Active breach, system down, data exfiltration | Unauthorized ADMIN access, mass photo download, DB deleted | 15 min acknowledge, 2h contain |
| **P2 — High** | Auth bypass, privilege escalation, partial outage | Token theft detected, operator account compromised, service degraded | 1h acknowledge, 4h contain |
| **P3 — Medium** | Policy violation, suspicious activity, single user affected | Repeated failed logins, unexpected role change | 4h acknowledge, 24h contain |
| **P4 — Low** | Configuration gap, documentation issue | Missing header, weak password in use | 1 week |

---

## Incident Response Steps

### 1. DETECT
- Source: `/admin/audit` review, operator report, automated log alert
- Any operator can report by messaging the BATTLE_CAPTAIN or ADMIN
- Security Lead reviews `GET /admin/audit?outcome=FAILURE` daily

### 2. TRIAGE
- Classify severity (P1–P4)
- Assign Incident Commander (IC) — Security Lead for P1/P2, System Owner for P1
- Open incident record (git issue, Slack channel, or log entry)

### 3. CONTAIN

**Compromised operator account:**
```bash
# Reset password immediately
curl -X POST /auth/register/admin -H "Authorization: Bearer <admin_token>" \
  -d '{"callsign":"TARGET","password":"<new_strong_pw>","role":"OPERATOR"}'
# Or via admin web UI → Edit operator → Change password
```

**Suspected unauthorized access:**
```bash
# Review audit log for the operator
GET /admin/audit?event_type=LOGIN_SUCCESS  # check recent logins
GET /admin/audit?event_type=OPERATOR_UPDATE  # check role changes
```

**Service compromise:**
```bash
# Take system offline
docker compose down
# Preserve logs before restart
docker logs arrow-backend > incident-backend-$(date +%Y%m%d).log
docker logs arrow-web     > incident-web-$(date +%Y%m%d).log
```

### 4. INVESTIGATE
- Review `audit_logs` table for the incident window
- Correlate: which IP, which operator, what resources accessed
- Determine: what data was accessed/modified, how long was compromise active

```sql
-- Example: all events in incident window
SELECT * FROM audit_logs
WHERE timestamp BETWEEN '2026-05-08T14:00:00Z' AND '2026-05-08T15:00:00Z'
ORDER BY timestamp;

-- Failed logins from suspicious IP
SELECT * FROM audit_logs
WHERE event_type = 'LOGIN_FAIL' AND ip_address = '1.2.3.4'
ORDER BY timestamp;
```

### 5. REMEDIATE
- Apply code fix or configuration change
- Deploy update: `docker compose pull && docker compose up -d`
- Verify fix with targeted test
- Document remediation in incident record

### 6. RECOVER
- Restore data from backup if needed (see `RECOVERY_PLAN.md`)
- Re-enable affected accounts
- Verify system integrity: `curl /health` → `{"status":"ok"}`

### 7. CLOSE & COMMUNICATE
- Notify affected operators (see Communication Templates below)
- Update SECURITY.md with new finding
- Schedule Post-Incident Review within 48 hours

---

## Communication Templates

### Internal — Incident Detected (Slack / Signal)
```
🔴 SECURITY INCIDENT — P[1/2/3]
Time: [UTC timestamp]
Description: [What happened]
Affected: [Which operators / data / services]
IC: [Name]
Status: INVESTIGATING
Next update: [time]
```

### External — Affected Operator Notification
```
Subject: Arrow Security Notice

We detected [suspicious activity / unauthorized access] on [DATE].

What happened: [brief, factual description]
What was affected: [your account / tactical data / photos]
What we did: [immediate action taken]
What you should do: [log out and log back in / change password / no action required]

Questions: Contact your Battle Captain or System Administrator.
```

### Post-Incident Summary (within 48h)
```
INCIDENT SUMMARY — [INCIDENT-ID]

Timeline:
  [time] — incident detected (source: audit log / operator report)
  [time] — contained
  [time] — remediated
  [time] — closed

Root cause: [one sentence]
Impact: [data accessed, duration, operators affected]
Fix applied: [code change / config change / access revoked]
Lessons learned: [what to improve]
Action items: [owner, due date]
```

---

## Runbooks

### RB-01: Compromised Operator Token
1. Identify operator from audit log
2. Reset password via admin UI or API
3. Old tokens become invalid on next 401 (OkHttp clears them automatically on Android)
4. Review audit log for actions taken during compromise window
5. Notify operator

### RB-02: Brute-Force Login Attempt
1. Check `GET /admin/audit?event_type=LOGIN_FAIL` for IP pattern
2. If confirmed brute force: block IP at Caddy/firewall level
3. Check if any `LOGIN_SUCCESS` occurred from same IP — if yes, treat as P1
4. Notify System Owner

### RB-03: Unauthorized Privilege Escalation
1. Check audit log for `REGISTER_ELEVATED` or `OPERATOR_UPDATE` with role change
2. Identify which admin performed the action
3. If unauthorized: revert role via admin UI, investigate admin account compromise
4. If admin account compromised: treat as P1

### RB-04: Mass Data Access (Suspected Exfiltration)
1. Check audit log for unusual photo requests or operator queries
2. Identify operator and data accessed
3. Assess sensitivity of accessed data (operator positions, tactical objects, fire missions)
4. If confirmed: take operator offline, reset token, notify IC
5. Determine if data included classified operational information

---

## Post-Incident Review (PIR)

Schedule within 48 hours of incident close. Agenda:

1. **Timeline** — what happened, when (from audit log)
2. **Root cause** — why did it happen (technical, process, human)
3. **Detection** — how was it found? How long did it go undetected?
4. **Response** — what worked, what was slow
5. **Prevention** — what code/config/process change prevents recurrence
6. **Action items** — owner + due date for each

Record PIR in git (create issue or add to `SECURITY.md`).
