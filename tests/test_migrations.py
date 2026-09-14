"""Database upgrades: every older schema reaches the current one in place, backed up first.

The fixtures are SQL dumps of databases written by the released code of v1.0.1 (schema 1) and
v1.1.1 (schema 2) themselves, so these tests upgrade what those releases really stored rather
than an imitation of it.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from online_annotator.app import create_app
from online_annotator.cli import main
from online_annotator.config import load_settings
from online_annotator.db import (
    MIGRATIONS,
    SCHEMA_VERSION,
    init_schema,
    make_engine,
    make_session_factory,
    schema_status,
)
from online_annotator.models import User
from online_annotator.services.auth import hash_password

from .conftest import HEADERS

FIXTURES = Path(__file__).parent / "fixtures"
OLD_RELEASES = [("db_v1.0.1_schema1.sql", 1), ("db_v1.1.1_schema2.sql", 2)]


def restore(path: Path, fixture: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as con:
        con.executescript((FIXTURES / fixture).read_text(encoding="utf-8"))
    return f"sqlite:///{path.as_posix()}"


def shape(url: str) -> dict[str, set[tuple]]:
    """Tables -> (column, type, not null) for comparing an upgraded database with a fresh one."""
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            tables = [r[0] for r in conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"))]
            return {t: {(r[1], r[2].upper(), r[3]) for r in conn.execute(text(f"PRAGMA table_info({t})"))}
                    for t in tables}
    finally:
        engine.dispose()


def query(path: Path, sql: str) -> list[tuple]:
    with closing(sqlite3.connect(path)) as con:
        return con.execute(sql).fetchall()


def test_migrations_are_numbered_without_gaps():
    assert [m.version for m in MIGRATIONS] == list(range(2, SCHEMA_VERSION + 1))


def test_a_fresh_database_is_created_at_the_current_version_without_a_backup(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'oa.sqlite3').as_posix()}")
    try:
        assert schema_status(engine).stored is None
        result = init_schema(engine)
        assert result.applied == [] and result.backup is None
        assert schema_status(engine).stored == SCHEMA_VERSION and not schema_status(engine).pending
    finally:
        engine.dispose()
    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize(("fixture", "stored"), OLD_RELEASES)
def test_an_old_release_database_is_backed_up_and_upgraded_in_place(tmp_path, fixture, stored):
    db_file = tmp_path / "old" / "online_annotator.sqlite3"
    url = restore(db_file, fixture)
    engine = make_engine(url)
    try:
        status = schema_status(engine)
        assert status.stored == stored
        assert [m.version for m in status.pending] == list(range(stored + 1, SCHEMA_VERSION + 1))

        result = init_schema(engine)
        assert result.applied == list(range(stored + 1, SCHEMA_VERSION + 1))

        # Former roles: administrators stay administrators; former reviewers start in Review mode.
        with make_session_factory(engine)() as db:
            users = {u.email: (u.is_admin, u.active_mode) for u in db.query(User)}
            assert users == {"lead@lab.test": (True, "annotate"), "rita@lab.test": (False, "review"),
                             "anil@lab.test": (False, "annotate")}
            # A dead NOT NULL "role" column would break this insert.
            db.add(User(email="new@lab.test", full_name="New", password_hash=hash_password("new-pass-1")))
            db.commit()
            assert db.query(User).filter(User.email == "new@lab.test").one().active_mode == "annotate"

        # A second start has nothing to do and takes no second backup.
        assert init_schema(engine).applied == []
    finally:
        engine.dispose()

    # The ground truth itself is untouched.
    assert query(db_file, "SELECT status, created_by, reviewed_by, mask_sha256 FROM versions") == [
        ("approved", "anil@lab.test", "rita@lab.test", "1" * 64)]
    assert query(db_file, "SELECT status, working_revision FROM images") == [("approved", 1)]

    # The upgraded database has exactly the shape a fresh one has.
    fresh = tmp_path / "fresh" / "online_annotator.sqlite3"
    fresh.parent.mkdir()
    fresh_engine = make_engine(f"sqlite:///{fresh.as_posix()}")
    init_schema(fresh_engine)
    fresh_engine.dispose()
    assert shape(url) == shape(f"sqlite:///{fresh.as_posix()}")

    # The backup is the database as it was before anything changed.
    backups = list((db_file.parent / "backups").glob("*.sqlite3"))
    assert len(backups) == 1 and f"schema{stored}" in backups[0].name
    assert query(backups[0], "PRAGMA user_version") == [(stored,)]
    assert "role" in {row[1] for row in query(backups[0], "PRAGMA table_info(users)")}


def test_an_interrupted_upgrade_can_simply_be_started_again(tmp_path):
    db_file = tmp_path / "online_annotator.sqlite3"
    url = restore(db_file, "db_v1.1.1_schema2.sql")
    # Half of step 3 ran before the process died: one column added, version not yet stamped.
    with closing(sqlite3.connect(db_file)) as con:
        con.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0")
        con.commit()
    engine = make_engine(url)
    try:
        assert init_schema(engine).applied == [3]
        with make_session_factory(engine)() as db:
            assert db.query(User).filter(User.email == "lead@lab.test").one().is_admin is True
    finally:
        engine.dispose()


def test_a_newer_database_is_refused(tmp_path):
    db_file = tmp_path / "online_annotator.sqlite3"
    engine = make_engine(f"sqlite:///{db_file.as_posix()}")
    try:
        init_schema(engine)
        with engine.begin() as conn:
            conn.execute(text(f"PRAGMA user_version={SCHEMA_VERSION + 1}"))
        assert schema_status(engine).newer_than_release
        with pytest.raises(RuntimeError, match="newer than this release"):
            init_schema(engine)
    finally:
        engine.dispose()


def test_the_server_starts_on_an_old_database_and_old_accounts_keep_working(tmp_path):
    data = tmp_path / "data"
    db_file = data / "online_annotator.sqlite3"
    restore(db_file, "db_v1.1.1_schema2.sql")
    with closing(sqlite3.connect(db_file)) as con:
        con.execute("UPDATE users SET password_hash = ?", (hash_password("legacy-pass-1"),))
        con.commit()
    application = create_app(load_settings(environ={}, data_dir=data, secret_key="k"))
    with TestClient(application, headers=HEADERS) as client:
        r = client.post("/api/v1/auth/login", json={"email": "rita@lab.test", "password": "legacy-pass-1"})
        assert r.status_code == 200, r.text
        assert r.json()["user"] | {"is_admin": False, "active_mode": "review"} == r.json()["user"]
        assert client.get("/api/v1/projects").json()["projects"][0]["name"] == "Legacy hydrides"
    application.state.engine.dispose()


def test_cli_reports_and_applies_a_pending_upgrade(tmp_path, capsys):
    data = tmp_path / "cli"
    assert main(["db-status", "--data-dir", str(data)]) == 0
    assert "No database yet" in capsys.readouterr().out

    restore(data / "online_annotator.sqlite3", "db_v1.1.1_schema2.sql")
    assert main(["db-status", "--data-dir", str(data)]) == 1
    out = capsys.readouterr().out
    assert "Stored schema: 2" in out and "working modes" in out

    assert main(["migrate", "--data-dir", str(data)]) == 0
    out = capsys.readouterr().out
    assert f"Upgraded to schema {SCHEMA_VERSION}" in out and "backups" in out

    assert main(["db-status", "--data-dir", str(data)]) == 0
    assert "Up to date" in capsys.readouterr().out
