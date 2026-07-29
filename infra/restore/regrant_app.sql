-- Post-restore grants for trainer_app (backup uses pg_dump --no-acl / --no-owner).
-- Run as superuser after pg_restore. Roles themselves come from image init + env.
GRANT USAGE ON SCHEMA public TO trainer_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO trainer_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO trainer_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO trainer_app;
