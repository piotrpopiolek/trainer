# Backup & restore runbook (FR-081a)

Local / Compose. **Restore drill** (CI or checklist) is a **F1.prod** gate — this doc is the procedure.

## Nightly backup

Build once (image includes `openssl`):

```bash
docker compose --profile ops build backup
```

```bash
# Requires BACKUP_ENCRYPTION_PASSPHRASE (or BACKUP_AGE_RECIPIENT) in `.env`
docker compose --profile ops run --rm backup
```

Artifacts land in `infra/backup/out/` (bind-mounted outside the app container filesystem; copy off-host in prod). The job streams `pg_dump | openssl` (or age) so **plaintext dumps never** write to that directory — only `.enc` / `.age` (plus atomic `.partial` cleaned on failure).

## Rel16 — backup before prod migration

Before any production `alembic upgrade`:

1. Run a fresh encrypted backup (`docker compose --profile ops run --rm backup`).
2. Confirm `backup.ok` + `LAST_OK`.
3. Copy the artifact off the app host.
4. Only then run migrations.
5. Periodically run the [restore drill](../restore/README.md) (`infra/restore/restore_drill.sh`) so RTO stays realistic.

Structured logs:

- `backup.ok file=… enc_bytes=… elapsed_s=…`
- `backup.fail reason=…`
- Heartbeat file: `infra/backup/out/LAST_OK` (UTC ISO). Silence ≥36h = incident.

Retention: encrypted files older than `BACKUP_RETENTION_DAYS` (default **30**) are deleted by the job.

## Decrypt

OpenSSL (passphrase):

```bash
export BACKUP_ENCRYPTION_PASSPHRASE='…'
openssl enc -d -aes-256-cbc -pbkdf2 -salt \
  -pass env:BACKUP_ENCRYPTION_PASSPHRASE \
  -in infra/backup/out/trainer-YYYYMMDDTHHMMSSZ.dump.enc \
  -out /tmp/trainer.dump
```

age:

```bash
age -d -i /path/to/backup.key \
  -o /tmp/trainer.dump \
  infra/backup/out/trainer-….dump.age
```

## Restore (fresh Compose)

1. Stop writers: `docker compose stop api web purge backup` (keep `db` if restoring in place, or tear down volumes for a clean restore).
2. Fresh DB volume (typical drill):

   ```bash
   docker compose down -v
   docker compose up -d db
   # wait healthy
   ```

3. Restore dump (custom format) as superuser:

   ```bash
   docker compose exec -T db pg_restore -U trainer -d trainer --clean --if-exists < /tmp/trainer.dump
   ```

   Or from host (port **5433**):

   ```bash
   pg_restore -h localhost -p 5433 -U trainer -d trainer --clean --if-exists /tmp/trainer.dump
   ```

4. Re-grant `trainer_app` (nightly dump uses `--no-acl` / `--no-owner`):

   ```bash
   docker compose exec -T db psql -U trainer -d trainer \
     -v ON_ERROR_STOP=1 -f - < infra/restore/regrant_app.sql
   ```

   Automated path: `infra/backup/restore_enc.sh` (decrypt + `pg_restore`) then regrant — see `infra/restore/restore_drill.sh`.

5. Migrations: `docker compose run --rm api alembic current` must equal `head`. If restore is from pre-migration backup, run `alembic upgrade head` only when intentional.
6. Smoke: `GET /api/health`, Google login, spot-check session/progress counts vs pre-backup notes. Optionally `docker compose run --rm api python -m app.seed` (idempotent) to confirm app-role writes.
7. Before any prod Alembic migration: take a fresh encrypted backup first.

## Account purge (FR-006c)

```bash
docker compose --profile ops run --rm purge
```

Select: `purge_after ≤ today AND purge_status IS DISTINCT FROM 'done'`.  
Incident query: `purge_after < current_date - 7 AND purge_status IS DISTINCT FROM 'done'`.

## Auth / rate-limit cleanup (FR-005c/d)

```bash
docker compose --profile ops run --rm cleanup
```

Removes stale `auth_sessions` (≥7d revoked/expired), `oauth_states`, and `rate_limit_buckets` windows older than ~2h.

## Cron (host)

Example daily at 02:15 UTC:

```cron
15 2 * * * cd /path/to/trainer && docker compose --profile ops run --rm backup >>/var/log/trainer-backup.log 2>&1
20 2 * * * cd /path/to/trainer && docker compose --profile ops run --rm purge >>/var/log/trainer-purge.log 2>&1
25 2 * * * cd /path/to/trainer && docker compose --profile ops run --rm cleanup >>/var/log/trainer-cleanup.log 2>&1
```

No HTTP triggers for backup/purge/cleanup.
