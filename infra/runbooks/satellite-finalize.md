# Satellite daily-outcome finalizer runbook (FR-053 / Stage 5)

Compose one-shot job (no Redis/ARQ). Finalizes overdue **pending** satellite
daily outcomes (`status=pending`, `finalize_after <= now`, failed-day path).

## Index

Partial index (migration Stage 3):

```text
ix_satellite_daily_outcomes_pending_finalize
  ON satellite_daily_outcomes (status, finalize_after)
  WHERE status = 'pending'
```

## Bounded batch

Env:

| Variable | Default | Meaning |
|----------|---------|---------|
| `SATELLITE_FINALIZE_LIMIT` | `500` | Max distinct `(user_id, exercise_id)` pairs per run |
| `SATELLITE_FINALIZE_HEARTBEAT_PATH` | empty | Optional UTC ISO heartbeat file on success |

Orchestrator re-validates each pair under `pg_advisory_xact_lock(user, exercise)`.

## Run

```bash
docker compose --profile ops run --rm satellite-finalize
# or
docker compose run --rm api python -m app.jobs.satellite_finalize
```

Cron example: `infra/cron/trainer.cron.example`.

## Structured logs / metrics

| Event | When |
|-------|------|
| `satellite_finalize.ok` | Pair finalized (`count` outcomes) |
| `satellite_finalize.fail` | Exception for a pair (TX rolled back; batch continues) |
| `satellite_finalize.batch` | End of run: `finalized`, `pairs_ok`, `fail`, `due_pairs` |
| `satellite_finalize.heartbeat_write_failed` | Heartbeat path set but unwritable |

Also emitted by domain paths (Today / session / sync / decide):

- late-after-deadline / `progression_skipped=daily_finalized`
- pending → finalized / cancelled outcomes
- config mismatch / `config_not_active_for_day`
- recommendation accept / decline / stale
- deadlock retry (orchestrator advisory lock)

## Heartbeat / incident

If `SATELLITE_FINALIZE_HEARTBEAT_PATH` is set, a successful batch (`fail=0`)
writes UTC ISO timestamp. **Silence ≥36 h** with pending overdue rows = incident
(same ops posture as purge/backup).

Lazy finalizer also runs on `GET /today`, session create, and sync push — cron
covers users who do not open the app.
