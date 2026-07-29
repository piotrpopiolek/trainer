#!/bin/sh
# F1.prod restore drill (FR-081a): seed → encrypted backup → wipe → restore → head + counts.
# Compose / CI only — no HTTP triggers.
set -eu
set -o pipefail

ROOT="$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "restore_drill.fail reason=missing_env" >&2
  exit 1
fi

PASS="${BACKUP_ENCRYPTION_PASSPHRASE:-restore-drill-ci-passphrase}"
export BACKUP_ENCRYPTION_PASSPHRASE="$PASS"

# Ensure passphrase present in compose env for backup service
if ! grep -q '^BACKUP_ENCRYPTION_PASSPHRASE=' .env 2>/dev/null; then
  printf '\nBACKUP_ENCRYPTION_PASSPHRASE=%s\n' "$PASS" >> .env
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
# Remove prior drill artifacts so we pick the fresh file
rm -f infra/backup/out/trainer-*.dump.enc infra/backup/out/trainer-*.dump.age 2>/dev/null || true

docker compose --profile ops build backup
docker compose --profile ops run --rm \
  -e BACKUP_ENCRYPTION_PASSPHRASE="$PASS" \
  backup

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
  -e BACKUP_ENCRYPTION_PASSPHRASE="$PASS" \
  -e ENC_BASENAME="$ENC_BASENAME" \
  --entrypoint /bin/sh \
  backup \
  -c '
    set -eu
    set -o pipefail
    openssl enc -d -aes-256-cbc -pbkdf2 -salt \
      -pass env:BACKUP_ENCRYPTION_PASSPHRASE \
      -in "/backup/${ENC_BASENAME}" -out /tmp/trainer.dump
    export PGPASSWORD="${POSTGRES_PASSWORD}"
    pg_restore -h db -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-trainer}" \
      -d "${POSTGRES_DB:-trainer}" --clean --if-exists /tmp/trainer.dump
  '

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
