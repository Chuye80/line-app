"""Runtime configuration.

Everything that differs between a laptop and a deployed environment is read
here so that no host, origin or feature switch is hard-coded in application
code.
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv


load_dotenv()


def _required(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"{name} must be set in the environment or .env file")

    return value


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)

    if value is None or not value.strip():
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _csv(name: str, default: tuple[str, ...]) -> list[str]:
    value = os.getenv(name)

    if value is None or not value.strip():
        return list(default)

    return [item.strip() for item in value.split(",") if item.strip()]


class Settings:
    def __init__(self) -> None:
        self.database_url = _required("DATABASE_URL")
        self.supabase_url = _required("SUPABASE_URL").rstrip("/")
        self.supabase_publishable_key = _required("SUPABASE_PUBLISHABLE_KEY")

        # When set, access tokens are verified locally with HMAC instead of
        # costing a round-trip to the Auth service on every request. Only
        # applies to HS256 tokens; anything else still goes to Supabase.
        self.supabase_jwt_secret = os.getenv("SUPABASE_JWT_SECRET") or None

        self.cors_origins = _csv(
            "CORS_ORIGINS",
            ("http://localhost:5173", "http://127.0.0.1:5173"),
        )

        # The /dev endpoints wipe registrations, delete every virtual member and
        # rewrite the game schedule. They must never be reachable in a
        # deployed environment, so they are off unless explicitly switched on.
        self.enable_dev_endpoints = _flag("ENABLE_DEV_ENDPOINTS", default=False)

        # How long a successfully verified access token may be reused without
        # asking Supabase again. Never extends past the token's own expiry.
        self.auth_cache_seconds = _int("AUTH_CACHE_SECONDS", 60)

        self.db_pool_size = _int("DB_POOL_SIZE", 5)
        self.db_max_overflow = _int("DB_MAX_OVERFLOW", 10)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
