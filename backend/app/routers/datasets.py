from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import List
import cv2
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ..config import get_config
from ..db import get_db
from ..models.dataset import DatasetClass, DatasetProject
from ..models.image import MicrographImage
from ..models.user import User
from ..schemas.dataset import (
    DatasetClassBase,
    DatasetClassResponse,
    DatasetProjectCreate,
    DatasetProjectDetailResponse,
    DatasetProjectSummaryResponse,
)
from ..schemas.image import ImageLockInfo, MicrographImageResponse
from ..services.auth_service import get_current_user, require_role
from ..services.ledger_service import record_ledger_event
from ..services.lock_service import get_lock_info

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("", response_model=List[DatasetProjectSummaryResponse])
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    projects = db.query(DatasetProject).all()
    results = []
    for p in projects:
        total = db.query(MicrographImage).filter(MicrographImage.project_id == p.id).count()
        annotated = db.query(MicrographImage).filter(MicrographImage.project_id == p.id, MicrographImage.status == "completed").count()
        in_progress = db.query(MicrographImage).filter(MicrographImage.project_id == p.id, MicrographImage.status == "in_progress").count()
        under_review = db.query(MicrographImage).filter(MicrographImage.project_id == p.id, MicrographImage.status == "under_review").count()

        results.append(
            DatasetProjectSummaryResponse(
                id=p.id,
                name=p.name,
                description=p.description,
                created_by=p.created_by,
                created_at=p.created_at,
                total_images=total,
                annotated_images=annotated,
                in_progress_images=in_progress,
                under_review_images=under_review,
            )
        )
    return results


@router.post("", response_model=DatasetProjectDetailResponse)
def create_project(
    payload: DatasetProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "lead_annotator")),
):
    existing = db.query(DatasetProject).filter(DatasetProject.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project with this name already exists.")

    project = DatasetProject(
        name=payload.name,
        description=payload.description,
        created_by=current_user.email,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # Classes
    classes_to_add = payload.classes
    if not classes_to_add:
        # Default microstructure classes
        config = get_config()
        classes_to_add = [
            DatasetClassBase(
                name=c.name,
                color_hex=c.color_hex,
                class_index=c.class_index,
                description=c.description,
                is_default=(c.class_index == 1),
            )
            for c in config.default_classes
        ]

    for c in classes_to_add:
        db.add(
            DatasetClass(
                project_id=project.id,
                name=c.name,
                color_hex=c.color_hex,
                class_index=c.class_index,
                description=c.description,
                is_default=c.is_default,
            )
        )
    db.commit()
    record_ledger_event(db, "PROJECT_CREATED", current_user.email, f"Project '{project.name}' created.", project_id=project.id)

    # Return detail
    classes = db.query(DatasetClass).filter(DatasetClass.project_id == project.id).order_by(DatasetClass.class_index).all()
    return DatasetProjectDetailResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        created_by=project.created_by,
        created_at=project.created_at,
        total_images=0,
        annotated_images=0,
        in_progress_images=0,
        under_review_images=0,
        classes=[DatasetClassResponse.model_validate(c) for c in classes],
    )


@router.get("/{project_id}", response_model=DatasetProjectDetailResponse)
def get_project_detail(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = db.query(DatasetProject).filter(DatasetProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    classes = db.query(DatasetClass).filter(DatasetClass.project_id == project.id).order_by(DatasetClass.class_index).all()
    total = db.query(MicrographImage).filter(MicrographImage.project_id == project.id).count()
    annotated = db.query(MicrographImage).filter(MicrographImage.project_id == project.id, MicrographImage.status == "completed").count()
    in_progress = db.query(MicrographImage).filter(MicrographImage.project_id == project.id, MicrographImage.status == "in_progress").count()
    under_review = db.query(MicrographImage).filter(MicrographImage.project_id == project.id, MicrographImage.status == "under_review").count()

    return DatasetProjectDetailResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        created_by=project.created_by,
        created_at=project.created_at,
        total_images=total,
        annotated_images=annotated,
        in_progress_images=in_progress,
        under_review_images=under_review,
        classes=[DatasetClassResponse.model_validate(c) for c in classes],
    )


@router.get("/{project_id}/images", response_model=List[MicrographImageResponse])
def list_project_images(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    images = db.query(MicrographImage).filter(MicrographImage.project_id == project_id).all()
    results = []
    for img in images:
        lock_info = get_lock_info(db, img.id, current_user.email)
        metadata = {}
        if img.metadata_json:
            try:
                metadata = json.loads(img.metadata_json)
            except Exception:
                pass

        results.append(
            MicrographImageResponse(
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
        )
    return results


@router.post("/{project_id}/images")
async def upload_images_to_project(
    project_id: int,
    files: List[UploadFile] = File(...),
    split_assignment: str = Form("train"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(DatasetProject).filter(DatasetProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    config = get_config()
    images_dir = Path(config.storage.images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)

    uploaded_count = 0
    for upload in files:
        if not upload.filename:
            continue

        raw_bytes = await upload.read()
        sha256 = hashlib.sha256(raw_bytes).hexdigest()

        # Check existing
        existing = db.query(MicrographImage).filter(MicrographImage.checksum_sha256 == sha256).first()
        if existing:
            continue

        filename = f"{sha256[:12]}_{upload.filename}"
        dest_path = images_dir / filename
        with open(dest_path, "wb") as f:
            f.write(raw_bytes)

        # Inspect dimensions with cv2
        cv_img = cv2.imread(str(dest_path))
        h, w = cv_img.shape[:2] if cv_img is not None else (512, 512)
        channels = cv_img.shape[2] if cv_img is not None else 3

        new_img = MicrographImage(
            project_id=project.id,
            filename=filename,
            original_filename=upload.filename,
            file_path=str(dest_path),
            width=w,
            height=h,
            channels=channels,
            checksum_sha256=sha256,
            status="unannotated",
            split_assignment=split_assignment,
        )
        db.add(new_img)
        uploaded_count += 1

    db.commit()
    record_ledger_event(db, "IMAGES_UPLOADED", current_user.email, f"Uploaded {uploaded_count} images to '{project.name}'.", project_id=project.id)

    return {"uploaded_count": uploaded_count, "message": f"Successfully uploaded {uploaded_count} image(s)."}
