from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.config import load_settings
from app.db.models import Base


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(load_settings().database_url, pool_pre_ping=True)


def init_db() -> None:
    Base.metadata.create_all(get_engine())


def get_db() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
