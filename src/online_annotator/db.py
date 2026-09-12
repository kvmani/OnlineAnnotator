"""Database engine and session management (SQLite in WAL mode by default)."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2


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


# Additive column migrations, keyed by the schema version that introduced them.
# ``create_all`` only creates missing *tables*, so a database written by an older
# release needs its new columns added explicitly. Every entry must be additive with a
# default, so the previous release can still read the database (AGENTS.md, contracts).
ADDED_COLUMNS: dict[int, list[tuple[str, str, str]]] = {
    2: [
        ("images", "mask_source", "VARCHAR(20) NOT NULL DEFAULT 'manual'"),
        ("images", "mask_source_tool", "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("images", "mask_source_remarks", "TEXT NOT NULL DEFAULT ''"),
        ("images", "mask_source_file", "VARCHAR(255) NOT NULL DEFAULT ''"),
        ("images", "mask_imported_by", "VARCHAR(255)"),
        ("images", "mask_imported_at", "DATETIME"),
        ("versions", "mask_source", "VARCHAR(20) NOT NULL DEFAULT 'manual'"),
        ("versions", "mask_source_tool", "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("versions", "mask_source_remarks", "TEXT NOT NULL DEFAULT ''"),
        ("versions", "mask_source_file", "VARCHAR(255) NOT NULL DEFAULT ''"),
    ],
}


def _add_missing_columns(conn, from_version: int) -> list[str]:
    """Apply every additive column above ``from_version``; returns what was added."""
    applied: list[str] = []
    for version in sorted(v for v in ADDED_COLUMNS if v > from_version):
        for table, column, ddl in ADDED_COLUMNS[version]:
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if not existing or column in existing:
                continue  # table absent (fresh database) or already migrated
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            applied.append(f"{table}.{column}")
    return applied


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
                added = _add_missing_columns(conn, current)
                if added:
                    logger.info("Schema %s -> %s: added %s", current, SCHEMA_VERSION, ", ".join(added))
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
