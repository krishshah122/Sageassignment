from __future__ import annotations

import pytest

from app.config import ConfigError, load_settings


def test_load_settings_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/order_supervisor")
    monkeypatch.setenv("TEMPORAL_ADDRESS", "localhost:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "default")
    monkeypatch.setenv("TEMPORAL_TASK_QUEUE", "order-supervisor")

    settings = load_settings()

    assert settings.temporal_address == "localhost:7233"
    assert settings.temporal_namespace == "default"
    assert settings.temporal_task_queue == "order-supervisor"
    assert settings.default_wakeup_seconds == 30


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_load_settings_rejects_invalid_default_wakeup(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", "******localhost:5432/order_supervisor")
    monkeypatch.setenv("TEMPORAL_ADDRESS", "localhost:7233")
    monkeypatch.setenv("DEFAULT_WAKEUP_SECONDS", value)

    with pytest.raises(ConfigError, match="DEFAULT_WAKEUP_SECONDS must be a positive integer"):
        load_settings()


def test_load_settings_requires_temporal_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/order_supervisor")
    monkeypatch.delenv("TEMPORAL_ADDRESS", raising=False)

    with pytest.raises(ConfigError, match="TEMPORAL_ADDRESS is required"):
        load_settings()


def test_load_settings_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPORAL_ADDRESS", "localhost:7233")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ConfigError, match="DATABASE_URL is required"):
        load_settings()
