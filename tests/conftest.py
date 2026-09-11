from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set test environment config
temp_dir = tempfile.mkdtemp(prefix="annotator_test_")
os.environ["ONLINE_ANNOTATOR_CONFIG"] = str(Path(temp_dir) / "test_config.yml")

from backend.app.config import AppConfig, get_config
from backend.app.db import Base, get_db
from backend.app.main import create_app
from backend.app.services.auth_service import create_session_token, get_password_hash
from backend.app.services.seed_data import seed_database
from backend.app.models.user import Role, User

# Create test sqlite engine
test_db_file = Path(temp_dir) / "test.sqlite3"
test_engine = create_engine(
    f"sqlite:///{test_db_file}",
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    # Update config storage paths
    cfg = get_config()
    cfg.storage.data_dir = str(Path(temp_dir) / "data")
    cfg.storage.images_dir = str(Path(temp_dir) / "data" / "images")
    cfg.storage.masks_dir = str(Path(temp_dir) / "data" / "masks")
    cfg.storage.exports_dir = str(Path(temp_dir) / "data" / "exports")
    cfg.storage.ledger_file = str(Path(temp_dir) / "data" / "ledger.json")
    cfg.database.url = f"sqlite:///{test_db_file}"

    for p in [cfg.storage.data_dir, cfg.storage.images_dir, cfg.storage.masks_dir, cfg.storage.exports_dir]:
        Path(p).mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(bind=test_engine)
    with TestingSessionLocal() as session:
        seed_database(session)

    yield

    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    app = create_app()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_token(db):
    user = db.query(User).filter(User.email == "admin@office.local").first()
    return create_session_token(db, user)


@pytest.fixture
def annotator_token(db):
    annotator_email = "annotator_1@office.local"
    user = db.query(User).filter(User.email == annotator_email).first()
    if not user:
        user = User(
            email=annotator_email,
            full_name="Annotator One",
            role="annotator",
            hashed_password=get_password_hash("Pass@123"),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return create_session_token(db, user)
