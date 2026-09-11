from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict


class ImageLockInfo(BaseModel):
    is_locked: bool
    locked_by: Optional[str] = None
    locked_by_me: bool = False
    expires_at: Optional[datetime] = None
    seconds_remaining: Optional[int] = None


class MicrographImageResponse(BaseModel):
    id: int
    project_id: int
    filename: str
    original_filename: str
    width: int
    height: int
    channels: int
    status: str
    assigned_to: Optional[str] = None
    split_assignment: str
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    image_url: str
    lock_info: ImageLockInfo
    model_config = ConfigDict(from_attributes=True)


class AcquireLockResponse(BaseModel):
    success: bool
    message: str
    image_id: int
    user_email: str
    expires_at: datetime
    lease_seconds: int


class ReleaseLockResponse(BaseModel):
    success: bool
    message: str
