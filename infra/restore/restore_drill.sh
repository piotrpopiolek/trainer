#!/bin/sh
# F1.prod restore drill (FR-081a): seed → encrypted backup → wipe → restore → head + counts.
# Compose / CI only — no HTTP triggers. Passphrase MUST come from .env (no hardcoded default).
set -eu
set -o pipefail

# Git Bash on Windows rewrites /bin/sh → C:/Program Files/...; keep Docker paths literal.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

ROOT="$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "restore_drill.fail reason=missing_env" >&2
  exit 1
fi

# Do not `source` .env — values may contain shell metacharacters (OAuth secrets).
# Compose services load .env via env_file; we only assert passphrase presence.
if ! grep -Eq '^BACKUP_ENCRYPTION_PASSPHRASE=.+' .env; then
  echo "restore_drill.fail reason=backup_passphrase_missing" >&2
  exit 1
fi

echo "restore_drill.start"

docker compose up -d db
i=0
while [ "$i" -lt 30 ]; do
  if docker compose exec -T db pg_isready -U trainer -d trainer >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 2
done

docker compose run --rm api alembic -c backend/alembic.ini upgrade head
docker compose run --rm api python -m app.seed

mkdir -p infra/backup/out
rm -f infra/backup/out/trainer-*.dump.enc infra/backup/out/trainer-*.dump.age 2>/dev/null || true

docker compose --profile ops build backup
docker compose --profile ops run --rm backup

ENC_BASENAME="$(ls -1t infra/backup/out/trainer-*.dump.enc | head -n1 | xargs -n1 basename)"
if [ -z "$ENC_BASENAME" ]; then
  echo "restore_drill.fail reason=no_encrypted_artifact" >&2
  exit 1
fi
echo "restore_drill.backup file=${ENC_BASENAME}"

docker compose down -v
docker compose up -d db
i=0
while [ "$i" -lt 30 ]; do
  if docker compose exec -T db pg_isready -U trainer -d trainer >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 2
done

docker compose --profile ops run --rm \
  -e ENC_BASENAME="$ENC_BASENAME" \
  --entrypoint sh \
  backup \
  /scripts/restore_enc.sh

# Dump omits ACLs (--no-acl); re-grant app role before any trainer_app smoke.
docker compose exec -T db psql -U trainer -d trainer \
  -v ON_ERROR_STOP=1 -f - < infra/restore/regrant_app.sql

# App-role smoke: seed must be able to write (catches missing grants).
docker compose run --rm api python -m app.seed >/dev/null

CURRENT="$(docker compose run --rm --no-deps api alembic -c backend/alembic.ini current)"
echo "restore_drill.alembic ${CURRENT}"
echo "${CURRENT}" | grep -q "(head)" || {
  HEAD_ID="$(docker compose run --rm --no-deps api alembic -c backend/alembic.ini heads | awk '{print $1}' | head -n1)"
  echo "${CURRENT}" | grep -q "${HEAD_ID}" || {
    echo "restore_drill.fail reason=alembic_not_head" >&2
    exit 1
  }
}

COUNTS="$(docker compose exec -T db psql -U trainer -d trainer -Atc \
  "SELECT
     (SELECT COUNT(*) FROM exercises WHERE kind='cc')::text || '|' ||
     (SELECT COUNT(*) FROM exercise_steps es
        JOIN exercises e ON e.id = es.exercise_id WHERE e.kind='cc')::text || '|' ||
     (SELECT COUNT(*) FROM exercise_step_translations est
        JOIN exercise_steps es ON es.id = est.exercise_step_id
        JOIN exercises e ON e.id = es.exercise_id
        WHERE e.kind='cc' AND est.locale='pl-PL' AND est.content_status='ready')::text;")"
echo "restore_drill.counts ${COUNTS}"
case "${COUNTS}" in
  6\|60\|60) ;;
  *)
    echo "restore_drill.fail reason=catalog_counts_mismatch got=${COUNTS}" >&2
    exit 1
    ;;
esac

echo "restore_drill.ok"
