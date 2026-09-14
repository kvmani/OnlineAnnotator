from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import pytest
from PIL import Image as PILImage

from online_annotator.services.exports import _rle, yolo_available

from .conftest import annotate_and_submit, put_labels, review, sample_image, set_mode

W, H = 64, 48


def approve(author, reviewer, image_id, labels):
    """``author`` annotates and submits; ``reviewer`` switches to Review mode and approves."""
    annotate_and_submit(author, image_id, labels)
    set_mode(reviewer, "review")
    assert review(reviewer, image_id).status_code == 200


def labels_a():
    arr = np.zeros((H, W), dtype=np.uint8)
    arr[10:14, 5:50] = 1
    arr[30:34, 30:34] = 2
    return arr


def read_zip(client, export):
    r = client.get("/" + export["download_url"])
    assert r.status_code == 200
    return zipfile.ZipFile(io.BytesIO(r.content))


def test_nothing_approved_means_clear_error(bob, project_id, image_id):
    preview = bob.post(f"/api/v1/projects/{project_id}/exports/preview", json={}).json()
    assert preview["image_count"] == 0 and preview["warnings"]
    r = bob.post(f"/api/v1/projects/{project_id}/exports", json={})
    assert r.status_code == 400 and "Nothing to export" in r.json()["detail"]


def test_hydride_pairs_binary_export_is_exact(alice, bob, project_id, image_id):
    approve(alice, bob, image_id, labels_a())
    # A second, unapproved image must not leak into the export.
    alice.post(f"/api/v1/projects/{project_id}/images", files=[("files", ("b.png", sample_image(seed=5), "image/png"))])
    preview = bob.post(f"/api/v1/projects/{project_id}/exports/preview", json={}).json()
    assert preview["image_count"] == 1 and preview["skipped"]["no_annotation"] == 1

    export = bob.post(f"/api/v1/projects/{project_id}/exports", json={"layout": "hydride_pairs",
                                                                        "mask_style": "binary"}).json()["export"]
    zf = read_zip(bob, export)
    names = set(zf.namelist())
    assert {"pairs/sample_one.png", "pairs/sample_one_mask.png", "manifest.json", "README.txt",
            "coco_annotations.json"} <= names
    mask = np.asarray(PILImage.open(io.BytesIO(zf.read("pairs/sample_one_mask.png"))))
    assert mask.dtype == np.uint8 and set(np.unique(mask)) == {0, 255}
    np.testing.assert_array_equal(mask == 255, labels_a() == 1)
    manifest = json.loads(zf.read("manifest.json"))
    rec = manifest["images"][0]
    assert manifest["schema"] == "online-annotator.export/1"
    assert rec["approved_by"] == "bob@lab.test" and rec["annotated_by"] == "alice@lab.test"
    assert rec["class_pixels"] == {"1": 180, "2": 16}
    assert rec["contributors"] == ["alice@lab.test"]
    assert rec["approved_at"].endswith("+00:00") and rec["approved_at"] >= rec["annotated_at"]
    listed = bob.get(f"/api/v1/projects/{project_id}/exports").json()["exports"]
    assert listed[0]["image_count"] == 1
    summary = bob.get(f"/api/v1/projects/{project_id}/summary").json()
    assert summary["approved_pixels"] == W * H and summary["class_fractions"]["1"] == 180 / (W * H)


def test_split_folders_indexed_auto_split_and_coco_rle(alice, bob, project_id, image_id):
    approve(alice, bob, image_id, labels_a())
    export = bob.post(f"/api/v1/projects/{project_id}/exports", json={
        "layout": "split_folders", "mask_style": "indexed", "split_mode": "auto", "train": 1, "val": 0,
        "test": 0}).json()["export"]
    zf = read_zip(bob, export)
    mask = np.asarray(PILImage.open(io.BytesIO(zf.read("train/masks/sample_one_mask.png"))))
    np.testing.assert_array_equal(mask, labels_a())
    coco = json.loads(zf.read("coco_annotations.json"))
    assert {a["category_id"] for a in coco["annotations"]} == {1, 2}
    ann1 = next(a for a in coco["annotations"] if a["category_id"] == 1)
    assert ann1["area"] == 180 and ann1["bbox"] == [5, 10, 45, 4]
    # Decode RLE and compare exactly.
    counts, flat, val = ann1["segmentation"]["counts"], [], 0
    for c in counts:
        flat.extend([val] * c)
        val ^= 1
    decoded = np.array(flat, dtype=np.uint8).reshape((W, H)).T
    np.testing.assert_array_equal(decoded, (labels_a() == 1).astype(np.uint8))


def test_red_style_matches_hydride_rgb_rule(alice, bob, project_id, image_id):
    approve(alice, bob, image_id, labels_a())
    export = bob.post(f"/api/v1/projects/{project_id}/exports", json={"mask_style": "red",
                                                                        "include_coco": False}).json()["export"]
    zf = read_zip(bob, export)
    rgb = np.asarray(PILImage.open(io.BytesIO(zf.read("pairs/sample_one_mask.png"))).convert("RGB"))
    red = (rgb[:, :, 0] >= 200) & (rgb[:, :, 1] <= 60) & (rgb[:, :, 2] <= 60)
    np.testing.assert_array_equal(red, labels_a() == 1)
    assert "coco_annotations.json" not in zf.namelist()


def test_unreviewed_only_when_asked(alice, bob, project_id, image_id):
    alice.post(f"/api/v1/images/{image_id}/lock")
    put_labels(alice, image_id, labels_a(), 0)
    alice.post(f"/api/v1/images/{image_id}/submit", json={})
    assert bob.post(f"/api/v1/projects/{project_id}/exports/preview", json={}).json()["image_count"] == 0
    preview = bob.post(f"/api/v1/projects/{project_id}/exports/preview",
                       json={"include": "approved_and_submitted"}).json()
    assert preview["image_count"] == 1 and any("not yet reviewed" in w for w in preview["warnings"])


def test_every_user_can_export_in_either_mode(alice, bob, project_id, image_id):
    approve(alice, bob, image_id, labels_a())
    assert alice.post(f"/api/v1/projects/{project_id}/exports", json={}).status_code == 200  # Annotate mode
    assert bob.post(f"/api/v1/projects/{project_id}/exports", json={}).status_code == 200  # Review mode


@pytest.mark.skipif(not yolo_available(), reason="OpenCV not installed")
def test_yolo_polygons(alice, bob, project_id, image_id):
    approve(alice, bob, image_id, labels_a())
    export = bob.post(f"/api/v1/projects/{project_id}/exports", json={"include_yolo": True}).json()["export"]
    zf = read_zip(bob, export)
    lines = zf.read("pairs_yolo/sample_one.txt").decode().strip().splitlines()
    assert {line.split()[0] for line in lines} == {"0", "1"}
    assert "names:" in zf.read("yolo_data.yaml").decode()


def test_rle_starts_with_zero_run_when_first_pixel_set():
    mask = np.array([[1, 0], [1, 1]], dtype=np.uint8)
    assert _rle(mask)["counts"] == [0, 2, 1, 1]
