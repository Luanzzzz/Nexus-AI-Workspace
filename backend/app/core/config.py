from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]

"""
configuações gerais da aplicação
Attributes:
    app_name: The name of the application.
    environment: The environment of the application.
    debug: Whether the application is in debug mode.
    postgres_user: The username for the PostgreSQL database.
    postgres_password: The password for the PostgreSQL database.
    postgres_db: The database name for the PostgreSQL database.
"""


class Settings(BaseSettings):
    app_name: str = "Nexus AI Workspace API"
    environment: str = "development"
    debug: bool = False
    postgres_user: str | None = None
    postgres_password: str | None = None
    postgres_db: str | None = None
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5433

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
