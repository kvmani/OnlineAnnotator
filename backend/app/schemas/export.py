from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class DatasetExportRequest(BaseModel):
    format: str = Field("hydride_paired", description="Format: hydride_paired, coco, yolo, numpy, zip")
    mask_type: str = Field("binary", description="binary, rgb, multiclass")
    split_strategy: str = Field("custom", description="custom, random")
    train_pct: float = 0.8
    val_pct: float = 0.1
    test_pct: float = 0.1
    include_unreviewed: bool = False


class DatasetExportResponse(BaseModel):
    export_id: str
    download_url: str
    filename: str
    format: str
    total_images_exported: int
    train_count: int
    val_count: int
    test_count: int
    file_size_bytes: int
    manifest: Dict
