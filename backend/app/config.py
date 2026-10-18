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


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
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
    )
