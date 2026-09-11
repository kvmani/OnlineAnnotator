"""Database engine and session management (SQLite in WAL mode by default)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

SCHEMA_VERSION = 1


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


def make_engine(url: str) -> Engine:
    """Create an engine; SQLite gets WAL, foreign keys and a busy timeout for concurrent users."""
    is_sqlite = url.startswith("sqlite")
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 30} if is_sqlite else {},
        pool_pre_ping=True,
    )
    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


def init_schema(engine: Engine) -> None:
    """Create tables and stamp the schema version. Refuses to run on a newer schema."""
    from . import models  # noqa: F401  (registers tables)

    Base.metadata.create_all(engine)
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            current = conn.execute(text("PRAGMA user_version")).scalar() or 0
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema {current} is newer than this release supports ({SCHEMA_VERSION}). "
                    "Roll back to the matching release or upgrade the application."
                )
            if current < SCHEMA_VERSION:
                conn.execute(text(f"PRAGMA user_version={SCHEMA_VERSION}"))


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency yielding a session bound to this application's engine."""
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()
