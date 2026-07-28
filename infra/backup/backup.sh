#!/bin/sh
# Encrypted nightly pg_dump (FR-081a). Compose service `backup` only — no HTTP trigger.
# Requires BACKUP_ENCRYPTION_PASSPHRASE (openssl AES-256-CBC) or BACKUP_AGE_RECIPIENT (age).
# Streams dump → encrypt so plaintext never lands on the backup bind mount.
set -eu
set -o pipefail

BACKUP_DIR="${BACKUP_DIR:-/backup}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
PGHOST="${POSTGRES_HOST:-db}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER="${POSTGRES_USER:-trainer}"
PGDATABASE="${POSTGRES_DB:-trainer}"
export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD required}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
partial=""
final=""
started="$(date -u +%s)"

cleanup_partial() {
  if [ -n "${partial}" ] && [ -f "${partial}" ]; then
    rm -f "${partial}"
  fi
}

fail() {
  reason="$1"
  echo "backup.fail reason=${reason}" >&2
  cleanup_partial
  exit 1
}

trap cleanup_partial EXIT

mkdir -p "${BACKUP_DIR}"

echo "backup.start host=${PGHOST} db=${PGDATABASE} ts=${ts}"

dump_cmd() {
  pg_dump -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" \
    -Fc --no-owner --no-acl
}

if [ -n "${BACKUP_AGE_RECIPIENT:-}" ]; then
  if ! command -v age >/dev/null 2>&1; then
    fail "age_not_installed"
  fi
  final="${BACKUP_DIR}/trainer-${ts}.dump.age"
  partial="${final}.partial"
  if ! dump_cmd | age -r "${BACKUP_AGE_RECIPIENT}" -o "${partial}"; then
    fail "age_encrypt_failed"
  fi
elif [ -n "${BACKUP_ENCRYPTION_PASSPHRASE:-}" ]; then
  final="${BACKUP_DIR}/trainer-${ts}.dump.enc"
  partial="${final}.partial"
  # PBKDF2 + AES-256-CBC; passphrase via env (never argv). Stdin = dump stream.
  if ! dump_cmd | openssl enc -aes-256-cbc -pbkdf2 -salt \
    -pass env:BACKUP_ENCRYPTION_PASSPHRASE \
    -out "${partial}"; then
    fail "openssl_encrypt_failed"
  fi
else
  fail "encryption_not_configured"
fi

mv "${partial}" "${final}"
partial=""

enc_size="$(wc -c < "${final}" | tr -d ' ')"
elapsed=$(( $(date -u +%s) - started ))

# Retention: drop encrypted dumps older than RETENTION_DAYS
find "${BACKUP_DIR}" -maxdepth 1 -type f \( -name 'trainer-*.dump.enc' -o -name 'trainer-*.dump.age' \) \
  -mtime "+${RETENTION_DAYS}" -print -delete 2>/dev/null || true

# Leftover plaintext dumps from older script versions / crashed hosts
find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'trainer-*.dump' ! -name '*.enc' ! -name '*.age' \
  -print -delete 2>/dev/null || true

printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${BACKUP_DIR}/LAST_OK"
echo "backup.ok file=$(basename "${final}") enc_bytes=${enc_size} elapsed_s=${elapsed}"
echo "backup.heartbeat path=${BACKUP_DIR}/LAST_OK"
