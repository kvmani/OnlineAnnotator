from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class OtsuThresholdRequest(BaseModel):
    image_id: int
    roi_bbox: Optional[List[int]] = Field(None, description="[x, y, width, height] for localized thresholding")
    invert: bool = Field(True, description="Default true for hydrides (dark features on bright background)")
    blur_kernel: int = Field(3, description="Gaussian blur kernel size (odd integer, 0 or 1 for no blur)")
    morphology_close: int = Field(2, description="Closing kernel size to bridge gaps")
    remove_small_speckles: int = Field(15, description="Min component area in pixels to keep")


class OtsuThresholdResponse(BaseModel):
    threshold_value: float
    contours: List[List[List[int]]]  # List of polygon point lists [[x, y], ...]
    mask_png_base64: str
    feature_count: int
    area_fraction: float


class AdaptiveThresholdRequest(BaseModel):
    image_id: int
    roi_bbox: Optional[List[int]] = None
    block_size: int = 15  # Must be odd > 1
    c_constant: int = 5
    invert: bool = True
    morphology_close: int = 2
    remove_small_speckles: int = 15
