#!/usr/bin/env bash
# Generate a private .env for CI / local bootstrap (never commit the result).
set -euo pipefail

ROOT_PW="$(openssl rand -hex 16)"
APP_PW="$(openssl rand -hex 16)"
MIG_PW="$(openssl rand -hex 16)"
CSRF="$(openssl rand -hex 32)"

cat > .env <<EOF
POSTGRES_USER=trainer
POSTGRES_PASSWORD=${ROOT_PW}
POSTGRES_DB=trainer
TRAINER_APP_PASSWORD=${APP_PW}
TRAINER_MIGRATOR_PASSWORD=${MIG_PW}
DATABASE_URL=postgresql+asyncpg://trainer_app:${APP_PW}@db:5432/trainer
ALEMBIC_DATABASE_URL=postgresql+asyncpg://trainer:${ROOT_PW}@db:5432/trainer
APP_ENV=development
PUBLIC_ORIGIN=https://localhost
LOG_LEVEL=info
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=https://localhost/api/auth/google/callback
SESSION_COOKIE_NAME=__Host-trainer_session
CSRF_SECRET=${CSRF}
RATE_LIMIT_STORE=memory
EOF

echo "Wrote .env with generated local credentials (gitignored)."
