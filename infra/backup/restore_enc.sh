#!/bin/sh
# Decrypt encrypted dump and pg_restore into Compose db (FR-081a).
# Invoked from restore_drill.sh via: docker compose run --entrypoint sh backup /scripts/restore_enc.sh
set -eu
set -o pipefail

if [ -z "${BACKUP_ENCRYPTION_PASSPHRASE:-}" ]; then
  echo "restore_enc.fail reason=backup_passphrase_missing" >&2
  exit 1
fi

if [ -z "${ENC_BASENAME:-}" ]; then
  echo "restore_enc.fail reason=enc_basename_missing" >&2
  exit 1
fi

ENC_PATH="/backup/${ENC_BASENAME}"
if [ ! -f "${ENC_PATH}" ]; then
  echo "restore_enc.fail reason=artifact_not_found path=${ENC_PATH}" >&2
  exit 1
fi

echo "restore_enc.start file=${ENC_BASENAME}"

openssl enc -d -aes-256-cbc -pbkdf2 -salt \
  -pass env:BACKUP_ENCRYPTION_PASSPHRASE \
  -in "${ENC_PATH}" -out /tmp/trainer.dump

export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD required}"
pg_restore -h "${POSTGRES_HOST:-db}" -p "${POSTGRES_PORT:-5432}" \
  -U "${POSTGRES_USER:-trainer}" -d "${POSTGRES_DB:-trainer}" \
  --clean --if-exists /tmp/trainer.dump

rm -f /tmp/trainer.dump
echo "restore_enc.ok"
