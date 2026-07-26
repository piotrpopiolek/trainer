from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    # Must be provided via environment / .env (no embedded credentials in defaults).
    database_url: str = ""
    alembic_database_url: str = ""
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


settings = Settings()
