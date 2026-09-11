from __future__ import annotations

import logging
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import get_config
from ..db import get_db
from ..models.user import User
from ..schemas.export import DatasetExportRequest, DatasetExportResponse
from ..services.auth_service import get_current_user
from ..services.export_service import build_dataset_export
from ..services.ledger_service import record_ledger_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/export", tags=["export"])


@router.post("/{project_id}", response_model=DatasetExportResponse)
def export_dataset_endpoint(
    project_id: int,
    payload: DatasetExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = build_dataset_export(
            db=db,
            project_id=project_id,
            export_format=payload.format,
            mask_type=payload.mask_type,
            split_strategy=payload.split_strategy,
            train_pct=payload.train_pct,
            val_pct=payload.val_pct,
            test_pct=payload.test_pct,
            include_unreviewed=payload.include_unreviewed,
        )

        record_ledger_event(
            db,
            "DATASET_EXPORTED",
            current_user.email,
            f"Exported dataset for project #{project_id} ({result['total_images_exported']} images, format: {payload.format})",
            project_id=project_id,
            details=result["manifest"]["summary"],
        )

        return DatasetExportResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Dataset export failed: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Export failed: {str(e)}")


@router.get("/download/{filename}")
def download_export_file(filename: str):
    config = get_config()
    export_path = Path(config.storage.exports_dir) / filename
    if not export_path.exists() or not filename.endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export bundle file not found.")

    return FileResponse(
        str(export_path),
        media_type="application/zip",
        filename=filename,
    )
