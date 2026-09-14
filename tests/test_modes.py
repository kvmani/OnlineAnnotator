"""Every user annotates and reviews; the working mode says which, and the server enforces it.

alice, bob and carol are ordinary users with identical rights. admin is an administrator. Each
test states which mode a user works in, because that -- not a role -- decides what they may do.
"""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from online_annotator.config import load_settings

from .conftest import (
    HEADERS,
    annotate_and_submit,
    build_app,
    get_labels,
    make_client,
    png_bytes,
    put_labels,
    review,
    set_mode,
    upload,
)

W, H = 64, 48


def labels(value: int = 1) -> np.ndarray:
    arr = np.zeros((H, W), dtype=np.uint8)
    arr[10:14, 5:50] = value
    return arr


def next_image(client, project_id: int, mode: str | None = None):
    url = f"/api/v1/projects/{project_id}/next" + (f"?mode={mode}" if mode else "")
    r = client.get(url)
    assert r.status_code == 200, r.text
    return r.json()["image_id"]


def queue(client, project_id: int) -> dict:
    return client.get(f"/api/v1/projects/{project_id}").json()["project"]["queue"]


# ------------------------------------------------------------------------ the account model
def test_users_have_a_privilege_and_a_working_mode_but_no_role(admin, alice):
    me = alice.get("/api/v1/auth/me").json()["user"]
    assert me["is_admin"] is False and me["active_mode"] == "annotate"
    assert "role" not in me
    assert admin.get("/api/v1/auth/me").json()["user"]["is_admin"] is True


def test_the_working_mode_is_kept_per_account(app, alice, bob):
    set_mode(alice, "review")
    elsewhere = make_client(app, "alice@lab.test")  # a new sign-in, e.g. at another desk
    assert elsewhere.get("/api/v1/auth/me").json()["user"]["active_mode"] == "review"
    assert bob.get("/api/v1/auth/me").json()["user"]["active_mode"] == "annotate"
    set_mode(elsewhere, "annotate")
    assert alice.get("/api/v1/auth/me").json()["user"]["active_mode"] == "annotate"


def test_switching_mode_is_validated_and_needs_a_real_session(app, admin, alice):
    assert alice.put("/api/v1/auth/mode", json={"mode": "admin"}).status_code == 422
    assert TestClient(app, headers=HEADERS).put("/api/v1/auth/mode", json={"mode": "review"}).status_code == 401
    # The CSRF guard covers PUT like every other mutation.
    assert TestClient(app, cookies=alice.cookies).put("/api/v1/auth/mode", json={"mode": "review"}).status_code == 403
    temp = admin.post("/api/v1/users", json={"email": "new@lab.test", "full_name": "New"}).json()["temporary_password"]
    newcomer = TestClient(app, headers=HEADERS)
    assert newcomer.post("/api/v1/auth/login", json={"email": "new@lab.test", "password": temp}).status_code == 200
    assert newcomer.put("/api/v1/auth/mode", json={"mode": "review"}).status_code == 403


# --------------------------------------------------- the two-person workflow, both directions
def test_alice_annotates_and_bob_reviews(alice, bob, project_id, image_id):
    annotate_and_submit(alice, image_id, labels(), note="first pass")
    assert queue(bob, project_id)["review"] == 1
    set_mode(bob, "review")
    assert next_image(bob, project_id) == image_id  # "next" follows the active mode
    r = review(bob, image_id, "approve", "Good")
    assert r.status_code == 200, r.text
    image = r.json()["image"]
    assert image["status"] == "approved"
    top = image["versions"][0]
    assert (top["created_by"], top["reviewed_by"], top["note"]) == ("alice@lab.test", "bob@lab.test", "first pass")


def test_bob_annotates_and_alice_reviews(alice, bob, project_id):
    image = upload(bob, project_id, "from bob.png", seed=2)
    annotate_and_submit(bob, image, labels(2))
    set_mode(alice, "review")
    assert next_image(alice, project_id) == image
    r = review(alice, image)
    assert r.status_code == 200, r.text
    top = r.json()["image"]["versions"][0]
    assert (top["created_by"], top["reviewed_by"]) == ("bob@lab.test", "alice@lab.test")


def test_one_account_alternates_between_annotating_and_reviewing(alice, bob, project_id, image_id):
    bobs = upload(bob, project_id, "bob's.png", seed=3)
    annotate_and_submit(alice, image_id, labels())
    annotate_and_submit(bob, bobs, labels(2))

    set_mode(alice, "review")
    assert next_image(alice, project_id) == bobs  # her own submission is not offered
    assert review(alice, bobs).status_code == 200

    set_mode(alice, "annotate")
    third = upload(alice, project_id, "third.png", seed=4)
    annotate_and_submit(alice, third, labels())

    set_mode(bob, "review")
    assert next_image(bob, project_id) == image_id  # oldest submission first
    assert review(bob, image_id).status_code == 200
    assert review(bob, third).status_code == 200


# ------------------------------------------------------------------------- mode enforcement
def test_review_mode_does_not_annotate(alice, project_id, image_id):
    set_mode(alice, "review")
    assert alice.post(f"/api/v1/images/{image_id}/lock").status_code == 200  # opening is not editing
    r = put_labels(alice, image_id, labels(), 0)
    assert r.status_code == 409 and "Switch to Annotate mode" in r.json()["detail"]
    assert "Annotate mode" in alice.post(f"/api/v1/images/{image_id}/submit", json={}).json()["detail"]
    mask = (labels() * 255).astype(np.uint8)
    r = alice.post(f"/api/v1/images/{image_id}/mask-import", files=[("file", ("m.png", png_bytes(mask), "image/png"))])
    assert r.status_code == 409 and "Annotate mode" in r.json()["detail"]
    r = alice.post(f"/api/v1/projects/{project_id}/masks",
                   files=[("files", ("sample one_mask.png", png_bytes(mask), "image/png"))])
    assert r.status_code == 409 and "Annotate mode" in r.json()["detail"]

    set_mode(alice, "annotate")
    assert put_labels(alice, image_id, labels(), 0).status_code == 200


def test_annotate_mode_does_not_review(alice, bob, image_id):
    annotate_and_submit(alice, image_id, labels())
    r = review(bob, image_id)
    assert r.status_code == 409 and "Switch to Review mode" in r.json()["detail"]
    assert bob.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    r = put_labels(bob, image_id, labels(2), 1)
    assert r.status_code == 409 and "Review mode" in r.json()["detail"]

    set_mode(bob, "review")
    assert put_labels(bob, image_id, labels(2), 1).status_code == 200  # a review correction
    assert review(bob, image_id).status_code == 200


# -------------------------------------------------------------- own-submission protection
def test_nobody_reviews_their_own_submission(alice, bob, project_id, image_id):
    annotate_and_submit(alice, image_id, labels())
    set_mode(alice, "review")
    assert queue(alice, project_id) == {"annotate": 0, "review": 0, "own_pending": 1}
    assert next_image(alice, project_id) is None

    for decision, comment in (("approve", ""), ("request_changes", "Missed a tip")):
        r = review(alice, image_id, decision, comment)
        assert r.status_code == 403 and "another person" in r.json()["detail"]
    assert alice.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    r = put_labels(alice, image_id, labels(2), 1)
    assert r.status_code == 403 and "withdraw" in r.json()["detail"]

    assert alice.get(f"/api/v1/images/{image_id}").json()["image"]["status"] == "submitted"
    assert queue(bob, project_id)["review"] == 1


def test_self_approval_configuration_lets_people_review_their_own_work(tmp_path):
    settings = load_settings(environ={}, data_dir=tmp_path / "d", secret_key="k", allow_self_approval=True)
    application = build_app(settings)
    alice = make_client(application, "alice@lab.test")
    project_id = alice.get("/api/v1/projects").json()["projects"][0]["id"]
    image = upload(alice, project_id)
    annotate_and_submit(alice, image, labels())
    set_mode(alice, "review")
    assert queue(alice, project_id)["review"] == 1
    assert next_image(alice, project_id) == image
    assert review(alice, image).status_code == 200


def test_only_the_submitter_or_an_administrator_withdraws(alice, bob, admin, image_id):
    annotate_and_submit(alice, image_id, labels())
    set_mode(bob, "review")
    r = bob.post(f"/api/v1/images/{image_id}/withdraw")
    assert r.status_code == 403 and "administrator" in r.json()["detail"]

    set_mode(alice, "review")  # taking back your own work is allowed in either mode
    assert alice.post(f"/api/v1/images/{image_id}/withdraw").json()["image"]["status"] == "in_progress"

    set_mode(alice, "annotate")
    assert alice.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    assert alice.post(f"/api/v1/images/{image_id}/submit", json={}).status_code == 200
    assert admin.post(f"/api/v1/images/{image_id}/withdraw").status_code == 200


# ------------------------------------------------ corrections, returns and resubmission
def test_returned_work_is_fixed_resubmitted_and_approved_by_someone_else(alice, bob, carol, project_id, image_id):
    annotate_and_submit(alice, image_id, labels(), note="first")
    set_mode(bob, "review")
    r = review(bob, image_id, "request_changes", "Missed the tip")
    assert r.status_code == 200 and r.json()["image"]["status"] == "changes_requested"

    assert next_image(alice, project_id) == image_id  # returned work comes first
    fixed = labels()
    fixed[20:22, 5:10] = 2
    annotate_and_submit(alice, image_id, fixed, note="tip added")

    set_mode(carol, "review")
    r = review(carol, image_id, "approve", "Good now")
    image = r.json()["image"]
    assert image["status"] == "approved"
    assert [(v["status"], v["reviewed_by"]) for v in image["versions"]] == [
        ("approved", "carol@lab.test"), ("changes_requested", "bob@lab.test")]
    np.testing.assert_array_equal(get_labels(carol, image_id, version=2).reshape(H, W), fixed)


def test_a_review_correction_is_approved_as_a_new_version(alice, bob, image_id):
    annotate_and_submit(alice, image_id, labels())
    set_mode(bob, "review")
    assert bob.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    corrected = labels()
    corrected[30:33, 30:40] = 1
    assert put_labels(bob, image_id, corrected, 1).status_code == 200
    image = review(bob, image_id).json()["image"]
    top, original = image["versions"][0], image["versions"][1]
    assert (top["kind"], top["status"], top["created_by"]) == ("reviewer_edit", "approved", "bob@lab.test")
    assert (original["status"], original["created_by"]) == ("superseded", "alice@lab.test")
    np.testing.assert_array_equal(get_labels(bob, image_id, version=top["number"]).reshape(H, W), corrected)


# ------------------------------------------------------ administrator privilege is separate
def test_administrator_rights_do_not_depend_on_the_mode(admin, alice, project_id, image_id):
    for mode in ("annotate", "review"):
        set_mode(admin, mode)
        assert admin.post("/api/v1/projects", json={"name": f"Made in {mode} mode"}).status_code == 200
        assert admin.post("/api/v1/users", json={"email": f"{mode}@lab.test", "full_name": mode}).status_code == 200

    assert alice.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    assert admin.delete(f"/api/v1/images/{image_id}/lock?force=true").json()["released"] is True
    assert admin.delete(f"/api/v1/images/{image_id}").status_code == 200


def test_a_working_mode_never_grants_administrator_rights(alice, project_id, image_id):
    for mode in ("annotate", "review"):
        set_mode(alice, mode)
        assert alice.post("/api/v1/projects", json={"name": f"Not allowed {mode}"}).status_code == 403
        assert alice.post("/api/v1/users", json={"email": "x@lab.test", "full_name": "X"}).status_code == 403
        assert alice.delete(f"/api/v1/images/{image_id}").status_code == 403


def test_administrators_review_like_everyone_else(admin, alice, image_id):
    annotate_and_submit(alice, image_id, labels())
    set_mode(admin, "annotate")
    assert review(admin, image_id).status_code == 409
    set_mode(admin, "review")
    assert review(admin, image_id).status_code == 200


def test_administrator_privilege_is_granted_and_revoked(admin, alice):
    users = admin.get("/api/v1/users").json()["users"]
    alice_id = next(u["id"] for u in users if u["email"] == "alice@lab.test")
    assert admin.patch(f"/api/v1/users/{alice_id}", json={"is_admin": True}).json()["user"]["is_admin"] is True
    assert alice.post("/api/v1/projects", json={"name": "Alice's project"}).status_code == 200
    assert admin.patch(f"/api/v1/users/{alice_id}", json={"is_admin": False}).status_code == 200
    assert alice.post("/api/v1/projects", json={"name": "Another project"}).status_code == 403
    me = admin.get("/api/v1/auth/me").json()["user"]
    assert admin.patch(f"/api/v1/users/{me['id']}", json={"is_admin": False}).status_code == 400


# ----------------------------------------------------- dataset curation is open to everyone
def test_splits_assignments_and_exports_are_open_to_every_user(alice, bob, project_id, image_id):
    for mode in ("annotate", "review"):
        set_mode(alice, mode)
        body = {"image_ids": [image_id], "split": "val" if mode == "annotate" else "test"}
        assert alice.post(f"/api/v1/projects/{project_id}/images/bulk", json=body).json()["updated"] == 1
    assert alice.patch(f"/api/v1/images/{image_id}", json={"assigned_to": "bob@lab.test"}).status_code == 200
    detail = alice.get(f"/api/v1/images/{image_id}").json()["image"]
    assert (detail["split"], detail["assigned_to"]) == ("test", "bob@lab.test")
    assert alice.post(f"/api/v1/projects/{project_id}/exports/preview", json={}).status_code == 200
