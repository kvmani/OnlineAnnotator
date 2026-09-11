from __future__ import annotations

import io
import json
import logging
import os
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import cv2
import numpy as np
from sqlalchemy.orm import Session

from ..config import get_config
from ..models.annotation import AnnotationDraft, AnnotationVersion
from ..models.dataset import DatasetClass, DatasetProject
from ..models.image import MicrographImage
from .cv_service import rasterize_shapes_to_mask

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_dataset_export(
    db: Session,
    project_id: int,
    export_format: str = "hydride_paired",
    mask_type: str = "binary",
    split_strategy: str = "custom",
    train_pct: float = 0.8,
    val_pct: float = 0.1,
    test_pct: float = 0.1,
    include_unreviewed: bool = False,
) -> Dict[str, Any]:
    """
    Generate an ML-ready dataset package for semantic segmentation workflows.
    Matches HydrideSegmentation paired folder standards.
    """
    config = get_config()
    project = db.query(DatasetProject).filter(DatasetProject.id == project_id).first()
    if not project:
        raise ValueError(f"Project ID {project_id} not found.")

    classes = db.query(DatasetClass).filter(DatasetClass.project_id == project_id).order_by(DatasetClass.class_index).all()
    class_map = {c.class_index: c.name for c in classes}
    class_map[0] = "Background"

    # Query images
    image_query = db.query(MicrographImage).filter(MicrographImage.project_id == project_id)
    if not include_unreviewed:
        # Include completed or under_review or images having drafts
        image_query = image_query.filter(MicrographImage.status.in_(["completed", "under_review", "in_progress"]))
    images = image_query.all()

    if not images:
        # Fallback to all images if none have completed status yet
        images = db.query(MicrographImage).filter(MicrographImage.project_id == project_id).all()

    export_uuid = uuid.uuid4().hex[:12]
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_dirname = f"{project.name.lower().replace(' ', '_')}_{export_format}_{timestamp_str}_{export_uuid}"
    temp_export_dir = Path(config.storage.exports_dir) / export_dirname
    temp_export_dir.mkdir(parents=True, exist_ok=True)

    # Prepare split assignment
    rng = np.random.default_rng(42)
    splits = ["train", "val", "test"]
    split_probs = np.array([train_pct, val_pct, test_pct])
    split_probs = split_probs / split_probs.sum()

    for s in splits:
        (temp_export_dir / s / "images").mkdir(parents=True, exist_ok=True)
        (temp_export_dir / s / "masks").mkdir(parents=True, exist_ok=True)

    manifest_images = []
    total_features_count = 0
    area_fractions = []
    coco_images = []
    coco_annotations = []
    coco_categories = [{"id": idx, "name": name, "supercategory": "microstructure"} for idx, name in class_map.items() if idx > 0]
    coco_ann_id = 1

    train_count = 0
    val_count = 0
    test_count = 0

    for i, img in enumerate(images):
        # Determine split
        if split_strategy == "random":
            assigned_split = str(rng.choice(splits, p=split_probs))
        else:
            assigned_split = img.split_assignment or "train"

        if assigned_split == "train":
            train_count += 1
        elif assigned_split == "val":
            val_count += 1
        else:
            test_count += 1

        # Retrieve best available annotation (approved version > latest version > draft)
        latest_ver = (
            db.query(AnnotationVersion)
            .filter(AnnotationVersion.image_id == img.id)
            .order_by(AnnotationVersion.version_number.desc())
            .first()
        )
        draft = db.query(AnnotationDraft).filter(AnnotationDraft.image_id == img.id).first()

        shapes = []
        if latest_ver and latest_ver.vector_data:
            try:
                shapes = json.loads(latest_ver.vector_data)
            except Exception:
                shapes = []
        elif draft and draft.vector_data:
            try:
                shapes = json.loads(draft.vector_data)
            except Exception:
                shapes = []

        # Rasterize mask
        h, w = img.height, img.width
        if h <= 0 or w <= 0:
            # Inspect image from disk to get dimensions
            actual_img = cv2.imread(img.file_path)
            if actual_img is not None:
                h, w = actual_img.shape[:2]
            else:
                h, w = 512, 512

        output_mode = "binary"
        if mask_type == "rgb":
            output_mode = "rgb_red_dominant"
        elif mask_type == "multiclass":
            output_mode = "multiclass"

        mask = rasterize_shapes_to_mask(shapes, width=w, height=h, output_mode=output_mode, target_class=1)

        # Compute image stats
        if output_mode == "rgb_red_dominant":
            fg_pixels = np.count_nonzero((mask[:, :, 2] >= 200) & (mask[:, :, 1] <= 60))
        else:
            fg_pixels = np.count_nonzero(mask > 0)
        area_frac = float(fg_pixels) / float(h * w)
        area_fractions.append(area_frac)
        total_features_count += len(shapes)

        # File names
        stem = Path(img.filename).stem
        image_dest_name = f"{stem}.png"
        mask_dest_name = f"{stem}_mask.png"

        # Copy image file
        dest_img_path = temp_export_dir / assigned_split / "images" / image_dest_name
        dest_mask_path = temp_export_dir / assigned_split / "masks" / mask_dest_name

        if Path(img.file_path).exists():
            shutil.copy2(img.file_path, dest_img_path)
        else:
            # Generate blank placeholder if file missing
            dummy = np.zeros((h, w, 3), dtype=np.uint8)
            cv2.imwrite(str(dest_img_path), dummy)

        # Save mask file
        cv2.imwrite(str(dest_mask_path), mask)

        # COCO entries
        coco_images.append({
            "id": img.id,
            "file_name": f"{assigned_split}/images/{image_dest_name}",
            "width": w,
            "height": h,
        })

        for s in shapes:
            pts = s.get("points", [])
            c_idx = int(s.get("class_index", 1))
            if len(pts) >= 3 and c_idx > 0:
                flat_pts = [coord for pt in pts for coord in pt]
                xs = [pt[0] for pt in pts]
                ys = [pt[1] for pt in pts]
                bx, by, bw, bh = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
                coco_annotations.append({
                    "id": coco_ann_id,
                    "image_id": img.id,
                    "category_id": c_idx,
                    "segmentation": [flat_pts],
                    "area": float(bw * bh),
                    "bbox": [float(bx), float(by), float(bw), float(bh)],
                    "iscrowd": 0,
                })
                coco_ann_id += 1

        # YOLO entries (saved in split/labels/ if requested)
        if export_format in ["yolo", "zip"]:
            labels_dir = temp_export_dir / assigned_split / "labels"
            labels_dir.mkdir(parents=True, exist_ok=True)
            yolo_txt_path = labels_dir / f"{stem}.txt"
            with open(yolo_txt_path, "w", encoding="utf-8") as yf:
                for s in shapes:
                    pts = s.get("points", [])
                    c_idx = max(0, int(s.get("class_index", 1)) - 1)  # 0-indexed for YOLO
                    if len(pts) >= 3:
                        norm_coords = [f"{pt[0] / w:.6f} {pt[1] / h:.6f}" for pt in pts]
                        yf.write(f"{c_idx} {' '.join(norm_coords)}\n")

        manifest_images.append({
            "image_id": img.id,
            "filename": image_dest_name,
            "mask_filename": mask_dest_name,
            "split": assigned_split,
            "width": w,
            "height": h,
            "hydride_area_fraction": round(area_frac, 5),
            "feature_count": len(shapes),
        })

    # Build manifest
    manifest = {
        "dataset_name": project.name,
        "export_format": export_format,
        "mask_type": mask_type,
        "generated_at": _utcnow_iso(),
        "application_target": "HydrideSegmentation",
        "classes": class_map,
        "summary": {
            "total_images": len(images),
            "train_count": train_count,
            "val_count": val_count,
            "test_count": test_count,
            "total_features": total_features_count,
            "mean_area_fraction": round(float(np.mean(area_fractions)) if area_fractions else 0.0, 5),
        },
        "images": manifest_images,
    }

    # Save manifest.json
    with open(temp_export_dir / "dataset_manifest.json", "w", encoding="utf-8") as mf:
        json.dump(manifest, mf, indent=2)

    # Save COCO JSON
    coco_data = {
        "info": {
            "description": f"{project.name} Microstructure Segmentation Dataset",
            "date_created": _utcnow_iso(),
        },
        "categories": coco_categories,
        "images": coco_images,
        "annotations": coco_annotations,
    }
    with open(temp_export_dir / "coco_annotations.json", "w", encoding="utf-8") as cf:
        json.dump(coco_data, cf, indent=2)

    # Create ZIP archive
    zip_filename = f"{export_dirname}.zip"
    zip_filepath = Path(config.storage.exports_dir) / zip_filename

    with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(temp_export_dir):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(temp_export_dir)
                zf.write(full_path, arcname=str(rel_path))

    # Clean up temp folder
    shutil.rmtree(temp_export_dir, ignore_errors=True)

    file_size = zip_filepath.stat().st_size

    return {
        "export_id": export_uuid,
        "download_url": f"/api/v1/export/download/{zip_filename}",
        "filename": zip_filename,
        "format": export_format,
        "total_images_exported": len(images),
        "train_count": train_count,
        "val_count": val_count,
        "test_count": test_count,
        "file_size_bytes": file_size,
        "manifest": manifest,
    }
