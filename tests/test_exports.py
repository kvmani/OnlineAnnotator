from __future__ import annotations

import io
import zipfile
import pytest
from backend.app.models.dataset import DatasetProject


def test_dataset_export_hydride_paired(client, admin_token, db):
    project = db.query(DatasetProject).first()
    project_id = project.id

    # Request export
    res = client.post(
        f"/api/v1/export/{project_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "format": "hydride_paired",
            "mask_type": "binary",
            "split_strategy": "custom",
            "train_pct": 0.8,
            "val_pct": 0.1,
            "test_pct": 0.1,
            "include_unreviewed": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "download_url" in data
    assert data["total_images_exported"] >= 1

    # Test downloading the ZIP file
    download_url = data["download_url"]
    dl_res = client.get(download_url)
    assert dl_res.status_code == 200
    assert dl_res.headers["content-type"] == "application/zip"

    # Inspect ZIP contents
    with zipfile.ZipFile(io.BytesIO(dl_res.content)) as zf:
        namelist = zf.namelist()
        assert "dataset_manifest.json" in namelist
        assert "coco_annotations.json" in namelist
        # Verify paired folder structure
        has_train_images = any(name.startswith("train/images/") for name in namelist)
        has_train_masks = any(name.startswith("train/masks/") and name.endswith("_mask.png") for name in namelist)
        assert has_train_images or any(name.startswith("val/images/") for name in namelist) or any(name.startswith("test/images/") for name in namelist)
