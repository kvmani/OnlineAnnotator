from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class VectorShape(BaseModel):
    id: str
    type: str  # polygon, brush_stroke, rectangle
    class_index: int
    points: List[List[float]]  # [[x, y], [x, y], ...]
    color: Optional[str] = None
    stroke_width: Optional[float] = None
    closed: bool = True


class SaveDraftRequest(BaseModel):
    vector_data: List[Dict[str, Any]]
    mask_png_base64: Optional[str] = None  # Optional client-rendered canvas raster mask
    zoom_level: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0
    active_class_index: int = 1
    active_tool: str = "brush"
    brush_size: int = 10


class DraftResponse(BaseModel):
    image_id: int
    user_email: str
    vector_data: List[Dict[str, Any]]
    mask_url: Optional[str] = None
    zoom_level: float
    pan_x: float
    pan_y: float
    active_class_index: int
    active_tool: str
    brush_size: int
    updated_at: datetime


class CommitVersionRequest(BaseModel):
    vector_data: List[Dict[str, Any]]
    mask_png_base64: Optional[str] = None
    comment: Optional[str] = None
    submit_for_review: bool = True


class VersionResponse(BaseModel):
    id: int
    image_id: int
    version_number: int
    created_by: str
    status: str
    review_comment: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    mask_url: str
    model_config = ConfigDict(from_attributes=True)


class ReviewAnnotationRequest(BaseModel):
    action: str  # approve, reject
    comment: Optional[str] = None
