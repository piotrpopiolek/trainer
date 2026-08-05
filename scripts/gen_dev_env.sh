#!/usr/bin/env bash
# Generate a private .env for CI / local bootstrap (never commit the result).
# Writes discrete secrets only — the app builds DSNs from them (no credentials-URI in git).
set -euo pipefail

ROOT_PW="$(openssl rand -hex 16)"
APP_PW="$(openssl rand -hex 16)"
MIG_PW="$(openssl rand -hex 16)"
CSRF="$(openssl rand -hex 32)"

cat > .env <<EOF
POSTGRES_USER=trainer
POSTGRES_PASSWORD=${ROOT_PW}
POSTGRES_DB=trainer
POSTGRES_HOST=db
POSTGRES_PORT=5432
TRAINER_APP_PASSWORD=${APP_PW}
TRAINER_MIGRATOR_PASSWORD=${MIG_PW}
APP_ENV=development
PUBLIC_ORIGIN=https://localhost
LOG_LEVEL=info
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=https://localhost/api/auth/google/callback
SESSION_COOKIE_NAME=__Host-trainer_session
CSRF_SECRET=${CSRF}
RATE_LIMIT_STORE=memory
ENABLE_E2E_LOGIN=1
BACKUP_ENCRYPTION_PASSPHRASE=$(openssl rand -hex 24)
BACKUP_RETENTION_DAYS=30
EOF

echo "Wrote .env with generated local credentials (gitignored)."
