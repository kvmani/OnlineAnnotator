"""Database engine, session management and schema migrations (SQLite in WAL mode by default).

Schema evolution
----------------
The stored schema version is SQLite's ``PRAGMA user_version``. ``SCHEMA_VERSION`` is the
version this release writes, and ``MIGRATIONS`` holds one numbered step for every version after
the first. ``init_schema`` runs at every start:

* **fresh database** -- the tables are created from the models and stamped ``SCHEMA_VERSION``;
* **older database** -- a consistent copy is saved under ``<data>/backups/`` first, then every
  pending step runs in order and the version is stamped after each one;
* **newer database** -- refused, so an accidental downgrade fails loudly instead of writing
  data an older release does not understand.

Rules for a new step (see AGENTS.md, "Contracts"):

1. append ``Migration(SCHEMA_VERSION + 1, ...)`` and bump ``SCHEMA_VERSION``; never edit a
   released step;
2. make it idempotent (check before adding or dropping), so an interrupted upgrade can simply
   be started again;
3. change the models in the same commit, and extend ``tests/test_migrations.py`` so the upgraded
   database is proven identical in shape to a fresh one.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request
from sqlalchemy import Connection, Engine, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 4


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


# ------------------------------------------------------------------------------ migrations
@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    apply: Callable[[Connection], None]


def _columns(conn: Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}


def _add_columns(conn: Connection, table: str, columns: list[tuple[str, str]]) -> None:
    existing = _columns(conn, table)
    for column, ddl in columns:
        if column not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def _v2_mask_provenance(conn: Connection) -> None:
    """Release 1.1.0: where each label map came from (imported mask or drawn here)."""
    provenance = [
        ("mask_source", "VARCHAR(20) NOT NULL DEFAULT 'manual'"),
        ("mask_source_tool", "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("mask_source_remarks", "TEXT NOT NULL DEFAULT ''"),
        ("mask_source_file", "VARCHAR(255) NOT NULL DEFAULT ''"),
    ]
    _add_columns(conn, "images", provenance + [("mask_imported_by", "VARCHAR(255)"),
                                               ("mask_imported_at", "DATETIME")])
    _add_columns(conn, "versions", provenance)


def _v3_working_modes(conn: Connection) -> None:
    """Release 2.0.0: every user annotates and reviews; admin is a privilege, not a role.

    ``users.role`` (annotator | reviewer | admin) becomes ``is_admin`` plus ``active_mode``.
    Former administrators stay administrators, former reviewers start in Review mode, and
    the old column is dropped so no dead NOT NULL column breaks later inserts.
    """
    if "role" in _columns(conn, "users") and sqlite3.sqlite_version_info < (3, 35, 0):
        raise RuntimeError(
            f"Upgrading the database needs SQLite 3.35 or newer; this Python uses {sqlite3.sqlite_version}. "
            "Install a newer Python or SQLite, or keep running the previous release."
        )
    _add_columns(conn, "users", [("is_admin", "BOOLEAN NOT NULL DEFAULT 0"),
                                 ("active_mode", "VARCHAR(10) NOT NULL DEFAULT 'annotate'")])
    if "role" in _columns(conn, "users"):
        conn.execute(text("UPDATE users SET is_admin = CASE WHEN role = 'admin' THEN 1 ELSE 0 END"))
        conn.execute(text("UPDATE users SET active_mode = 'review' WHERE role = 'reviewer'"))
        conn.execute(text("ALTER TABLE users DROP COLUMN role"))


def _v4_mask_import_details(conn: Connection) -> None:
    """Release 2.1.0: how an imported mask file was interpreted (encoding, mapping, threshold)."""
    for table in ("images", "versions"):
        _add_columns(conn, table, [("mask_import_details", "TEXT NOT NULL DEFAULT ''")])


MIGRATIONS: tuple[Migration, ...] = (
    Migration(2, "mask provenance on images and versions", _v2_mask_provenance),
    Migration(3, "working modes: users.role -> is_admin + active_mode", _v3_working_modes),
    Migration(4, "mask import interpretation on images and versions", _v4_mask_import_details),
)


@dataclass
class SchemaStatus:
    """What an operator needs to know before starting a release on a data directory."""

    stored: int | None  # None: no database yet
    supported: int = SCHEMA_VERSION
    pending: list[Migration] = field(default_factory=list)

    @property
    def newer_than_release(self) -> bool:
        return self.stored is not None and self.stored > self.supported


@dataclass
class MigrationResult:
    applied: list[int] = field(default_factory=list)
    backup: Path | None = None


def _sqlite_file(engine: Engine) -> Path | None:
    database = engine.url.database
    if engine.dialect.name != "sqlite" or not database or database == ":memory:":
        return None
    return Path(database)


def _stored_version(conn: Connection) -> int | None:
    if "users" not in inspect(conn).get_table_names():
        return None
    # 1.0.x stamped version 1; a database that somehow carries 0 predates nothing newer.
    return max(conn.execute(text("PRAGMA user_version")).scalar() or 0, 1)


def schema_status(engine: Engine) -> SchemaStatus:
    """Inspect without changing anything (and without creating a missing database file)."""
    path = _sqlite_file(engine)
    if path is not None and not path.exists():
        return SchemaStatus(stored=None)
    with engine.connect() as conn:
        stored = _stored_version(conn)
    pending = [m for m in MIGRATIONS if stored is not None and m.version > stored]
    return SchemaStatus(stored=stored, pending=pending)


def backup_database(engine: Engine, from_version: int) -> Path | None:
    """Consistent copy of the SQLite file (safe while the WAL is in use) before an upgrade."""
    source = _sqlite_file(engine)
    if source is None or not source.exists():
        return None
    folder = source.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = folder / f"{source.stem}.schema{from_version}.{stamp}.sqlite3"
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
    return target


def init_schema(engine: Engine, *, backup: bool = True) -> MigrationResult:
    """Create or upgrade the schema. Refuses to run on a schema newer than this release."""
    from . import models  # noqa: F401  (registers tables)

    result = MigrationResult()
    if engine.dialect.name != "sqlite":
        # Numbered migrations are written for SQLite, the supported database.
        Base.metadata.create_all(engine)
        return result

    status = schema_status(engine)
    if status.newer_than_release:
        raise RuntimeError(
            f"Database schema {status.stored} is newer than this release supports ({SCHEMA_VERSION}). "
            "Roll back to the matching release or upgrade the application."
        )
    if status.stored is None:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(text(f"PRAGMA user_version={SCHEMA_VERSION}"))
        return result

    if status.pending:
        if backup:
            result.backup = backup_database(engine, status.stored)
            logger.warning("Database schema %s is older than %s; backup saved to %s",
                           status.stored, SCHEMA_VERSION, result.backup)
        for step in status.pending:
            with engine.begin() as conn:
                step.apply(conn)
                conn.execute(text(f"PRAGMA user_version={step.version}"))
            result.applied.append(step.version)
            logger.warning("Database schema upgraded to %s: %s", step.version, step.description)
    Base.metadata.create_all(engine)  # tables that a release adds without touching existing data
    return result


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency yielding a session bound to this application's engine."""
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()
