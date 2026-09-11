from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.image import MicrographImage
from ..models.user import User
from ..schemas.tools import AdaptiveThresholdRequest, OtsuThresholdRequest, OtsuThresholdResponse
from ..services.auth_service import get_current_user
from ..services.cv_service import run_adaptive_threshold, run_otsu_threshold

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


@router.post("/otsu-threshold", response_model=OtsuThresholdResponse)
def otsu_threshold_endpoint(
    payload: OtsuThresholdRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    img = db.query(MicrographImage).filter(MicrographImage.id == payload.image_id).first()
    if not img or not Path(img.file_path).exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image file not found.")

    try:
        result = run_otsu_threshold(
            image_path=img.file_path,
            roi_bbox=payload.roi_bbox,
            invert=payload.invert,
            blur_kernel=payload.blur_kernel,
            morphology_close=payload.morphology_close,
            remove_small_speckles=payload.remove_small_speckles,
        )
        return OtsuThresholdResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/adaptive-threshold", response_model=OtsuThresholdResponse)
def adaptive_threshold_endpoint(
    payload: AdaptiveThresholdRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    img = db.query(MicrographImage).filter(MicrographImage.id == payload.image_id).first()
    if not img or not Path(img.file_path).exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image file not found.")

    try:
        result = run_adaptive_threshold(
            image_path=img.file_path,
            roi_bbox=payload.roi_bbox,
            block_size=payload.block_size,
            c_constant=payload.c_constant,
            invert=payload.invert,
            morphology_close=payload.morphology_close,
            remove_small_speckles=payload.remove_small_speckles,
        )
        return OtsuThresholdResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
