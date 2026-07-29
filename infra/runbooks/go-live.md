# Go-live checklist — F1.prod

Operator checklist before public prod (after F1.0/F1.1 code + F1.prod gates).  
Source of truth: `docs/prd.md` §1.4a / FR-081a / FR-020a / FR-005a–d.

## A. Gates already in CI / repo

| Check | How |
|-------|-----|
| Content 60× `pl-PL` ready | `TRAINER_CONTENT_GATE_STRICT=1 python scripts/check_content_gate.py` (CI job `content-gate`) |
| Restore drill | `bash infra/restore/restore_drill.sh` (CI job `restore-drill`) |
| IDOR suite | `docker compose run --rm api pytest -m idor` |
| Backend + frontend CI | `.github/workflows/ci.yml` green on `main` |
| Local preflight smoke | `python scripts/go_live_smoke.py` (or `make go-live-smoke`) |
| Ops cron template | `infra/cron/trainer.cron.example` |

## B. Host / Compose prod

```bash
# Secrets in private .env (never commit)
# APP_ENV=production
# RATE_LIMIT_STORE=postgres
# PUBLIC_ORIGIN=https://<your-domain>
# GOOGLE_* pointing at that origin
# CSRF_SECRET, BACKUP_ENCRYPTION_PASSPHRASE, DB passwords

docker compose -f docker-compose.yml -f infra/docker-compose.prod.yml up -d --build
docker compose run --rm api alembic -c backend/alembic.ini upgrade head
docker compose run --rm api python -m app.seed
```

API refuses to start in `production`/`staging` if rate-limit is `memory`, CSRF/Google secrets are empty, or origin/redirect still use localhost.

## C. Ops cron (host)

Copy and edit [infra/cron/trainer.cron.example](../cron/trainer.cron.example). Details: [backup-restore.md](backup-restore.md). Minimum:

- nightly encrypted backup (`profile ops` → `backup`)
- purge + auth/rate-limit cleanup
- heartbeat silence ≥36h = incident (purge); backup silence per FR-081a

Backup destination must be **off the app host** in real prod (bind-mount `infra/backup/out` is OK for dogfood only).

## D. Manual dogfood (founder)

0. `python scripts/go_live_smoke.py` must print `go_live_smoke.ok` (sets expectations for env + stack).
1. Trust TLS / real cert; open `PUBLIC_ORIGIN`
2. Google login → onboarding + health disclaimer
3. Log CC session online; confirm progression surface
4. Airplane mode: log session → online → flush / conflicts UI
5. Settings: schedule/TZ, sync status, `storage.persist` banner if needed
6. Export / soft-delete account smoke (CSRF)
7. `docker compose --profile ops run --rm backup` then restore drill on a **non-prod** volume

## E. Content (PCO)

CI gate ≠ product acceptance. Founder reviews 60 step descriptions for accuracy and no book quotes (FR-020a).  
Legal v2 (`health_disclaimer` + `privacy_policy`, w tym retencja backupów ≤30 dni) — founder should skim before public prod; dogfood users re-accept disclaimer after seed upgrade.

## F. Rel16 — before any prod Alembic

1. Fresh encrypted backup
2. Migrate
3. Smoke health + login + catalog counts `6|60|60`

## G. Explicitly still out of F1

Redis, ARQ, R2, Apple OAuth, Garmin, Web Push, AI agent, progress photos.
