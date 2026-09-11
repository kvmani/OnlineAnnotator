from __future__ import annotations

import pytest
from backend.app.models.image import MicrographImage


def test_multi_user_concurrency_locks(client, admin_token, annotator_token, db):
    # Find an image
    img = db.query(MicrographImage).first()
    assert img is not None
    image_id = img.id

    # 1. Admin acquires lock
    res1 = client.post(f"/api/v1/images/{image_id}/lock", headers={"Authorization": f"Bearer {admin_token}"})
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["success"] is True

    # 2. Annotator attempts to acquire lock while held by Admin -> 409 Conflict
    res2 = client.post(f"/api/v1/images/{image_id}/lock", headers={"Authorization": f"Bearer {annotator_token}"})
    assert res2.status_code == 409
    assert "currently locked by admin@office.local" in res2.json()["detail"]

    # 3. Admin checks image lock status -> locked_by_me is True
    res3 = client.get(f"/api/v1/images/{image_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert res3.status_code == 200
    assert res3.json()["lock_info"]["locked_by_me"] is True

    # 4. Annotator checks image lock status -> locked_by_me is False
    res4 = client.get(f"/api/v1/images/{image_id}", headers={"Authorization": f"Bearer {annotator_token}"})
    assert res4.status_code == 200
    assert res4.json()["lock_info"]["locked_by_me"] is False
    assert res4.json()["lock_info"]["is_locked"] is True

    # 5. Admin releases lock
    res5 = client.delete(f"/api/v1/images/{image_id}/lock", headers={"Authorization": f"Bearer {admin_token}"})
    assert res5.status_code == 200

    # 6. Annotator can now successfully acquire lock
    res6 = client.post(f"/api/v1/images/{image_id}/lock", headers={"Authorization": f"Bearer {annotator_token}"})
    assert res6.status_code == 200
    assert res6.json()["success"] is True

    # Cleanup: Annotator releases lock
    client.delete(f"/api/v1/images/{image_id}/lock", headers={"Authorization": f"Bearer {annotator_token}"})
