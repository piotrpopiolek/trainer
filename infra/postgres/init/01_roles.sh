#!/bin/sh
# Bootstrap DB roles from env (no passwords in git).
# Requires: TRAINER_APP_PASSWORD, TRAINER_MIGRATOR_PASSWORD
set -eu

: "${TRAINER_APP_PASSWORD:?TRAINER_APP_PASSWORD must be set}"
: "${TRAINER_MIGRATOR_PASSWORD:?TRAINER_MIGRATOR_PASSWORD must be set}"
: "${POSTGRES_DB:=trainer}"

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -v app_pw="$TRAINER_APP_PASSWORD" \
  -v mig_pw="$TRAINER_MIGRATOR_PASSWORD" \
  -v dbname="$POSTGRES_DB" <<'EOSQL'
CREATE EXTENSION IF NOT EXISTS citext;

DO $$
BEGIN
  CREATE ROLE trainer_migrator NOLOGIN;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

ALTER ROLE trainer_migrator WITH LOGIN BYPASSRLS PASSWORD :'mig_pw';

DO $$
BEGIN
  CREATE ROLE trainer_app NOLOGIN;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

ALTER ROLE trainer_app WITH LOGIN PASSWORD :'app_pw';

GRANT CONNECT ON DATABASE :"dbname" TO trainer_migrator;
GRANT CONNECT ON DATABASE :"dbname" TO trainer_app;
GRANT USAGE, CREATE ON SCHEMA public TO trainer_migrator;
GRANT USAGE ON SCHEMA public TO trainer_app;
EOSQL
