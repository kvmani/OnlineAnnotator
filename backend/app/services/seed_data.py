from __future__ import annotations

import hashlib
import logging
import os
import shutil
from pathlib import Path
import cv2
import numpy as np
from sqlalchemy.orm import Session

from ..config import get_config
from ..models.annotation import AnnotationDraft
from ..models.dataset import DatasetClass, DatasetProject
from ..models.image import MicrographImage
from ..models.user import Role, User
from .auth_service import get_password_hash
from .cv_service import run_otsu_threshold
from .ledger_service import record_ledger_event

logger = logging.getLogger(__name__)


def compute_file_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def create_synthetic_microstructure(filepath: str, width: int = 512, height: int = 512) -> None:
    """Generate a realistic synthetic zirconium microstructure with hydride platelets."""
    # Light gray matrix
    img = np.full((height, width, 3), 210, dtype=np.uint8)
    # Add subtle grain texture noise
    noise = np.random.normal(0, 8, (height, width, 3)).astype(np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    # Draw dark elongated hydride platelets
    rng = np.random.default_rng(1234)
    for _ in range(35):
        cx = int(rng.integers(30, width - 30))
        cy = int(rng.integers(30, height - 30))
        length = int(rng.integers(40, 140))
        angle_deg = float(rng.normal(15, 20))  # Orient roughly near horizontal
        rad = np.radians(angle_deg)
        x1 = int(cx - (length // 2) * np.cos(rad))
        y1 = int(cy - (length // 2) * np.sin(rad))
        x2 = int(cx + (length // 2) * np.cos(rad))
        y2 = int(cy + (length // 2) * np.sin(rad))
        thickness = int(rng.integers(2, 6))
        # Dark gray/black hydride color
        cv2.line(img, (x1, y1), (x2, y2), (40, 40, 40), thickness)

    cv2.imwrite(filepath, img)


def seed_database(db: Session) -> None:
    config = get_config()

    # 1. Seed Roles
    roles = [
        ("admin", "Full system administrator"),
        ("lead_annotator", "Project manager and dataset lead"),
        ("annotator", "Image annotator"),
        ("reviewer", "Validation and quality reviewer"),
    ]
    for r_name, r_desc in roles:
        existing_role = db.query(Role).filter(Role.name == r_name).first()
        if not existing_role:
            db.add(Role(name=r_name, description=r_desc))
    db.commit()

    # 2. Seed Default Admin User
    admin_email = "admin@office.local"
    admin_user = db.query(User).filter(User.email == admin_email).first()
    if not admin_user:
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        admin_user = User(
            email=admin_email,
            full_name="System Administrator",
            role="admin",
            role_id=admin_role.id if admin_role else None,
            hashed_password=get_password_hash("Admin@123"),
            is_active=True,
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        record_ledger_event(db, "USER_CREATED", admin_email, "Default administrator account seeded.")
        logger.info("Admin user created: %s / Admin@123", admin_email)

    # 3. Seed Default Project: Hydride Microstructures
    project_name = "Hydride Microstructures (Zircaloy)"
    project = db.query(DatasetProject).filter(DatasetProject.name == project_name).first()
    if not project:
        project = DatasetProject(
            name=project_name,
            description="Ground truth annotation of hydride platelets in zirconium cladding microstructures for ML model training.",
            task_type="semantic_segmentation",
            created_by=admin_email,
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        # Add classes
        classes_data = [
            ("Hydride", "#FF0000", 1, "Hydride precipitate platelets", True),
            ("Matrix", "#2ECC71", 2, "Zirconium metal matrix phase", False),
            ("Crack / Pore", "#3498DB", 3, "Cracks, pores, or delaminations", False),
            ("Grain Boundary", "#F1C40F", 4, "Prior grain boundaries", False),
        ]
        for c_name, c_color, c_idx, c_desc, c_def in classes_data:
            db.add(DatasetClass(
                project_id=project.id,
                name=c_name,
                color_hex=c_color,
                class_index=c_idx,
                description=c_desc,
                is_default=c_def,
            ))
        db.commit()
        record_ledger_event(db, "PROJECT_CREATED", admin_email, f"Project '{project_name}' created.", project_id=project.id)

    # 4. Seed sample images from HydrideSegmentation if available
    images_dir = Path(config.storage.images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)

    hydride_sample_dir = Path("C:/Users/kvman/HydrideSegmentation/data/sample_images")
    sample_files = []
    if hydride_sample_dir.exists():
        for p in hydride_sample_dir.glob("*.png"):
            sample_files.append(p)

    if not sample_files:
        # Create a synthetic sample if external directory not found
        synth_path = images_dir / "sample_hydride_micrograph_01.png"
        if not synth_path.exists():
            create_synthetic_microstructure(str(synth_path))
        sample_files = [synth_path]

    splits = ["train", "val", "test"]
    for i, src_path in enumerate(sample_files):
        dest_filename = f"hydride_sample_{i+1:02d}_{src_path.name}"
        dest_path = images_dir / dest_filename
        if not dest_path.exists():
            shutil.copy2(src_path, dest_path)

        checksum = compute_file_sha256(str(dest_path))
        existing_img = db.query(MicrographImage).filter(MicrographImage.checksum_sha256 == checksum).first()

        if not existing_img:
            cv_img = cv2.imread(str(dest_path))
            h, w = cv_img.shape[:2] if cv_img is not None else (512, 512)
            channels = cv_img.shape[2] if cv_img is not None else 3

            assigned_split = splits[i % len(splits)]
            new_img = MicrographImage(
                project_id=project.id,
                filename=dest_filename,
                original_filename=src_path.name,
                file_path=str(dest_path),
                width=w,
                height=h,
                channels=channels,
                checksum_sha256=checksum,
                status="unannotated",
                split_assignment=assigned_split,
                metadata_json='{"material": "Zircaloy-4", "etchant": "HF-HNO3", "magnification": "500x"}',
            )
            db.add(new_img)
            db.commit()
            db.refresh(new_img)

            # Pre-populate draft with smart Otsu detection for the first sample
            if i == 0:
                try:
                    otsu_res = run_otsu_threshold(str(dest_path), invert=True, blur_kernel=3, morphology_close=2)
                    vector_shapes = []
                    for c_idx, c_pts in enumerate(otsu_res["contours"]):
                        vector_shapes.append({
                            "id": f"otsu_shape_{c_idx+1}",
                            "type": "polygon",
                            "class_index": 1,
                            "points": c_pts,
                            "color": "#FF0000",
                            "closed": True,
                        })

                    import json
                    draft = AnnotationDraft(
                        image_id=new_img.id,
                        user_email=admin_email,
                        vector_data=json.dumps(vector_shapes),
                        zoom_level=1.0,
                        pan_x=0.0,
                        pan_y=0.0,
                        active_class_index=1,
                        active_tool="brush",
                        brush_size=10,
                    )
                    db.add(draft)
                    new_img.status = "in_progress"
                    db.commit()
                except Exception as ex:
                    logger.warning("Could not pre-populate sample draft: %s", ex)

            record_ledger_event(db, "IMAGE_IMPORTED", admin_email, f"Imported micrograph {dest_filename}", project_id=project.id, image_id=new_img.id)

    logger.info("Database seeding completed.")
