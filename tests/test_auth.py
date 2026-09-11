from __future__ import annotations

import pytest


def test_password_login_success(client):
    res = client.post("/api/v1/auth/login", json={
        "email": "admin@office.local",
        "password": "Admin@123",
    })
    assert res.status_code == 200
    data = res.json()
    assert "token" in data
    assert data["user"]["email"] == "admin@office.local"
    assert data["user"]["role"] == "admin"


def test_password_login_invalid_credentials(client):
    res = client.post("/api/v1/auth/login", json={
        "email": "admin@office.local",
        "password": "WrongPassword",
    })
    assert res.status_code == 401


def test_office_email_format_validation(client):
    # Rejects non-email usernames
    res = client.post("/api/v1/auth/login", json={
        "email": "plain_username_not_email",
        "password": "Password123",
    })
    assert res.status_code == 422  # Validation error


def test_email_otp_lifecycle(client):
    email = "scientist@office.local"
    # Step 1: Request OTP
    req_res = client.post("/api/v1/auth/email-otp/request", json={"email": email})
    assert req_res.status_code == 200
    req_data = req_res.json()
    assert "challenge_id" in req_data
    assert req_data["dev_otp"] is not None  # In dev mode, OTP is provided for test suites

    challenge_id = req_data["challenge_id"]
    dev_otp = req_data["dev_otp"]

    # Step 2: Try invalid OTP
    bad_res = client.post("/api/v1/auth/email-otp/confirm", json={
        "challenge_id": challenge_id,
        "otp": "000000",
    })
    assert bad_res.status_code == 400

    # Step 3: Confirm with valid OTP
    good_res = client.post("/api/v1/auth/email-otp/confirm", json={
        "challenge_id": challenge_id,
        "otp": dev_otp,
    })
    assert good_res.status_code == 200
    good_data = good_res.json()
    assert "token" in good_data
    assert good_data["user"]["email"] == email


def test_get_current_user_profile(client, admin_token):
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "admin@office.local"
    assert data["role"] == "admin"


def test_logout(client, admin_token):
    res = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
