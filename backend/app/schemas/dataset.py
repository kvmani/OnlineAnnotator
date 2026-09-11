from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class DatasetClassBase(BaseModel):
    name: str
    color_hex: str = Field(..., pattern="^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")
    class_index: int
    description: Optional[str] = None
    is_default: bool = False


class DatasetClassCreate(DatasetClassBase):
    pass


class DatasetClassResponse(DatasetClassBase):
    id: int
    project_id: int
    model_config = ConfigDict(from_attributes=True)


class DatasetProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    classes: Optional[List[DatasetClassBase]] = None


class DatasetProjectSummaryResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    created_by: str
    created_at: datetime
    total_images: int = 0
    annotated_images: int = 0
    in_progress_images: int = 0
    under_review_images: int = 0
    model_config = ConfigDict(from_attributes=True)


class DatasetProjectDetailResponse(DatasetProjectSummaryResponse):
    classes: List[DatasetClassResponse] = []
