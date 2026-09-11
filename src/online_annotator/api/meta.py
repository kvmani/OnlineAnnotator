"""Health, release identity and client configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from .._version import TOOL_ID, TOOL_NAME, __version__
from ..config import Settings
from ..db import get_db
from ..services.exports import yolo_available
from .deps import get_settings

router = APIRouter(tags=["meta"])


@router.get("/api/health")
@router.get("/health")
def health() -> dict:
    """Platform health contract (ml_server governance §6): cheap, no computation."""
    return {"status": "ok", "tool_id": TOOL_ID, "version": __version__}


@router.get("/api/health/deep")
def deep_health(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    db.execute(text("SELECT 1"))
    writable = settings.data_dir.exists() and settings.masks_dir.exists()
    return {"status": "ok" if writable else "degraded", "tool_id": TOOL_ID, "version": __version__,
            "database": "ok", "storage_writable": writable}


@router.get("/api/v1/meta")
def meta(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "tool_id": TOOL_ID, "name": TOOL_NAME, "version": __version__, "site_name": settings.site_name,
        "portal_url": settings.portal_url, "feedback_url": settings.feedback_url, "demo": settings.demo,
        "lock_lease_seconds": settings.lock_lease_seconds, "max_upload_mb": settings.max_upload_mb,
        "max_image_megapixels": settings.max_image_megapixels, "allow_self_approval": settings.allow_self_approval,
        "otp_login": settings.otp_login_enabled, "yolo_export": yolo_available(),
    }
