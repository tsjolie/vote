"""Application configuration from environment variables."""

from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    def __init__(self) -> None:
        # CloudNativePG-generated secret exposes a libpq/SQLAlchemy-style URI. We
        # accept either DATABASE_URL directly or the CNPG components.
        self.database_url = self._build_database_url()
        self.session_cookie_name = os.getenv("SESSION_COOKIE_NAME", "vote_session")
        self.session_ttl_days = int(os.getenv("SESSION_TTL_DAYS", "30"))
        # Secure cookie flag; disable only for local http development.
        self.cookie_secure = os.getenv("COOKIE_SECURE", "true").lower() != "false"
        # Static assets built by the frontend (stage 1 of the Dockerfile).
        self.static_dir = os.getenv("STATIC_DIR", "/app/static")
        self.environment = os.getenv("ENVIRONMENT", "production")

    @staticmethod
    def _build_database_url() -> str:
        url = os.getenv("DATABASE_URL")
        if url:
            # Normalize to the asyncpg driver.
            if url.startswith("postg://"):
                url = url.replace("postg://", "postgresql://", 1)
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        name = os.getenv("DB_NAME", "vote")
        user = os.getenv("DB_USER", "vote")
        password = os.getenv("DB_PASSWORD", "vote")
        return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"

    @property
    def sync_database_url(self) -> str:
        """Alembic runs migrations with a synchronous driver."""
        return self.database_url.replace("+asyncpg", "+psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()
