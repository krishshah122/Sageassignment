from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(ValueError):
    """Raised when required process configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    database_url: str
    temporal_address: str
    temporal_namespace: str
    temporal_task_queue: str
    default_wakeup_seconds: int
    groq_api_key: str
    groq_model: str


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value


def _positive_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be a positive integer")
    return value


def load_settings() -> Settings:
    """Load settings from the process environment. Fails fast on missing values."""
    return Settings(
        database_url=_required("DATABASE_URL"),
        temporal_address=_required("TEMPORAL_ADDRESS"),
        temporal_namespace=os.environ.get("TEMPORAL_NAMESPACE", "default").strip()
        or "default",
        temporal_task_queue=os.environ.get("TEMPORAL_TASK_QUEUE", "order-supervisor").strip()
        or "order-supervisor",
        default_wakeup_seconds=_positive_int("DEFAULT_WAKEUP_SECONDS", 30),
        groq_api_key=os.environ.get("GROQ_API_KEY", "").strip(),
        groq_model=os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b").strip()
        or "openai/gpt-oss-20b",
    )
