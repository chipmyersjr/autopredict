"""Shared local environment configuration, independent of working directory."""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    postgres_db: str = Field(default="autopredict", min_length=1)
    postgres_user: str = Field(default="autopredict", min_length=1)
    postgres_password: SecretStr = SecretStr("autopredict_local")
    postgres_host: str = Field(default="127.0.0.1", min_length=1)
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    db_connect_timeout: int = Field(default=3, ge=2, le=10)

    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, origins: list[str]) -> list[str]:
        for origin in origins:
            url = urlsplit(origin)
            if url.scheme not in {"http", "https"} or not url.hostname or url.path or url.query or url.fragment or url.username or url.password or "*" in origin:
                raise ValueError("CORS origins must be explicit HTTP(S) origins without paths or credentials")
        return origins

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )
