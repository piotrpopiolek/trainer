# Restore drill (F1.prod / FR-081a)

Automated checklist: encrypted backup → wipe Compose volume → restore → `alembic` at head → CC catalog counts.

## Run locally

```bash
bash scripts/gen_dev_env.sh   # if no .env
# ensure BACKUP_ENCRYPTION_PASSPHRASE is set in .env
bash infra/restore/restore_drill.sh
```

On Windows use **Git Bash** (not WSL path mixing). The script sets `MSYS_NO_PATHCONV` so Docker entrypoints are not rewritten to `C:/Program Files/...`.

Expect `restore_drill.ok` and counts `6|60|60` (CC exercises | steps | pl-PL ready translations).

Restore step uses `infra/backup/restore_enc.sh` inside the `backup` image (`--entrypoint sh … /scripts/restore_enc.sh`), then `regrant_app.sql` (dump is `--no-acl`).

## CI

Job `restore-drill` in `.github/workflows/ci.yml` runs the same script on `workflow_dispatch` and on `main`/`master` pushes (and PRs that touch backup/restore/seed).

## Manual Rel16 (before prod Alembic)

1. `docker compose --profile ops run --rm backup` (fresh encrypted artifact off-host)
2. `alembic upgrade head`
3. Smoke login + catalog counts

See also: [backup-restore runbook](../runbooks/backup-restore.md).
