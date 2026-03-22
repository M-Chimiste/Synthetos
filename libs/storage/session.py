from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from libs.core.config import AppConfig
from libs.storage.base import Base


@lru_cache(maxsize=4)
def get_engine(db_url: str) -> Engine:
    connect_args: dict[str, object] = {}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(db_url, future=True, connect_args=connect_args)


_session_factories: dict[str, sessionmaker[Session]] = {}


def get_session_factory(config: AppConfig) -> sessionmaker[Session]:
    if config.db_url not in _session_factories:
        engine = get_engine(config.db_url)
        _session_factories[config.db_url] = sessionmaker(
            bind=engine, autoflush=False, autocommit=False, future=True,
        )
    return _session_factories[config.db_url]


def initialize_database(config: AppConfig) -> None:
    engine = get_engine(config.db_url)
    Base.metadata.create_all(engine)

