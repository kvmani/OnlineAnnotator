from __future__ import annotations

import pytest
from backend.app.models.image import MicrographImage
from backend.app.services.cv_service import rasterize_shapes_to_mask


def test_otsu_thresholding_api(client, admin_token, db):
    img = db.query(MicrographImage).first()
    image_id = img.id

    res = client.post(
        "/api/v1/tools/otsu-threshold",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "image_id": image_id,
            "invert": True,
            "blur_kernel": 3,
            "morphology_close": 2,
            "remove_small_speckles": 10,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "threshold_value" in data
    assert "contours" in data
    assert "mask_png_base64" in data
    assert data["mask_png_base64"].startswith("data:image/png;base64,")


def test_rasterize_shapes_to_mask():
    shapes = [
        {
            "id": "poly_1",
            "type": "polygon",
            "class_index": 1,
            "points": [[10, 10], [50, 10], [50, 50], [10, 50]],
            "closed": True,
        }
    ]
    # Test binary mode
    bin_mask = rasterize_shapes_to_mask(shapes, width=100, height=100, output_mode="binary", target_class=1)
    assert bin_mask.shape == (100, 100)
    assert bin_mask[25, 25] == 255
    assert bin_mask[5, 5] == 0

    # Test multiclass mode
    multi_mask = rasterize_shapes_to_mask(shapes, width=100, height=100, output_mode="multiclass")
    assert multi_mask.shape == (100, 100)
    assert multi_mask[25, 25] == 1
    assert multi_mask[5, 5] == 0
