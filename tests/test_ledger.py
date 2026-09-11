from __future__ import annotations

import pytest


def test_working_ledger_and_resumption(client, admin_token):
    # Retrieve recent ledger entries
    res = client.get("/api/v1/ledger/recent?limit=10", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    entries = res.json()
    assert len(entries) >= 1

    # Check resumption state
    resume_res = client.get("/api/v1/ledger/resume", headers={"Authorization": f"Bearer {admin_token}"})
    assert resume_res.status_code == 200
    state = resume_res.json()
    assert "can_resume" in state
    if state["can_resume"]:
        assert "image_id" in state
        assert "project_id" in state
