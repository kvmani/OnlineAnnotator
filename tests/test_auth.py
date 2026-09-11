from __future__ import annotations

from fastapi.testclient import TestClient

from online_annotator.app import create_app
from online_annotator.config import load_settings
from online_annotator.services import auth as auth_ops

from .conftest import HEADERS, make_client


def test_login_and_me(admin):
    me = admin.get("/api/v1/auth/me").json()["user"]
    assert me["email"] == "admin@lab.test" and me["role"] == "admin"


def test_wrong_password_is_generic_and_rate_limited(app):
    client = TestClient(app, headers=HEADERS)
    for _ in range(10):
        r = client.post("/api/v1/auth/login", json={"email": "ann@lab.test", "password": "nope-nope-1"})
        assert r.status_code == 401
        assert "not correct" in r.json()["detail"]
    r = client.post("/api/v1/auth/login", json={"email": "ann@lab.test", "password": "annot-pass-1"})
    assert r.status_code == 401 and "Too many" in r.json()["detail"]


def test_unknown_account_same_message(app):
    client = TestClient(app, headers=HEADERS)
    r = client.post("/api/v1/auth/login", json={"email": "ghost@lab.test", "password": "whatever-1"})
    assert r.status_code == 401 and "not correct" in r.json()["detail"]


def test_api_requires_session(app):
    client = TestClient(app, headers=HEADERS)
    assert client.get("/api/v1/projects").status_code == 401
    assert client.get("/api/v1/images/1/display").status_code == 401


def test_mutation_without_client_header_is_blocked(app):
    client = TestClient(app)
    r = client.post("/api/v1/auth/login", json={"email": "admin@lab.test", "password": "admin-pass-1"})
    assert r.status_code == 403 and "cross-site" in r.json()["detail"]


def test_otp_disabled_by_default_and_never_leaks_code(app):
    client = TestClient(app, headers=HEADERS)
    assert client.get("/api/v1/auth/options").json()["otp"] is False
    r = client.post("/api/v1/auth/otp/request", json={"email": "admin@lab.test"})
    assert r.status_code == 400
    assert "code" not in r.json() and "dev_otp" not in r.text


def test_otp_flow_with_mail_server(tmp_path, monkeypatch):
    sent = {}
    settings = load_settings(environ={}, data_dir=tmp_path / "d", secret_key="k",
                             email={"enabled": True, "smtp_host": "mail.lab.test"})
    application = create_app(settings, admin_email="boss@lab.test", admin_password="boss-pass-1")
    monkeypatch.setattr(auth_ops, "send_mail", lambda s, to, subj, body: sent.update(to=to, body=body))
    with TestClient(application, headers=HEADERS) as client:
        r = client.post("/api/v1/auth/otp/request", json={"email": "boss@lab.test"})
        assert r.status_code == 200 and "code" not in r.json()
        code = sent["body"].split("code is ")[1][:6]
        bad = client.post("/api/v1/auth/otp/verify", json={"challenge_id": r.json()["challenge_id"], "code": "000000"})
        assert bad.status_code == 401
        ok = client.post("/api/v1/auth/otp/verify", json={"challenge_id": r.json()["challenge_id"], "code": code})
        assert ok.status_code == 200 and ok.json()["user"]["email"] == "boss@lab.test"
        again = client.post("/api/v1/auth/otp/verify", json={"challenge_id": r.json()["challenge_id"], "code": code})
        assert again.status_code == 401
        # Unknown address: same response, nothing mailed, no account created.
        sent.clear()
        r = client.post("/api/v1/auth/otp/request", json={"email": "stranger@lab.test"})
        assert r.status_code == 200 and not sent


def test_bootstrap_generates_one_time_password(tmp_path):
    settings = load_settings(environ={}, data_dir=tmp_path / "d", secret_key="k")
    application = create_app(settings)
    with TestClient(application, headers=HEADERS) as client:
        note = (tmp_path / "d" / "initial_admin_password.txt").read_text()
        email = note.split("e-mail:")[1].split()[0]
        password = note.split("password:")[1].split()[0]
        r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert r.json()["user"]["must_change_password"] is True
        assert client.get("/api/v1/projects").status_code == 403
        r = client.post("/api/v1/auth/change-password", json={"current_password": password,
                                                             "new_password": "a-better-pass-9"})
        assert r.status_code == 200
        assert client.get("/api/v1/projects").status_code == 200


def test_weak_password_rejected(admin):
    r = admin.post("/api/v1/auth/change-password", json={"current_password": "admin-pass-1",
                                                         "new_password": "12345678"})
    assert r.status_code == 400


def test_admin_creates_user_with_temporary_password(app, admin):
    r = admin.post("/api/v1/users", json={"email": "New.Person@Lab.test", "full_name": "New Person",
                                          "role": "annotator"})
    assert r.status_code == 200
    temp = r.json()["temporary_password"]
    assert r.json()["user"]["email"] == "new.person@lab.test"
    client = TestClient(app, headers=HEADERS)
    login = client.post("/api/v1/auth/login", json={"email": "new.person@lab.test", "password": temp})
    assert login.json()["user"]["must_change_password"] is True
    assert admin.post("/api/v1/users", json={"email": "new.person@lab.test", "full_name": "X"}).status_code == 409


def test_non_admin_cannot_manage_users(ann):
    assert ann.post("/api/v1/users", json={"email": "x@lab.test", "full_name": "X"}).status_code == 403


def test_admin_cannot_demote_self(admin):
    me = admin.get("/api/v1/auth/me").json()["user"]
    assert admin.patch(f"/api/v1/users/{me['id']}", json={"role": "annotator"}).status_code == 400


def test_disabled_user_loses_session(app, admin):
    ann = make_client(app, "ann@lab.test")
    users = admin.get("/api/v1/users").json()["users"]
    ann_id = next(u["id"] for u in users if u["email"] == "ann@lab.test")
    assert admin.patch(f"/api/v1/users/{ann_id}", json={"is_active": False}).status_code == 200
    assert ann.get("/api/v1/projects").status_code == 401


def test_logout(admin):
    assert admin.post("/api/v1/auth/logout").status_code == 200
    assert admin.get("/api/v1/auth/me").status_code == 401
