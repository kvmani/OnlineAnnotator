from __future__ import annotations

import io

import numpy as np
from PIL import Image as PILImage

from .conftest import get_labels, png_bytes, put_labels, sample_image


def test_create_project_admin_only(admin, ann):
    body = {"name": "Grain boundaries", "classes": [{"name": "Boundary", "color": "#00ff00"}]}
    assert ann.post("/api/v1/projects", json=body).status_code == 403
    r = admin.post("/api/v1/projects", json=body)
    assert r.status_code == 200
    project = r.json()["project"]
    assert project["classes"][0] == {**project["classes"][0], "index": 1, "color": "#00FF00"}
    assert admin.post("/api/v1/projects", json=body).status_code == 409


def test_class_rules(admin, project_id):
    r = admin.post(f"/api/v1/projects/{project_id}/classes", json={"name": "Crack", "color": "red"})
    assert r.status_code == 400 and "#RRGGBB" in r.json()["detail"]
    r = admin.post(f"/api/v1/projects/{project_id}/classes", json={"name": "Crack"})
    assert r.json()["class"]["index"] == 3
    assert admin.post(f"/api/v1/projects/{project_id}/classes", json={"name": "crack"}).status_code == 400


def test_class_in_use_cannot_be_deleted(admin, ann, project_id, image_id):
    ann.post(f"/api/v1/images/{image_id}/lock")
    labels = np.zeros((48, 64), dtype=np.uint8)
    labels[0, 0] = 2
    put_labels(ann, image_id, labels, 0)
    classes = admin.get(f"/api/v1/projects/{project_id}").json()["project"]["classes"]
    pore = next(c for c in classes if c["index"] == 2)
    r = admin.delete(f"/api/v1/projects/{project_id}/classes/{pore['id']}")
    assert r.status_code == 409 and "Rename" in r.json()["detail"]
    renamed = admin.patch(f"/api/v1/projects/{project_id}/classes/{pore['id']}", json={"name": "Void"})
    assert renamed.json()["class"]["name"] == "Void"


def test_upload_dedup_and_rejects(ann, project_id):
    files = [("files", ("a.png", sample_image(seed=1), "image/png")),
             ("files", ("copy.png", sample_image(seed=1), "image/png")),
             ("files", ("notes.txt", b"hello", "text/plain")),
             ("files", ("broken.png", b"\x89PNG broken", "image/png"))]
    r = ann.post(f"/api/v1/projects/{project_id}/images", files=files).json()
    assert r["added"] == 1
    assert any("identical" in m for m in r["messages"])
    assert len(r["errors"]) == 2


def test_tiff_16bit_gets_display_copy(ann, project_id):
    arr = (np.arange(64 * 48, dtype=np.uint16).reshape(48, 64) * 20)
    buf = io.BytesIO()
    PILImage.fromarray(arr).save(buf, format="TIFF")
    r = ann.post(f"/api/v1/projects/{project_id}/images", files=[("files", ("scan_mask_01.tif", buf.getvalue(),
                                                                              "image/tiff"))]).json()
    assert r["added"] == 1, r
    img = ann.get(f"/api/v1/projects/{project_id}/images").json()["images"][0]
    assert img["stem"] == "scan-mask_01"  # "_mask" would confuse HydrideSegmentation pairing
    detail = ann.get(f"/api/v1/images/{img['id']}").json()["image"]
    assert "scaled to 8-bit" in detail["conversion_note"]
    disp = ann.get(detail["display_url"].replace("api/", "/api/", 1))
    assert disp.status_code == 200 and disp.content[:4] == b"\x89PNG"
    grey = ann.get(f"/api/v1/images/{img['id']}/grey")
    assert len(grey.content) == 64 * 48


def test_import_masks_binary_and_red(ann, project_id, image_id):
    binary = np.zeros((48, 64), dtype=np.uint8)
    binary[5:9, 5:9] = 255
    r = ann.post(f"/api/v1/projects/{project_id}/masks",
                 files=[("files", ("sample_one_mask.png", png_bytes(binary), "image/png"))]).json()
    assert r["errors"] == [] and "binary" in r["imported"][0]
    labels = get_labels(ann, image_id).reshape(48, 64)
    assert labels[6, 6] == 1 and labels.sum() == 16
    red = np.zeros((48, 64, 3), dtype=np.uint8)
    red[0:2, 0:2] = (230, 20, 10)
    r = ann.post(f"/api/v1/projects/{project_id}/masks", data={"import_class": "2"},
                 files=[("files", ("sample_one.png", png_bytes(red), "image/png"))]).json()
    assert "red-dominant" in r["imported"][0]
    assert get_labels(ann, image_id).reshape(48, 64)[0, 0] == 2
    wrong = ann.post(f"/api/v1/projects/{project_id}/masks",
                     files=[("files", ("unknown_mask.png", png_bytes(binary), "image/png"))]).json()
    assert "no image" in wrong["errors"][0]
    small = ann.post(f"/api/v1/projects/{project_id}/masks",
                     files=[("files", ("sample_one_mask.png", png_bytes(binary[:10]), "image/png"))]).json()
    assert "does not match" in small["errors"][0]


def test_bulk_split_assignment_needs_reviewer(ann, rev, project_id, image_id):
    body = {"image_ids": [image_id], "split": "val"}
    assert ann.post(f"/api/v1/projects/{project_id}/images/bulk", json=body).status_code == 403
    assert rev.post(f"/api/v1/projects/{project_id}/images/bulk", json=body).json()["updated"] == 1
    assert rev.get(f"/api/v1/images/{image_id}").json()["image"]["split"] == "val"


def test_delete_image_admin_only(admin, ann, image_id):
    assert ann.delete(f"/api/v1/images/{image_id}").status_code == 403
    assert admin.delete(f"/api/v1/images/{image_id}").status_code == 200
    assert admin.get(f"/api/v1/images/{image_id}").status_code == 404
