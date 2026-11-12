from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import DateTime, TypeDecorator, event
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import DATA_DIR, settings


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""
    pass


class UTCDateTime(TypeDecorator):
    """
    SQLAlchemy TypeDecorator ensuring datetimes are stored in UTC and always
    returned as timezone-aware UTC datetime objects.

    Handling rules:
    - Bind parameter (Python -> DB):
      * If aware, converted to UTC via .astimezone(timezone.utc).
      * If naive, explicitly assumed to represent UTC and tagged with timezone.utc.
      * Rejects non-datetime inputs with TypeError.
    - Result value (DB -> Python):
      * If naive (standard SQLite behavior), tagged with timezone.utc.
      * If aware, normalized to UTC via .astimezone(timezone.utc).
    """
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if not isinstance(value, datetime):
                raise TypeError(f"Expected datetime object, got {type(value).__name__}.")
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            else:
                value = value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return value


def ensure_db_directory_exists(db_url: str) -> None:
    """Ensure parent directory exists for SQLite database files."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if "sqlite" in db_url and ":memory:" not in db_url:
        for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
            if db_url.startswith(prefix):
                file_path = Path(db_url[len(prefix):])
                file_path.parent.mkdir(parents=True, exist_ok=True)
                break


# Ensure data directory exists before establishing connection
ensure_db_directory_exists(settings.DATABASE_URL)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
)


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Ensure SQLite foreign key constraints are strictly enforced for all connections."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides an asynchronous database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all database tables on application startup."""
    ensure_db_directory_exists(settings.DATABASE_URL)
    # Import models here so metadata includes all defined tables
    from app.models import Conversation, Message, Memory  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose the database engine on application shutdown."""
    await engine.dispose()

