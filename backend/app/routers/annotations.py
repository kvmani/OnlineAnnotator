from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import get_config
from ..db import get_db
from ..models.annotation import AnnotationDraft, AnnotationVersion
from ..models.image import MicrographImage
from ..models.user import User
from ..schemas.annotation import (
    CommitVersionRequest,
    DraftResponse,
    ReviewAnnotationRequest,
    SaveDraftRequest,
    VersionResponse,
)
from ..services.auth_service import get_current_user, require_role
from ..services.cv_service import rasterize_shapes_to_mask, save_b64_mask_to_file
from ..services.ledger_service import record_ledger_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/annotations", tags=["annotations"])


@router.get("/{image_id}/draft", response_model=DraftResponse)
def get_draft(image_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    draft = db.query(AnnotationDraft).filter(AnnotationDraft.image_id == image_id).first()
    if not draft:
        # Return empty draft
        return DraftResponse(
            image_id=image_id,
            user_email=current_user.email,
            vector_data=[],
            mask_url=None,
            zoom_level=1.0,
            pan_x=0.0,
            pan_y=0.0,
            active_class_index=1,
            active_tool="brush",
            brush_size=10,
            updated_at=datetime.now(timezone.utc),
        )

    vector_shapes = []
    if draft.vector_data:
        try:
            vector_shapes = json.loads(draft.vector_data)
        except Exception:
            vector_shapes = []

    mask_url = f"/api/v1/annotations/{image_id}/mask" if draft.mask_path and Path(draft.mask_path).exists() else None

    return DraftResponse(
        image_id=draft.image_id,
        user_email=draft.user_email,
        vector_data=vector_shapes,
        mask_url=mask_url,
        zoom_level=draft.zoom_level,
        pan_x=draft.pan_x,
        pan_y=draft.pan_y,
        active_class_index=draft.active_class_index,
        active_tool=draft.active_tool,
        brush_size=draft.brush_size,
        updated_at=draft.updated_at,
    )


@router.post("/{image_id}/draft", response_model=DraftResponse)
def save_draft(
    image_id: int,
    payload: SaveDraftRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    img = db.query(MicrographImage).filter(MicrographImage.id == image_id).first()
    if not img:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")

    config = get_config()
    masks_dir = Path(config.storage.masks_dir)
    masks_dir.mkdir(parents=True, exist_ok=True)

    mask_path = masks_dir / f"draft_{image_id}.png"

    # Save mask either from client canvas base64 or server-side rasterization
    if payload.mask_png_base64:
        save_b64_mask_to_file(payload.mask_png_base64, str(mask_path))
    else:
        # Server-side rasterize
        w = img.width if img.width > 0 else 512
        h = img.height if img.height > 0 else 512
        mask_np = rasterize_shapes_to_mask(payload.vector_data, width=w, height=h, output_mode="multiclass")
        cv2.imwrite(str(mask_path), mask_np)

    draft = db.query(AnnotationDraft).filter(AnnotationDraft.image_id == image_id).first()
    vector_json = json.dumps(payload.vector_data)

    if not draft:
        draft = AnnotationDraft(
            image_id=image_id,
            user_email=current_user.email,
            vector_data=vector_json,
            mask_path=str(mask_path),
            zoom_level=payload.zoom_level,
            pan_x=payload.pan_x,
            pan_y=payload.pan_y,
            active_class_index=payload.active_class_index,
            active_tool=payload.active_tool,
            brush_size=payload.brush_size,
        )
        db.add(draft)
    else:
        draft.user_email = current_user.email
        draft.vector_data = vector_json
        draft.mask_path = str(mask_path)
        draft.zoom_level = payload.zoom_level
        draft.pan_x = payload.pan_x
        draft.pan_y = payload.pan_y
        draft.active_class_index = payload.active_class_index
        draft.active_tool = payload.active_tool
        draft.brush_size = payload.brush_size

    if img.status == "unannotated":
        img.status = "in_progress"

    db.commit()
    db.refresh(draft)

    record_ledger_event(
        db,
        "DRAFT_SAVED",
        current_user.email,
        f"Saved annotation draft for {img.filename} ({len(payload.vector_data)} shapes)",
        project_id=img.project_id,
        image_id=img.id,
    )

    return DraftResponse(
        image_id=draft.image_id,
        user_email=draft.user_email,
        vector_data=payload.vector_data,
        mask_url=f"/api/v1/annotations/{image_id}/mask",
        zoom_level=draft.zoom_level,
        pan_x=draft.pan_x,
        pan_y=draft.pan_y,
        active_class_index=draft.active_class_index,
        active_tool=draft.active_tool,
        brush_size=draft.brush_size,
        updated_at=draft.updated_at,
    )


@router.post("/{image_id}/commit", response_model=VersionResponse)
def commit_version(
    image_id: int,
    payload: CommitVersionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    img = db.query(MicrographImage).filter(MicrographImage.id == image_id).first()
    if not img:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")

    config = get_config()
    masks_dir = Path(config.storage.masks_dir)
    masks_dir.mkdir(parents=True, exist_ok=True)

    # Next version number
    last_version = (
        db.query(AnnotationVersion)
        .filter(AnnotationVersion.image_id == image_id)
        .order_by(AnnotationVersion.version_number.desc())
        .first()
    )
    next_ver = (last_version.version_number + 1) if last_version else 1

    mask_filename = f"mask_img{image_id}_v{next_ver}.png"
    mask_path = masks_dir / mask_filename

    if payload.mask_png_base64:
        save_b64_mask_to_file(payload.mask_png_base64, str(mask_path))
    else:
        w = img.width if img.width > 0 else 512
        h = img.height if img.height > 0 else 512
        mask_np = rasterize_shapes_to_mask(payload.vector_data, width=w, height=h, output_mode="multiclass")
        cv2.imwrite(str(mask_path), mask_np)

    ver_status = "submitted_for_review" if payload.submit_for_review else "draft"
    if payload.submit_for_review:
        img.status = "under_review"

    version = AnnotationVersion(
        image_id=image_id,
        version_number=next_ver,
        created_by=current_user.email,
        vector_data=json.dumps(payload.vector_data),
        mask_path=str(mask_path),
        status=ver_status,
        review_comment=payload.comment,
    )
    db.add(version)
    db.commit()
    db.refresh(version)

    record_ledger_event(
        db,
        "VERSION_COMMITTED",
        current_user.email,
        f"Committed v{next_ver} for {img.filename} (Status: {ver_status})",
        project_id=img.project_id,
        image_id=img.id,
    )

    return VersionResponse(
        id=version.id,
        image_id=version.image_id,
        version_number=version.version_number,
        created_by=version.created_by,
        status=version.status,
        review_comment=version.review_comment,
        reviewed_by=version.reviewed_by,
        reviewed_at=version.reviewed_at,
        created_at=version.created_at,
        mask_url=f"/api/v1/annotations/{image_id}/mask?v={version.version_number}",
    )


@router.get("/{image_id}/versions", response_model=List[VersionResponse])
def list_versions(image_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    versions = (
        db.query(AnnotationVersion)
        .filter(AnnotationVersion.image_id == image_id)
        .order_by(AnnotationVersion.version_number.desc())
        .all()
    )
    return [
        VersionResponse(
            id=v.id,
            image_id=v.image_id,
            version_number=v.version_number,
            created_by=v.created_by,
            status=v.status,
            review_comment=v.review_comment,
            reviewed_by=v.reviewed_by,
            reviewed_at=v.reviewed_at,
            created_at=v.created_at,
            mask_url=f"/api/v1/annotations/{image_id}/mask?v={v.version_number}",
        )
        for v in versions
    ]


@router.post("/{image_id}/restore/{version_id}", response_model=DraftResponse)
def restore_version_to_draft(
    image_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    version = db.query(AnnotationVersion).filter(AnnotationVersion.id == version_id, AnnotationVersion.image_id == image_id).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")

    draft = db.query(AnnotationDraft).filter(AnnotationDraft.image_id == image_id).first()
    if not draft:
        draft = AnnotationDraft(
            image_id=image_id,
            user_email=current_user.email,
            vector_data=version.vector_data,
            mask_path=version.mask_path,
        )
        db.add(draft)
    else:
        draft.user_email = current_user.email
        draft.vector_data = version.vector_data
        draft.mask_path = version.mask_path

    db.commit()
    db.refresh(draft)

    shapes = json.loads(draft.vector_data) if draft.vector_data else []
    record_ledger_event(
        db,
        "VERSION_RESTORED",
        current_user.email,
        f"Restored v{version.version_number} as draft for image #{image_id}",
        image_id=image_id,
    )

    return DraftResponse(
        image_id=draft.image_id,
        user_email=draft.user_email,
        vector_data=shapes,
        mask_url=f"/api/v1/annotations/{image_id}/mask",
        zoom_level=draft.zoom_level,
        pan_x=draft.pan_x,
        pan_y=draft.pan_y,
        active_class_index=draft.active_class_index,
        active_tool=draft.active_tool,
        brush_size=draft.brush_size,
        updated_at=draft.updated_at,
    )


@router.post("/{image_id}/review")
def review_annotation(
    image_id: int,
    payload: ReviewAnnotationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "lead_annotator", "reviewer")),
):
    img = db.query(MicrographImage).filter(MicrographImage.id == image_id).first()
    if not img:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")

    latest_ver = (
        db.query(AnnotationVersion)
        .filter(AnnotationVersion.image_id == image_id)
        .order_by(AnnotationVersion.version_number.desc())
        .first()
    )
    if not latest_ver:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No submitted versions to review.")

    now = datetime.now(timezone.utc)
    if payload.action == "approve":
        latest_ver.status = "approved"
        latest_ver.reviewed_by = current_user.email
        latest_ver.reviewed_at = now
        latest_ver.review_comment = payload.comment
        img.status = "completed"
        db.commit()
        record_ledger_event(db, "ANNOTATION_APPROVED", current_user.email, f"Approved annotation for {img.filename}", project_id=img.project_id, image_id=img.id)
        return {"message": "Annotation approved successfully.", "status": "completed"}
    elif payload.action == "reject":
        latest_ver.status = "rejected"
        latest_ver.reviewed_by = current_user.email
        latest_ver.reviewed_at = now
        latest_ver.review_comment = payload.comment
        img.status = "in_progress"
        db.commit()
        record_ledger_event(db, "ANNOTATION_REJECTED", current_user.email, f"Rejected annotation for {img.filename}: {payload.comment}", project_id=img.project_id, image_id=img.id)
        return {"message": "Annotation returned for revisions.", "status": "in_progress"}
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid review action. Must be 'approve' or 'reject'.")


@router.get("/{image_id}/mask")
def get_mask_png(
    image_id: int,
    v: Optional[int] = None,
    format: str = "binary",
    db: Session = Depends(get_db),
):
    """Serve the raster mask PNG for inspection or download."""
    img = db.query(MicrographImage).filter(MicrographImage.id == image_id).first()
    if not img:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")

    target_mask_path = None
    if v is not None:
        version = db.query(AnnotationVersion).filter(AnnotationVersion.image_id == image_id, AnnotationVersion.version_number == v).first()
        if version and version.mask_path and Path(version.mask_path).exists():
            target_mask_path = version.mask_path
    else:
        draft = db.query(AnnotationDraft).filter(AnnotationDraft.image_id == image_id).first()
        if draft and draft.mask_path and Path(draft.mask_path).exists():
            target_mask_path = draft.mask_path

    if not target_mask_path or not Path(target_mask_path).exists():
        # Generate on the fly
        w = img.width if img.width > 0 else 512
        h = img.height if img.height > 0 else 512
        empty_mask = np.zeros((h, w), dtype=np.uint8)
        success, buffer = cv2.imencode(".png", empty_mask)
        return Response(content=buffer.tobytes(), media_type="image/png")

    return FileResponse(target_mask_path, media_type="image/png")
