from __future__ import annotations

import io
import pytest


def test_list_projects(client, admin_token):
    res = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    assert any("Hydride" in p["name"] for p in data)


def test_create_project_with_classes(client, admin_token):
    res = client.post("/api/v1/projects", headers={"Authorization": f"Bearer {admin_token}"}, json={
        "name": "Steel Inclusions Phase Analysis",
        "description": "Microstructural semantic segmentation for oxide and sulfide inclusions.",
        "classes": [
            {"name": "Oxide Inclusion", "color_hex": "#E74C3C", "class_index": 1, "is_default": True},
            {"name": "Sulfide Inclusion", "color_hex": "#F39C12", "class_index": 2},
            {"name": "Ferrite Matrix", "color_hex": "#27AE60", "class_index": 3},
        ],
    })
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Steel Inclusions Phase Analysis"
    assert len(data["classes"]) == 3


def test_upload_image_to_project(client, admin_token):
    # Get project id
    p_res = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {admin_token}"})
    project_id = p_res.json()[0]["id"]

    # Create dummy PNG image bytes
    from PIL import Image
    buf = io.BytesIO()
    im = Image.new("RGB", (256, 256), color=(180, 180, 180))
    im.save(buf, format="PNG")
    buf.seek(0)

    files = [("files", ("test_micrograph.png", buf.getvalue(), "image/png"))]
    upload_res = client.post(
        f"/api/v1/projects/{project_id}/images",
        headers={"Authorization": f"Bearer {admin_token}"},
        files=files,
        data={"split_assignment": "train"},
    )
    assert upload_res.status_code == 200
    data = upload_res.json()
    assert data["uploaded_count"] >= 1
