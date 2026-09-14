from __future__ import annotations

import gzip
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from online_annotator.app import create_app
from online_annotator.config import load_settings
from online_annotator.models import LabelClass, Project, User
from online_annotator.services.auth import hash_password

HEADERS = {"X-Requested-With": "OnlineAnnotator"}
# One administrator and three ordinary users. None of the ordinary users is an "annotator" or a
# "reviewer": each of them annotates or reviews depending on the working mode they switch to.
PASSWORDS = {"admin@lab.test": "admin-pass-1", "alice@lab.test": "alice-pass-1", "bob@lab.test": "bob-pass-1",
             "carol@lab.test": "carol-pass-1"}


def build_app(settings):
    application = create_app(settings, admin_email="admin@lab.test", admin_password=PASSWORDS["admin@lab.test"])
    with TestClient(application) as client:  # runs lifespan (bootstrap)
        client.close()
    with application.state.session_factory() as db:
        for email in ("alice@lab.test", "bob@lab.test", "carol@lab.test"):
            db.add(User(email=email, full_name=email.split("@")[0].title(),
                        password_hash=hash_password(PASSWORDS[email])))
        project = Project(name="Hydrides", created_by="admin@lab.test", guidelines="Label hydrides.")
        project.classes.append(LabelClass(index=1, name="Hydride", color="#FF0000"))
        project.classes.append(LabelClass(index=2, name="Pore", color="#0000FF"))
        db.add(project)
        db.commit()
    return application


@pytest.fixture
def settings(tmp_path):
    return load_settings(environ={}, data_dir=tmp_path / "data", secret_key="test-secret")


@pytest.fixture
def app(settings):
    return build_app(settings)


def make_client(app, email: str | None = None) -> TestClient:
    client = TestClient(app, headers=HEADERS)
    if email:
        r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORDS[email]})
        assert r.status_code == 200, r.text
    return client


@pytest.fixture
def admin(app):
    return make_client(app, "admin@lab.test")


@pytest.fixture
def alice(app):
    return make_client(app, "alice@lab.test")


@pytest.fixture
def bob(app):
    return make_client(app, "bob@lab.test")


@pytest.fixture
def carol(app):
    return make_client(app, "carol@lab.test")


def set_mode(client, mode: str) -> dict:
    r = client.put("/api/v1/auth/mode", json={"mode": mode})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["active_mode"] == mode
    return r.json()["user"]


def png_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    PILImage.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def sample_image(width=64, height=48, seed=0) -> bytes:
    rng = np.random.default_rng(seed)
    arr = rng.integers(150, 220, (height, width), dtype=np.uint8)
    arr[10:14, 5:50] = 40
    return png_bytes(arr)


@pytest.fixture
def project_id(app):
    with app.state.session_factory() as db:
        return db.query(Project).filter(Project.name == "Hydrides").one().id


def upload(client, project_id: int, name: str = "sample one.png", seed: int = 0) -> int:
    r = client.post(f"/api/v1/projects/{project_id}/images",
                    files=[("files", (name, sample_image(seed=seed), "image/png"))])
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 1, r.json()
    images = client.get(f"/api/v1/projects/{project_id}/images").json()["images"]
    return max(i["id"] for i in images)


@pytest.fixture
def image_id(alice, project_id):
    return upload(alice, project_id)


def put_labels(client, image_id: int, labels: np.ndarray, base_revision: int, compress: bool = True):
    raw = np.ascontiguousarray(labels, dtype=np.uint8).tobytes()
    headers = {"Content-Type": "application/octet-stream"}
    if compress:
        raw = gzip.compress(raw)
        headers["Content-Encoding"] = "gzip"
    return client.put(f"/api/v1/images/{image_id}/labels?base_revision={base_revision}", content=raw,
                      headers=headers)


def get_labels(client, image_id: int, version: int | None = None) -> np.ndarray:
    url = f"/api/v1/images/{image_id}/labels" + (f"?version={version}" if version else "")
    r = client.get(url)
    assert r.status_code == 200
    return np.frombuffer(r.content, dtype=np.uint8)


def annotate_and_submit(client, image_id: int, labels: np.ndarray, note: str = "") -> dict:
    """Lease, save and submit one image, as a user working in Annotate mode would."""
    assert client.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    revision = client.get(f"/api/v1/images/{image_id}").json()["image"]["working_revision"]
    r = put_labels(client, image_id, labels, revision)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/images/{image_id}/submit", json={"note": note})
    assert r.status_code == 200, r.text
    return r.json()["image"]


def review(client, image_id: int, decision: str = "approve", comment: str = ""):
    return client.post(f"/api/v1/images/{image_id}/review", json={"decision": decision, "comment": comment})
