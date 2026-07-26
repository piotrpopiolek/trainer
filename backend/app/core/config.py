from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://trainer_app:trainer_app@db:5432/trainer"
    alembic_database_url: str = "postgresql+asyncpg://trainer:trainer@db:5432/trainer"
    public_origin: str = "https://localhost"
    log_level: str = "info"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "https://localhost/api/auth/google/callback"
    session_cookie_name: str = "__Host-trainer_session"
    csrf_secret: str = ""
    rate_limit_store: str = "memory"
    trainer_app_password: str = "trainer_app"
    trainer_migrator_password: str = "trainer_migrator"


settings = Settings()
