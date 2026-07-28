#!/bin/sh
# Encrypted nightly pg_dump (FR-081a). Compose service `backup` only — no HTTP trigger.
# Requires BACKUP_ENCRYPTION_PASSPHRASE (openssl AES-256-CBC) or BACKUP_AGE_RECIPIENT (age).
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backup}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
PGHOST="${POSTGRES_HOST:-db}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER="${POSTGRES_USER:-trainer}"
PGDATABASE="${POSTGRES_DB:-trainer}"
export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD required}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
raw="${BACKUP_DIR}/trainer-${ts}.dump"
final=""
started="$(date -u +%s)"

fail() {
  reason="$1"
  echo "backup.fail reason=${reason}" >&2
  rm -f "${raw}" "${raw}.tmp" 2>/dev/null || true
  exit 1
}

mkdir -p "${BACKUP_DIR}"

echo "backup.start host=${PGHOST} db=${PGDATABASE} ts=${ts}"

if ! pg_dump -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" \
  -Fc --no-owner --no-acl -f "${raw}"; then
  fail "pg_dump_failed"
fi

size="$(wc -c < "${raw}" | tr -d ' ')"

if [ -n "${BACKUP_AGE_RECIPIENT:-}" ]; then
  if ! command -v age >/dev/null 2>&1; then
    fail "age_not_installed"
  fi
  final="${raw}.age"
  if ! age -r "${BACKUP_AGE_RECIPIENT}" -o "${final}" "${raw}"; then
    fail "age_encrypt_failed"
  fi
  rm -f "${raw}"
elif [ -n "${BACKUP_ENCRYPTION_PASSPHRASE:-}" ]; then
  final="${raw}.enc"
  # PBKDF2 + AES-256-CBC; passphrase via env (never argv).
  if ! openssl enc -aes-256-cbc -pbkdf2 -salt \
    -pass env:BACKUP_ENCRYPTION_PASSPHRASE \
    -in "${raw}" -out "${final}"; then
    fail "openssl_encrypt_failed"
  fi
  rm -f "${raw}"
else
  fail "encryption_not_configured"
fi

enc_size="$(wc -c < "${final}" | tr -d ' ')"
elapsed=$(( $(date -u +%s) - started ))

# Retention: drop encrypted dumps older than RETENTION_DAYS
find "${BACKUP_DIR}" -maxdepth 1 -type f \( -name 'trainer-*.dump.enc' -o -name 'trainer-*.dump.age' \) \
  -mtime "+${RETENTION_DAYS}" -print -delete 2>/dev/null || true

printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${BACKUP_DIR}/LAST_OK"
echo "backup.ok file=$(basename "${final}") raw_bytes=${size} enc_bytes=${enc_size} elapsed_s=${elapsed}"
echo "backup.heartbeat path=${BACKUP_DIR}/LAST_OK"
