# Arrow — Recovery Plan

**CSF 2.0:** RC.RP, RC.CO, RC.IM  
**Last reviewed:** 2026-05-08

---

## Objectives

| Metric | Target |
|--------|--------|
| Recovery Time Objective (RTO) | 4 hours — service restored from any single failure |
| Recovery Point Objective (RPO) | 24 hours — maximum acceptable data loss |
| Backup test cadence | Monthly restore test on staging |
| Full DR drill cadence | Quarterly |

---

## What Needs Backing Up

| Asset | Location | Backup Method | Frequency | Retention |
|-------|----------|--------------|-----------|-----------|
| `arrow.db` | Docker volume `arrow-data` | `sqlite3 .dump` → S3 | Daily | 30 days |
| `/app/data/photos/` | Docker volume `arrow-data` | `tar.gz` → S3 | Daily | 7 days |
| `config.xml` | Git repository | Git history | On change | 1 year |
| `Caddyfile` | Git repository | Git history | On change | 1 year |
| `docker-compose.yml` | Git repository | Git history | On change | 1 year |

---

## Backup Procedure (Manual — Automate with Cron)

```bash
#!/bin/bash
# run-backup.sh — run on Docker host daily

set -euo pipefail
DATE=$(date +%Y-%m-%d)
BACKUP_DIR="/opt/arrow-backups"

mkdir -p "$BACKUP_DIR"

# 1. Dump SQLite database
docker exec arrow-backend sqlite3 /app/data/arrow.db ".dump" \
  | gzip > "$BACKUP_DIR/arrow-db-$DATE.sql.gz"

# 2. Snapshot photo directory
docker run --rm \
  -v arrow-data:/data:ro \
  -v "$BACKUP_DIR":/backup \
  alpine tar czf "/backup/arrow-photos-$DATE.tar.gz" /data/photos

# 3. Upload to S3 (configure AWS CLI)
aws s3 sync "$BACKUP_DIR/" "s3://YOUR-BUCKET/arrow-backups/"

# 4. Prune local backups older than 7 days
find "$BACKUP_DIR" -name "*.gz" -mtime +7 -delete

echo "Backup complete: $DATE"
```

---

## Recovery Scenarios

### Scenario 1: Database Corruption

**Symptoms:** Backend returns 500 errors, SQLite errors in logs.

```bash
# 1. Stop stack
docker compose down

# 2. List available backups
aws s3 ls s3://YOUR-BUCKET/arrow-backups/ | grep arrow-db

# 3. Download latest good backup
aws s3 cp s3://YOUR-BUCKET/arrow-backups/arrow-db-YYYY-MM-DD.sql.gz ./

# 4. Decompress and restore
gunzip arrow-db-YYYY-MM-DD.sql.gz
docker run --rm \
  -v arrow-data:/data \
  -v "$(pwd)/arrow-db-YYYY-MM-DD.sql":/restore.sql \
  alpine sh -c "sqlite3 /data/arrow.db < /restore.sql"

# 5. Verify integrity
docker run --rm -v arrow-data:/data alpine \
  sqlite3 /data/arrow.db "PRAGMA integrity_check;"
# Expected output: "ok"

# 6. Restart
docker compose up -d

# 7. Verify
curl http://localhost:6200/health
```

### Scenario 2: Docker Host Failure (Full Re-provision)

**Symptoms:** Host unreachable, all containers down.

```bash
# On new host:

# 1. Install Docker + Compose
curl -fsSL https://get.docker.com | sh

# 2. Clone repository
git clone https://github.com/BenoitGoethals/Arrow.git
cd Arrow

# 3. Restore database from S3
mkdir -p /opt/arrow-data
aws s3 cp s3://YOUR-BUCKET/arrow-backups/arrow-db-YYYY-MM-DD.sql.gz ./
gunzip arrow-db-YYYY-MM-DD.sql.gz
docker run --rm \
  -v arrow-data:/data \
  -v "$(pwd)/arrow-db-YYYY-MM-DD.sql":/restore.sql \
  alpine sh -c "mkdir -p /data && sqlite3 /data/arrow.db < /restore.sql"

# 4. Restore photos
aws s3 cp s3://YOUR-BUCKET/arrow-backups/arrow-photos-YYYY-MM-DD.tar.gz ./
docker run --rm \
  -v arrow-data:/data \
  -v "$(pwd)/arrow-photos-YYYY-MM-DD.tar.gz":/photos.tar.gz \
  alpine tar xzf /photos.tar.gz -C /data/

# 5. Set production config
# Edit config.xml — set strong JWT secret, production DB URL
vim config.xml

# 6. Set ARROW_ALLOWED_ORIGINS in docker-compose.yml to production domain

# 7. Start stack
docker compose up -d

# 8. Verify
curl http://localhost:6200/health
```

**Estimated time:** 2–4 hours with practiced runbook.

### Scenario 3: Photo Loss

```bash
# Download archive and extract
aws s3 cp s3://YOUR-BUCKET/arrow-backups/arrow-photos-YYYY-MM-DD.tar.gz ./
docker run --rm \
  -v arrow-data:/data \
  -v "$(pwd)":/src \
  alpine tar xzf /src/arrow-photos-YYYY-MM-DD.tar.gz -C /data/
docker compose restart web
```

### Scenario 4: Rolled Back Bad Deployment

```bash
# Roll back to previous image tag
docker compose pull --quiet
git log --oneline -5  # find last good commit
git checkout <COMMIT>
docker compose build
docker compose up -d
```

---

## Recovery Validation Checklist

After any recovery, verify:

- [ ] `curl http://localhost:6200/health` → `{"status":"ok"}`
- [ ] Admin login succeeds via web UI
- [ ] Operator list loads in admin dashboard
- [ ] Tactical map shows operator positions (if any had recent GPS)
- [ ] Photo upload and retrieval works
- [ ] WebSocket connection established (check browser console)
- [ ] Audit log accessible: `GET /admin/audit`

---

## Recovery Communication

See `INCIDENT_RESPONSE.md` for communication templates.

During recovery:
1. Post initial notice: "Arrow service unavailable — recovery in progress"
2. Update every 30 minutes with status and ETA
3. Post restoration notice: "Service restored — verify your data and report any issues"
4. Post summary within 24 hours: what happened, what was lost (if any), what changed

---

## Continuous Improvement

After each recovery event:

1. Record actual RTO vs target → update this document
2. Identify what slowed recovery (missing tools, unclear steps, missing credentials)
3. Update runbooks with lessons learned
4. Schedule next backup restore test if not done in last 30 days

**Backup test procedure (monthly):**
```bash
# Restore to staging environment, not production
docker volume create arrow-test-data
aws s3 cp s3://YOUR-BUCKET/arrow-backups/arrow-db-$(date +%Y-%m-%d).sql.gz ./
gunzip arrow-db-$(date +%Y-%m-%d).sql.gz
docker run --rm -v arrow-test-data:/data -v "$(pwd)/arrow-db-$(date +%Y-%m-%d).sql":/r.sql \
  alpine sh -c "sqlite3 /data/arrow.db < /r.sql"
docker run --rm -v arrow-test-data:/data alpine sqlite3 /data/arrow.db "PRAGMA integrity_check;"
echo "Backup test passed: $(date)"
docker volume rm arrow-test-data
```
