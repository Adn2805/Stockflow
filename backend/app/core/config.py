from os import getenv
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def parse_origins(value: str | list[str]) -> list[str]:
    entries = value.split(",") if isinstance(value, str) else value
    origins = [origin.strip() for origin in entries if origin.strip()]
    for origin in origins:
        url = urlsplit(origin)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username is not None
                or url.path or url.query or url.fragment or "*" in origin):
            raise ValueError("CORS origins must be explicit HTTP(S) origins without paths")
    return origins


def configured_origins() -> list[str]:
    return parse_origins(getenv("CORS_ORIGINS", ""))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(hide_input_in_errors=True)

    cors_origins: Annotated[list[str], NoDecode] = []
    database_url: SecretStr
    write_token: SecretStr | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def validate_origins(cls, value):
        return parse_origins(value)

    @field_validator("database_url")
    @classmethod
    def require_postgresql(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("DATABASE_URL must be a valid SQLAlchemy URL") from None
        if url.drivername != "postgresql+psycopg":
            raise ValueError("DATABASE_URL must use postgresql+psycopg")
        return value

    @field_validator("write_token", mode="before")
    @classmethod
    def normalize_token(cls, value):
        return None if value == "" else value

    @field_validator("write_token")
    @classmethod
    def check_token_length(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("WRITE_TOKEN must be at least 32 characters")
        return value
