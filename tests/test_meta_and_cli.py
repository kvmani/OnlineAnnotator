from __future__ import annotations

from fastapi.testclient import TestClient

from online_annotator import __version__
from online_annotator.app import create_app
from online_annotator.cli import main
from online_annotator.config import load_settings
from online_annotator.services.demo import DEMO_PROJECT, synthetic_micrograph

from .conftest import HEADERS


def test_health_contract(app):
    client = TestClient(app)
    for path in ("/api/health", "/health"):
        assert client.get(path).json() == {"status": "ok", "tool_id": "online-annotator", "version": __version__}
    assert client.get("/api/health/deep").json()["storage_writable"] is True


def test_security_headers_and_spa(app):
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200 and __version__ in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/help", follow_redirects=False).headers["location"] == "./#/help"


def test_meta(app):
    meta = TestClient(app).get("/api/v1/meta").json()
    assert meta["version"] == __version__ and meta["otp_login"] is False


def test_env_overrides(tmp_path):
    settings = load_settings(environ={"ONLINE_ANNOTATOR_PORT": "6000", "ONLINE_ANNOTATOR_EMAIL__SMTP_HOST": "10.0.0.1",
                                      "ONLINE_ANNOTATOR_ALLOWED_EMAIL_DOMAINS": '["Lab.Test"]'},
                             data_dir=tmp_path)
    assert settings.port == 6000 and settings.email.smtp_host == "10.0.0.1"
    assert settings.allowed_email_domains == ["lab.test"]


def test_demo_mode_seeds_project_and_accounts(tmp_path):
    settings = load_settings(environ={}, data_dir=tmp_path / "d", secret_key="k", demo=True)
    with TestClient(create_app(settings), headers=HEADERS) as client:
        r = client.post("/api/v1/auth/login", json={"email": "annotator@demo.local", "password": "annotate-demo-1"})
        assert r.status_code == 200
        projects = client.get("/api/v1/projects").json()["projects"]
        assert projects[0]["name"] == DEMO_PROJECT and projects[0]["counts"]["total"] == 6


def test_synthetic_micrograph_is_deterministic():
    assert synthetic_micrograph(3) == synthetic_micrograph(3)


def test_cli_create_and_reset(tmp_path, capsys):
    data = str(tmp_path / "cli")
    assert main(["create-user", "lead@lab.test", "--role", "reviewer", "--password", "lead-pass-1",
                 "--data-dir", data]) == 0
    assert main(["create-user", "lead@lab.test", "--password", "lead-pass-1", "--data-dir", data]) == 2
    assert main(["reset-password", "lead@lab.test", "--data-dir", data]) == 0
    assert "Temporary password" in capsys.readouterr().out
