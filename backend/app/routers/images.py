from __future__ import annotations

import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.image import MicrographImage
from ..models.user import User
from ..schemas.image import AcquireLockResponse, MicrographImageResponse, ReleaseLockResponse
from ..services.auth_service import get_current_user
from ..services.ledger_service import record_ledger_event
from ..services.lock_service import acquire_or_renew_lock, get_lock_info, release_lock

router = APIRouter(prefix="/api/v1/images", tags=["images"])


@router.get("/{image_id}", response_model=MicrographImageResponse)
def get_image(image_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    img = db.query(MicrographImage).filter(MicrographImage.id == image_id).first()
    if not img:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")

    lock_info = get_lock_info(db, img.id, current_user.email)
    metadata = {}
    if img.metadata_json:
        try:
            metadata = json.loads(img.metadata_json)
        except Exception:
            pass

    return MicrographImageResponse(
        id=img.id,
        project_id=img.project_id,
        filename=img.filename,
        original_filename=img.original_filename,
        width=img.width,
        height=img.height,
        channels=img.channels,
        status=img.status,
        assigned_to=img.assigned_to,
        split_assignment=img.split_assignment,
        metadata=metadata,
        created_at=img.created_at,
        image_url=f"/api/v1/images/{img.id}/file",
        lock_info=lock_info,
    )


@router.get("/{image_id}/file")
def get_image_file(image_id: int, db: Session = Depends(get_db)):
    img = db.query(MicrographImage).filter(MicrographImage.id == image_id).first()
    if not img or not Path(img.file_path).exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image file not found.")

    # Determine media type
    ext = Path(img.file_path).suffix.lower()
    media_type = "image/png"
    if ext in [".jpg", ".jpeg"]:
        media_type = "image/jpeg"
    elif ext == ".tif" or ext == ".tiff":
        media_type = "image/tiff"

    return FileResponse(img.file_path, media_type=media_type)


@router.post("/{image_id}/lock", response_model=AcquireLockResponse)
def acquire_lock_endpoint(image_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    img = db.query(MicrographImage).filter(MicrographImage.id == image_id).first()
    if not img:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")

    success, msg, expires_at, lease_sec = acquire_or_renew_lock(db, image_id, current_user.email)
    if not success:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)

    # Set image to in_progress if currently unannotated
    if img.status == "unannotated":
        img.status = "in_progress"
        db.commit()

    record_ledger_event(db, "LOCK_ACQUIRED", current_user.email, f"Acquired lock on image {img.filename}", project_id=img.project_id, image_id=img.id)

    return AcquireLockResponse(
        success=True,
        message=msg,
        image_id=image_id,
        user_email=current_user.email,
        expires_at=expires_at,
        lease_seconds=lease_sec,
    )


@router.delete("/{image_id}/lock", response_model=ReleaseLockResponse)
def release_lock_endpoint(image_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    success, msg = release_lock(db, image_id, current_user.email, force=(current_user.role == "admin"))
    if not success:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)

    record_ledger_event(db, "LOCK_RELEASED", current_user.email, f"Released lock on image #{image_id}", image_id=image_id)
    return ReleaseLockResponse(success=True, message=msg)
