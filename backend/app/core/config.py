from functools import cached_property
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


def _asyncpg_dsn(
    *,
    user: str,
    password: str,
    host: str,
    port: int,
    database: str,
) -> str:
    """Build a DSN without embedding a credentials-URI literal in source."""
    userinfo = quote(user, safe="") + ":" + quote(password, safe="")
    return "postgresql+asyncpg://" + userinfo + "@" + host + ":" + str(port) + "/" + database


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    # Optional full DSN overrides (prefer discrete password env vars for local/CI).
    database_url: str = ""
    alembic_database_url: str = ""
    postgres_user: str = "trainer"
    postgres_password: str = ""
    postgres_db: str = "trainer"
    postgres_host: str = "db"
    postgres_port: int = 5432
    public_origin: str = "https://localhost"
    log_level: str = "info"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "https://localhost/api/auth/google/callback"
    session_cookie_name: str = "__Host-trainer_session"
    csrf_secret: str = ""
    rate_limit_store: str = "memory"
    trainer_app_password: str = ""
    trainer_migrator_password: str = ""

    @cached_property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        if not self.trainer_app_password:
            raise RuntimeError(
                "Set DATABASE_URL or TRAINER_APP_PASSWORD (see .env.example)"
            )
        return _asyncpg_dsn(
            user="trainer_app",
            password=self.trainer_app_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @cached_property
    def resolved_alembic_database_url(self) -> str:
        if self.alembic_database_url:
            return self.alembic_database_url
        if not self.postgres_password:
            raise RuntimeError(
                "Set ALEMBIC_DATABASE_URL or POSTGRES_PASSWORD (see .env.example)"
            )
        return _asyncpg_dsn(
            user=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


settings = Settings()
