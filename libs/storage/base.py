"""SQLAlchemy base, engine, and session factories."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import MetaData, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from libs.core.config import get_settings

# Naming convention for constraints (makes Alembic autogenerate deterministic)
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def get_sync_engine(url: str | None = None):
    """Create a synchronous engine (used by Alembic and CLI tools)."""
    db_url = url or get_settings().sync_db_url
    return create_engine(db_url, echo=False)


def get_async_engine(url: str | None = None):
    """Create an async engine for the application runtime."""
    db_url = url or get_settings().db_url
    # Convert sync URL to async if needed
    async_url = db_url.replace("postgresql+psycopg://", "postgresql+psycopg://")
    return create_async_engine(async_url, echo=False)


def get_sync_session_factory(url: str | None = None) -> sessionmaker[Session]:
    """Create a synchronous session factory."""
    engine = get_sync_engine(url)
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_async_session_factory(url: str | None = None) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory."""
    engine = get_async_engine(url)
    return async_sessionmaker(bind=engine, expire_on_commit=False)


@asynccontextmanager
async def get_async_session(url: str | None = None) -> AsyncGenerator[AsyncSession]:
    """Convenience context manager for a single async session."""
    factory = get_async_session_factory(url)
    async with factory() as session:
        yield session
