from __future__ import annotations

import numpy as np

from .conftest import get_labels, put_labels

W, H = 64, 48


def labels_with(value=1):
    arr = np.zeros((H, W), dtype=np.uint8)
    arr[10:14, 5:50] = value
    return arr


def test_save_requires_lock(ann, image_id):
    r = put_labels(ann, image_id, labels_with(), 0)
    assert r.status_code == 423 and "expired" in r.json()["detail"]


def test_lock_is_exclusive_and_saves_are_exact(ann, rev, image_id):
    assert ann.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    blocked = rev.post(f"/api/v1/images/{image_id}/lock")
    assert blocked.status_code == 423 and "is editing" in blocked.json()["detail"]
    labels = labels_with()
    r = put_labels(ann, image_id, labels, 0)
    assert r.status_code == 200, r.text
    assert r.json()["revision"] == 1 and r.json()["class_pixels"] == {"1": 4 * 45}
    np.testing.assert_array_equal(get_labels(rev, image_id).reshape(H, W), labels)
    # Another user cannot save even with the right revision.
    assert put_labels(rev, image_id, labels, 1).status_code == 423
    # Stale revision is refused (no lost updates).
    stale = put_labels(ann, image_id, labels, 0)
    assert stale.status_code == 409 and "Reload" in stale.json()["detail"]
    # Uncompressed payloads work too.
    assert put_labels(ann, image_id, labels, 1, compress=False).status_code == 200


def test_invalid_labels_rejected(ann, image_id):
    ann.post(f"/api/v1/images/{image_id}/lock")
    bad = labels_with(7)
    r = put_labels(ann, image_id, bad, 0)
    assert r.status_code == 422 and "[7]" in r.json()["detail"]
    r = put_labels(ann, image_id, np.zeros((H, W - 1), dtype=np.uint8), 0)
    assert r.status_code == 422


def test_full_review_cycle(ann, rev, image_id, project_id):
    ann.post(f"/api/v1/images/{image_id}/lock")
    assert ann.post(f"/api/v1/images/{image_id}/submit", json={}).status_code == 409  # nothing saved yet
    put_labels(ann, image_id, labels_with(), 0)
    r = ann.post(f"/api/v1/images/{image_id}/submit", json={"note": "first pass"})
    assert r.status_code == 200 and r.json()["image"]["status"] == "submitted"
    # Annotator cannot keep editing a submitted image.
    blocked = put_labels(ann, image_id, labels_with(2), 1)
    assert blocked.status_code == 409 and "Withdraw" in blocked.json()["detail"]
    # Annotator cannot review.
    assert ann.post(f"/api/v1/images/{image_id}/review", json={"decision": "approve"}).status_code == 403
    # Changes need a comment.
    r = rev.post(f"/api/v1/images/{image_id}/review", json={"decision": "request_changes"})
    assert r.status_code == 422
    r = rev.post(f"/api/v1/images/{image_id}/review", json={"decision": "request_changes",
                                                             "comment": "Missed the tip"})
    assert r.json()["image"]["status"] == "changes_requested"
    assert r.json()["image"]["versions"][0]["review_comment"] == "Missed the tip"
    # Annotator fixes and resubmits.
    fixed = labels_with()
    fixed[20:22, 5:10] = 2
    assert ann.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    assert put_labels(ann, image_id, fixed, 1).status_code == 200
    ann.post(f"/api/v1/images/{image_id}/submit", json={})
    r = rev.post(f"/api/v1/images/{image_id}/review", json={"decision": "approve", "comment": "Good"})
    img = r.json()["image"]
    assert img["status"] == "approved"
    assert [v["status"] for v in img["versions"]] == ["approved", "changes_requested"]
    np.testing.assert_array_equal(get_labels(rev, image_id, version=2).reshape(H, W), fixed)
    events = ann.get(f"/api/v1/projects/{project_id}/activity").json()["events"]
    assert {"submitted", "approve", "request_changes", "labels_saved"} <= {e["action"] for e in events}


def test_no_self_approval(rev, rev2, image_id):
    rev.post(f"/api/v1/images/{image_id}/lock")
    put_labels(rev, image_id, labels_with(), 0)
    rev.post(f"/api/v1/images/{image_id}/submit", json={})
    r = rev.post(f"/api/v1/images/{image_id}/review", json={"decision": "approve"})
    assert r.status_code == 403 and "another reviewer" in r.json()["detail"]
    assert rev2.post(f"/api/v1/images/{image_id}/review", json={"decision": "approve"}).status_code == 200


def test_reviewer_corrections_become_new_approved_version(ann, rev, image_id):
    ann.post(f"/api/v1/images/{image_id}/lock")
    put_labels(ann, image_id, labels_with(), 0)
    ann.post(f"/api/v1/images/{image_id}/submit", json={})
    assert rev.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    corrected = labels_with()
    corrected[30:33, 30:40] = 1
    assert put_labels(rev, image_id, corrected, 1).status_code == 200
    img = rev.post(f"/api/v1/images/{image_id}/review", json={"decision": "approve"}).json()["image"]
    assert img["status"] == "approved"
    top = img["versions"][0]
    assert top["kind"] == "reviewer_edit" and top["status"] == "approved" and top["created_by"] == "rev@lab.test"
    assert img["versions"][1]["status"] == "superseded"
    np.testing.assert_array_equal(get_labels(rev, image_id, version=top["number"]).reshape(H, W), corrected)


def test_withdraw_and_restore(ann, image_id):
    ann.post(f"/api/v1/images/{image_id}/lock")
    first = labels_with()
    put_labels(ann, image_id, first, 0)
    ann.post(f"/api/v1/images/{image_id}/submit", json={})
    r = ann.post(f"/api/v1/images/{image_id}/withdraw")
    assert r.json()["image"]["status"] == "in_progress"
    ann.post(f"/api/v1/images/{image_id}/lock")
    put_labels(ann, image_id, np.zeros((H, W), dtype=np.uint8), 1)
    r = ann.post(f"/api/v1/images/{image_id}/restore/1")
    assert r.status_code == 200 and r.json()["image"]["working_revision"] == 3
    np.testing.assert_array_equal(get_labels(ann, image_id).reshape(H, W), first)


def test_editing_approved_image_reopens_it_but_keeps_approved_version(ann, rev, image_id):
    ann.post(f"/api/v1/images/{image_id}/lock")
    put_labels(ann, image_id, labels_with(), 0)
    ann.post(f"/api/v1/images/{image_id}/submit", json={})
    rev.post(f"/api/v1/images/{image_id}/review", json={"decision": "approve"})
    ann.post(f"/api/v1/images/{image_id}/lock")
    r = put_labels(ann, image_id, labels_with(2), 1)
    assert r.json()["status"] == "in_progress"
    detail = ann.get(f"/api/v1/images/{image_id}").json()["image"]
    assert detail["versions"][0]["status"] == "approved"


def test_admin_can_break_lock_others_cannot(ann, rev, admin, image_id):
    ann.post(f"/api/v1/images/{image_id}/lock")
    assert rev.delete(f"/api/v1/images/{image_id}/lock").status_code == 403
    assert admin.delete(f"/api/v1/images/{image_id}/lock?force=true").json()["released"] is True
    assert rev.post(f"/api/v1/images/{image_id}/lock").status_code == 200


def test_beacon_release_needs_no_header(app, ann, image_id):
    from fastapi.testclient import TestClient

    ann.post(f"/api/v1/images/{image_id}/lock")
    bare = TestClient(app, cookies=ann.cookies)
    assert bare.post(f"/api/v1/images/{image_id}/lock/release").json()["released"] is True


def test_next_image_prefers_my_returned_work(ann, rev, project_id, image_id):
    nxt = ann.get(f"/api/v1/projects/{project_id}/next").json()["image_id"]
    assert nxt == image_id
    assert rev.get(f"/api/v1/projects/{project_id}/next?mode=review").json()["image_id"] is None
    ann.post(f"/api/v1/images/{image_id}/lock")
    put_labels(ann, image_id, labels_with(), 0)
    ann.post(f"/api/v1/images/{image_id}/submit", json={})
    assert rev.get(f"/api/v1/projects/{project_id}/next?mode=review").json()["image_id"] == image_id
    assert ann.get(f"/api/v1/projects/{project_id}/next?mode=review").status_code == 403


def test_mask_png_download(ann, image_id):
    ann.post(f"/api/v1/images/{image_id}/lock")
    put_labels(ann, image_id, labels_with(), 0)
    r = ann.get(f"/api/v1/images/{image_id}/mask.png?style=binary")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert "attachment" in r.headers["content-disposition"]
