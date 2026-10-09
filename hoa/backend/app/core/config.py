"""Core configuration — single source of truth for all settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Postgres ──
    DATABASE_URL: str = "postgresql+psycopg://hoa:changeme@db:5432/hoa"

    # ── Security ──
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480
    AUDIT_HMAC_KEY: str = "change-me"
    VAULT_KEY: str = ""  # Fernet key, generated if empty

    # ── LLM ──
    LLM_PROVIDER: Literal["mistral", "template"] = "template"
    MISTRAL_API_KEY: str = ""
    MISTRAL_BASE_URL: str = "https://api.mistral.ai/v1"
    MISTRAL_CHAT_MODEL: str = "mistral-large-latest"
    MISTRAL_FAST_MODEL: str = "mistral-small-latest"
    MISTRAL_EMBED_MODEL: str = "mistral-embed"
    EMBED_DIM: int = 1024

    # ── App ──
    CORS_ORIGINS: list[str] = Field(default=["http://localhost:5173"])
    LOG_LEVEL: str = "info"


@lru_cache
def get_settings() -> Settings:
    return Settings()
