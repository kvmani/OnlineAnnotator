from __future__ import annotations

import pytest
from backend.app.models.image import MicrographImage


def test_annotation_draft_save_and_retrieve(client, admin_token, db):
    img = db.query(MicrographImage).first()
    image_id = img.id

    # 1. Save draft
    shapes = [
        {
            "id": "shape_1",
            "type": "polygon",
            "class_index": 1,
            "color": "#FF0000",
            "points": [[10, 10], [50, 15], [45, 60], [15, 55]],
            "closed": True,
        }
    ]

    save_res = client.post(
        f"/api/v1/annotations/{image_id}/draft",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "vector_data": shapes,
            "zoom_level": 1.25,
            "pan_x": 30.0,
            "pan_y": 45.0,
            "active_class_index": 1,
            "active_tool": "polygon",
            "brush_size": 15,
        },
    )
    assert save_res.status_code == 200
    save_data = save_res.json()
    assert len(save_data["vector_data"]) == 1
    assert save_data["zoom_level"] == 1.25

    # 2. Retrieve draft
    get_res = client.get(f"/api/v1/annotations/{image_id}/draft", headers={"Authorization": f"Bearer {admin_token}"})
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert len(get_data["vector_data"]) == 1
    assert get_data["vector_data"][0]["id"] == "shape_1"


def test_commit_version_and_review_workflow(client, admin_token, db):
    img = db.query(MicrographImage).first()
    image_id = img.id

    shapes = [
        {
            "id": "shape_v1",
            "type": "brush_stroke",
            "class_index": 1,
            "color": "#FF0000",
            "brush_size": 10,
            "points": [[20, 20], [25, 25], [30, 30]],
        }
    ]

    # 1. Commit Version 1
    commit_res = client.post(
        f"/api/v1/annotations/{image_id}/commit",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "vector_data": shapes,
            "comment": "Initial complete hydride outline",
            "submit_for_review": True,
        },
    )
    assert commit_res.status_code == 200
    commit_data = commit_res.json()
    assert commit_data["version_number"] >= 1
    assert commit_data["status"] == "submitted_for_review"

    # 2. List versions
    ver_res = client.get(f"/api/v1/annotations/{image_id}/versions", headers={"Authorization": f"Bearer {admin_token}"})
    assert ver_res.status_code == 200
    versions = ver_res.json()
    assert len(versions) >= 1

    # 3. Reviewer approves annotation
    rev_res = client.post(
        f"/api/v1/annotations/{image_id}/review",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "action": "approve",
            "comment": "Accurate hydride platelet boundaries.",
        },
    )
    assert rev_res.status_code == 200
    assert rev_res.json()["status"] == "completed"

    # 4. Check image status is now completed
    img_check = client.get(f"/api/v1/images/{image_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert img_check.json()["status"] == "completed"
