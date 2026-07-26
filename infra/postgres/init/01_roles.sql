-- Bootstrap roles for Trainer F1 (runs only on fresh Postgres volume).
-- Passwords here match .env.example local defaults; override via re-create + secrets in prod.

CREATE EXTENSION IF NOT EXISTS citext;

DO $$
BEGIN
  CREATE ROLE trainer_migrator LOGIN PASSWORD 'trainer_migrator';
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

ALTER ROLE trainer_migrator WITH BYPASSRLS;

DO $$
BEGIN
  CREATE ROLE trainer_app LOGIN PASSWORD 'trainer_app';
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

GRANT CONNECT ON DATABASE trainer TO trainer_migrator;
GRANT CONNECT ON DATABASE trainer TO trainer_app;
GRANT USAGE, CREATE ON SCHEMA public TO trainer_migrator;
GRANT USAGE ON SCHEMA public TO trainer_app;
