from __future__ import annotations

import numpy as np

from .conftest import get_labels, put_labels, review, set_mode

W, H = 64, 48


def labels_with(value=1):
    arr = np.zeros((H, W), dtype=np.uint8)
    arr[10:14, 5:50] = value
    return arr


def test_save_requires_lock(alice, image_id):
    r = put_labels(alice, image_id, labels_with(), 0)
    assert r.status_code == 423 and "expired" in r.json()["detail"]


def test_lock_is_exclusive_and_saves_are_exact(alice, bob, image_id):
    assert alice.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    blocked = bob.post(f"/api/v1/images/{image_id}/lock")
    assert blocked.status_code == 423 and "is editing" in blocked.json()["detail"]
    labels = labels_with()
    r = put_labels(alice, image_id, labels, 0)
    assert r.status_code == 200, r.text
    assert r.json()["revision"] == 1 and r.json()["class_pixels"] == {"1": 4 * 45}
    np.testing.assert_array_equal(get_labels(bob, image_id).reshape(H, W), labels)
    # Another user cannot save even with the right revision.
    assert put_labels(bob, image_id, labels, 1).status_code == 423
    # Stale revision is refused (no lost updates).
    stale = put_labels(alice, image_id, labels, 0)
    assert stale.status_code == 409 and "Reload" in stale.json()["detail"]
    # Uncompressed payloads work too.
    assert put_labels(alice, image_id, labels, 1, compress=False).status_code == 200


def test_invalid_labels_rejected(alice, image_id):
    alice.post(f"/api/v1/images/{image_id}/lock")
    bad = labels_with(7)
    r = put_labels(alice, image_id, bad, 0)
    assert r.status_code == 422 and "[7]" in r.json()["detail"]
    r = put_labels(alice, image_id, np.zeros((H, W - 1), dtype=np.uint8), 0)
    assert r.status_code == 422


def test_full_review_cycle(alice, bob, image_id, project_id):
    alice.post(f"/api/v1/images/{image_id}/lock")
    assert alice.post(f"/api/v1/images/{image_id}/submit", json={}).status_code == 409  # nothing saved yet
    put_labels(alice, image_id, labels_with(), 0)
    r = alice.post(f"/api/v1/images/{image_id}/submit", json={"note": "first pass"})
    assert r.status_code == 200 and r.json()["image"]["status"] == "submitted"
    # The submitter cannot keep editing a submitted image.
    blocked = put_labels(alice, image_id, labels_with(2), 1)
    assert blocked.status_code == 403 and "withdraw" in blocked.json()["detail"]
    # Reviewing happens in Review mode.
    assert review(bob, image_id).status_code == 409
    set_mode(bob, "review")
    # Changes need a comment.
    assert review(bob, image_id, "request_changes").status_code == 422
    r = review(bob, image_id, "request_changes", "Missed the tip")
    assert r.json()["image"]["status"] == "changes_requested"
    assert r.json()["image"]["versions"][0]["review_comment"] == "Missed the tip"
    # The submitter fixes and resubmits.
    fixed = labels_with()
    fixed[20:22, 5:10] = 2
    assert alice.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    assert put_labels(alice, image_id, fixed, 1).status_code == 200
    alice.post(f"/api/v1/images/{image_id}/submit", json={})
    img = review(bob, image_id, "approve", "Good").json()["image"]
    assert img["status"] == "approved"
    assert [v["status"] for v in img["versions"]] == ["approved", "changes_requested"]
    np.testing.assert_array_equal(get_labels(bob, image_id, version=2).reshape(H, W), fixed)
    events = alice.get(f"/api/v1/projects/{project_id}/activity").json()["events"]
    assert {"submitted", "approve", "request_changes", "labels_saved"} <= {e["action"] for e in events}


def test_no_self_approval(alice, carol, image_id):
    alice.post(f"/api/v1/images/{image_id}/lock")
    put_labels(alice, image_id, labels_with(), 0)
    alice.post(f"/api/v1/images/{image_id}/submit", json={})
    set_mode(alice, "review")
    r = review(alice, image_id)
    assert r.status_code == 403 and "another person" in r.json()["detail"]
    set_mode(carol, "review")
    assert review(carol, image_id).status_code == 200


def test_withdraw_and_restore(alice, image_id):
    alice.post(f"/api/v1/images/{image_id}/lock")
    first = labels_with()
    put_labels(alice, image_id, first, 0)
    alice.post(f"/api/v1/images/{image_id}/submit", json={})
    r = alice.post(f"/api/v1/images/{image_id}/withdraw")
    assert r.json()["image"]["status"] == "in_progress"
    alice.post(f"/api/v1/images/{image_id}/lock")
    put_labels(alice, image_id, np.zeros((H, W), dtype=np.uint8), 1)
    r = alice.post(f"/api/v1/images/{image_id}/restore/1")
    assert r.status_code == 200 and r.json()["image"]["working_revision"] == 3
    np.testing.assert_array_equal(get_labels(alice, image_id).reshape(H, W), first)


def test_editing_approved_image_reopens_it_but_keeps_approved_version(alice, bob, image_id):
    alice.post(f"/api/v1/images/{image_id}/lock")
    put_labels(alice, image_id, labels_with(), 0)
    alice.post(f"/api/v1/images/{image_id}/submit", json={})
    set_mode(bob, "review")
    review(bob, image_id)
    alice.post(f"/api/v1/images/{image_id}/lock")
    r = put_labels(alice, image_id, labels_with(2), 1)
    assert r.json()["status"] == "in_progress"
    detail = alice.get(f"/api/v1/images/{image_id}").json()["image"]
    assert detail["versions"][0]["status"] == "approved"


def test_admin_can_break_lock_others_cannot(alice, bob, admin, image_id):
    alice.post(f"/api/v1/images/{image_id}/lock")
    assert bob.delete(f"/api/v1/images/{image_id}/lock").status_code == 403
    assert admin.delete(f"/api/v1/images/{image_id}/lock?force=true").json()["released"] is True
    assert bob.post(f"/api/v1/images/{image_id}/lock").status_code == 200


def test_beacon_release_needs_no_header(app, alice, image_id):
    from fastapi.testclient import TestClient

    alice.post(f"/api/v1/images/{image_id}/lock")
    bare = TestClient(app, cookies=alice.cookies)
    assert bare.post(f"/api/v1/images/{image_id}/lock/release").json()["released"] is True


def test_next_image_prefers_my_returned_work(alice, bob, project_id, image_id):
    nxt = alice.get(f"/api/v1/projects/{project_id}/next").json()["image_id"]
    assert nxt == image_id
    assert bob.get(f"/api/v1/projects/{project_id}/next?mode=review").json()["image_id"] is None
    alice.post(f"/api/v1/images/{image_id}/lock")
    put_labels(alice, image_id, labels_with(), 0)
    alice.post(f"/api/v1/images/{image_id}/submit", json={})
    assert bob.get(f"/api/v1/projects/{project_id}/next?mode=review").json()["image_id"] == image_id
    # Nobody is handed their own submission to review.
    assert alice.get(f"/api/v1/projects/{project_id}/next?mode=review").json()["image_id"] is None
    assert alice.get(f"/api/v1/projects/{project_id}/next?mode=nonsense").status_code == 422


def test_mask_png_download(alice, image_id):
    alice.post(f"/api/v1/images/{image_id}/lock")
    put_labels(alice, image_id, labels_with(), 0)
    r = alice.get(f"/api/v1/images/{image_id}/mask.png?style=binary")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert "attachment" in r.headers["content-disposition"]
