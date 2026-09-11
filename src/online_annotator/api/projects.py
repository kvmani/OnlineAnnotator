"""Projects, classes, image lists, uploads, pre-annotation import, activity and exports."""

from __future__ import annotations

import io
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image as PILImage
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import get_db
from ..models import AuditEvent, Export, Image, LabelClass, Project, User
from ..services import audit, imaging, workflow
from ..services import exports as export_ops
from ..services import labels as label_ops
from ..services import projects as project_ops
from . import serialize
from .deps import active_user, admin, get_image, get_project, get_settings, reviewer
from .schemas import (
    BulkImageUpdateBody,
    ClassBody,
    ClassUpdateBody,
    ExportBody,
    ProjectCreateBody,
    ProjectUpdateBody,
)

router = APIRouter(prefix="/api/v1", tags=["projects"])


@router.get("/projects")
def list_projects(include_archived: bool = False, db: Session = Depends(get_db),
                  _: User = Depends(active_user)) -> dict:
    query = db.query(Project).order_by(Project.name)
    if not include_archived:
        query = query.filter(Project.archived.is_(False))
    return {"projects": [serialize.project(p) for p in query.all()]}


@router.post("/projects")
def create_project(body: ProjectCreateBody, db: Session = Depends(get_db), actor: User = Depends(admin),
                   settings: Settings = Depends(get_settings)) -> dict:
    name = body.name.strip()
    if db.query(Project).filter(Project.name == name).first():
        raise HTTPException(409, f"A project called {name!r} already exists.")
    project = Project(name=name, description=body.description.strip(), guidelines=body.guidelines.strip(),
                      created_by=actor.email)
    db.add(project)
    db.flush()
    classes = body.classes or [ClassBody(name="Feature", description="Replace with your first class.")]
    try:
        for c in classes:
            project_ops.add_class(db, project, c.name, c.color, c.description, c.index)
    except project_ops.ProjectError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    audit.record(db, settings.audit_file, actor.email, "project_created", f"Created project {name}.",
                 project_id=project.id)
    return {"project": serialize.project(project, detail=True)}


@router.get("/projects/{project_id}")
def project_detail(project_id: int, db: Session = Depends(get_db), _: User = Depends(active_user)) -> dict:
    return {"project": serialize.project(get_project(project_id, db), detail=True)}


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: ProjectUpdateBody, db: Session = Depends(get_db),
                   actor: User = Depends(admin), settings: Settings = Depends(get_settings)) -> dict:
    project = get_project(project_id, db)
    changes = body.model_dump(exclude_none=True)
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        clash = db.query(Project).filter(Project.name == changes["name"], Project.id != project.id).first()
        if clash:
            raise HTTPException(409, f"A project called {changes['name']!r} already exists.")
    for key, value in changes.items():
        setattr(project, key, value)
    db.commit()
    audit.record(db, settings.audit_file, actor.email, "project_updated",
                 f"Updated project {project.name}: {', '.join(changes)}.", project_id=project.id)
    return {"project": serialize.project(project, detail=True)}


# ------------------------------------------------------------------------------- classes
@router.post("/projects/{project_id}/classes")
def add_class(project_id: int, body: ClassBody, db: Session = Depends(get_db), actor: User = Depends(admin),
              settings: Settings = Depends(get_settings)) -> dict:
    project = get_project(project_id, db)
    try:
        label = project_ops.add_class(db, project, body.name, body.color, body.description, body.index)
    except project_ops.ProjectError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit.record(db, settings.audit_file, actor.email, "class_added",
                 f"Added class {label.index} {label.name} to {project.name}.", project_id=project.id)
    return {"class": serialize.label_class(label)}


@router.patch("/projects/{project_id}/classes/{class_id}")
def update_class(project_id: int, class_id: int, body: ClassUpdateBody, db: Session = Depends(get_db),
                 actor: User = Depends(admin), settings: Settings = Depends(get_settings)) -> dict:
    project = get_project(project_id, db)
    label = db.get(LabelClass, class_id)
    if label is None or label.project_id != project.id:
        raise HTTPException(404, "Class not found.")
    name = (body.name or label.name).strip()
    color = (body.color or label.color).upper()
    try:
        project_ops.validate_class(label.index, name, color)
    except project_ops.ProjectError as exc:
        raise HTTPException(400, str(exc)) from exc
    if name.lower() != label.name.lower() and name.lower() in {c.name.lower() for c in project.classes}:
        raise HTTPException(409, f"A class called {name!r} already exists.")
    label.name, label.color = name, color
    if body.description is not None:
        label.description = body.description.strip()
    db.commit()
    audit.record(db, settings.audit_file, actor.email, "class_updated",
                 f"Updated class {label.index} ({label.name}) in {project.name}.", project_id=project.id)
    return {"class": serialize.label_class(label)}


@router.delete("/projects/{project_id}/classes/{class_id}")
def delete_class(project_id: int, class_id: int, db: Session = Depends(get_db), actor: User = Depends(admin),
                 settings: Settings = Depends(get_settings)) -> dict:
    project = get_project(project_id, db)
    label = db.get(LabelClass, class_id)
    if label is None or label.project_id != project.id:
        raise HTTPException(404, "Class not found.")
    if project_ops.class_in_use(project, label.index):
        raise HTTPException(409, f"Class {label.name} is used in existing annotations and cannot be deleted. "
                                 "Rename it instead, or erase those pixels first.")
    if len(project.classes) == 1:
        raise HTTPException(409, "A project needs at least one class.")
    project.classes.remove(label)
    db.commit()
    audit.record(db, settings.audit_file, actor.email, "class_deleted",
                 f"Deleted class {label.index} ({label.name}) from {project.name}.", project_id=project.id)
    return {"ok": True}


# -------------------------------------------------------------------------------- images
@router.get("/projects/{project_id}/images")
def list_images(project_id: int, db: Session = Depends(get_db), user: User = Depends(active_user)) -> dict:
    project = get_project(project_id, db)
    images = sorted(project.images, key=lambda i: i.stem.lower())
    return {"images": [serialize.image(db, img, user) for img in images],
            "counts": project_ops.status_counts(project)}


@router.post("/projects/{project_id}/images")
async def upload_images(project_id: int, files: list[UploadFile] = File(...), split: str = Form("unassigned"),
                        db: Session = Depends(get_db), user: User = Depends(active_user),
                        settings: Settings = Depends(get_settings)) -> dict:
    project = get_project(project_id, db)
    added, messages, errors = [], [], []
    limit = settings.max_upload_mb * 1024 * 1024
    for upload in files:
        raw = await upload.read(limit + 1)
        name = Path(upload.filename or "upload").name
        if len(raw) > limit:
            errors.append(f"{name}: larger than the {settings.max_upload_mb} MB upload limit.")
            continue
        try:
            image, message = project_ops.add_uploaded_image(db, settings, project, user, raw, name, split)
        except imaging.ImageIngestError as exc:
            db.rollback()
            errors.append(str(exc))
            continue
        if image is not None:
            added.append(image.id)
        messages.append(message)
    if added:
        audit.record(db, settings.audit_file, user.email, "images_uploaded",
                     f"Uploaded {len(added)} image(s) to {project.name}.", project_id=project.id,
                     details={"image_ids": added})
    return {"added": len(added), "messages": messages, "errors": errors}


@router.post("/projects/{project_id}/images/bulk")
def bulk_update(project_id: int, body: BulkImageUpdateBody, db: Session = Depends(get_db),
                actor: User = Depends(reviewer), settings: Settings = Depends(get_settings)) -> dict:
    project = get_project(project_id, db)
    targets = [i for i in project.images if i.id in set(body.image_ids)]
    for img in targets:
        if body.split is not None:
            img.split = body.split
        if body.assigned_to is not None:
            img.assigned_to = body.assigned_to or None
    db.commit()
    audit.record(db, settings.audit_file, actor.email, "images_updated",
                 f"Updated {len(targets)} image(s) in {project.name}.", project_id=project.id,
                 details=body.model_dump(exclude_none=True))
    return {"updated": len(targets)}


@router.get("/projects/{project_id}/next")
def next_image(project_id: int, mode: str = "annotate", after: int | None = None, db: Session = Depends(get_db),
               user: User = Depends(active_user)) -> dict:
    project = get_project(project_id, db)
    if mode == "review" and not user.can_review:
        raise HTTPException(403, "Reviewing needs the reviewer role.")
    img = project_ops.next_image(db, project, user, after, mode)
    return {"image_id": img.id if img else None}


@router.post("/projects/{project_id}/masks")
async def import_masks(project_id: int, files: list[UploadFile] = File(...), import_class: int | None = Form(None),
                       db: Session = Depends(get_db), user: User = Depends(active_user),
                       settings: Settings = Depends(get_settings)) -> dict:
    """Load masks (e.g. model predictions) as the working copy of matching images.

    A mask ``<stem>_mask.png`` or ``<stem>.png`` is matched to the image with that stem
    or original filename stem.
    """
    project = get_project(project_id, db)
    classes = {c.index: c.color for c in project.classes}
    target = import_class if import_class in classes else min(classes)
    by_stem: dict[str, Image] = {}
    for img in project.images:
        by_stem[img.stem.lower()] = img
        by_stem.setdefault(Path(img.original_filename).stem.lower(), img)
    imported, errors = [], []
    for upload in files:
        name = Path(upload.filename or "mask").name
        stem = Path(name).stem
        key = stem[:-5] if stem.lower().endswith("_mask") else stem
        img = by_stem.get(key.lower()) or by_stem.get(imaging.safe_stem(key).lower())
        if img is None:
            errors.append(f"{name}: no image called {key!r} in this project.")
            continue
        try:
            with PILImage.open(io.BytesIO(await upload.read())) as pil:
                arr = np.asarray(pil.convert("RGB") if pil.mode in ("P", "RGBA", "CMYK") else pil)
            if arr.shape[:2] != (img.height, img.width):
                raise label_ops.LabelError(
                    f"size {arr.shape[1]} x {arr.shape[0]} does not match the image ({img.width} x {img.height}).")
            labels_arr, kind = label_ops.interpret_mask_image(arr, classes, target)
            workflow.import_working(db, settings, img, user, labels_arr, origin=f"imported from {name} ({kind})")
            db.commit()
            imported.append(f"{name} -> {img.stem} ({kind} mask)")
        except (label_ops.LabelError, workflow.WorkflowError) as exc:
            db.rollback()
            errors.append(f"{name}: {exc}")
        except OSError as exc:
            errors.append(f"{name}: not a readable image ({exc}).")
    if imported:
        audit.record(db, settings.audit_file, user.email, "masks_imported",
                     f"Imported {len(imported)} pre-annotation mask(s) into {project.name}.",
                     project_id=project.id, details={"files": imported})
    return {"imported": imported, "errors": errors}


@router.get("/projects/{project_id}/activity")
def activity(project_id: int, limit: int = 100, db: Session = Depends(get_db), _: User = Depends(active_user)):
    get_project(project_id, db)
    rows = (db.query(AuditEvent).filter(AuditEvent.project_id == project_id)
            .order_by(AuditEvent.id.desc()).limit(min(limit, 500)).all())
    return {"events": [r.as_dict() for r in rows]}


# ------------------------------------------------------------------------------- exports
def _options(body: ExportBody) -> export_ops.ExportOptions:
    return export_ops.ExportOptions(**body.model_dump())


@router.post("/projects/{project_id}/exports/preview")
def export_preview(project_id: int, body: ExportBody, db: Session = Depends(get_db),
                   _: User = Depends(reviewer)) -> dict:
    try:
        return export_ops.preview(get_project(project_id, db), _options(body))
    except export_ops.ExportError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/projects/{project_id}/exports")
def create_export(project_id: int, body: ExportBody, db: Session = Depends(get_db),
                  actor: User = Depends(reviewer), settings: Settings = Depends(get_settings)) -> dict:
    project = get_project(project_id, db)
    options = _options(body)
    try:
        record = export_ops.build_export(db, settings, project, actor, options)
    except export_ops.ExportError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit.record(db, settings.audit_file, actor.email, "dataset_exported",
                 f"Exported {record.image_count} image(s) from {project.name} as {record.filename}.",
                 project_id=project.id, details=asdict(options))
    return {"export": serialize.export(record)}


@router.get("/projects/{project_id}/exports")
def list_exports(project_id: int, db: Session = Depends(get_db), _: User = Depends(active_user)) -> dict:
    get_project(project_id, db)
    rows = db.query(Export).filter(Export.project_id == project_id).order_by(Export.id.desc()).all()
    return {"exports": [serialize.export(e) for e in rows], "yolo_available": export_ops.yolo_available()}


@router.get("/exports/{export_id}/download")
def download_export(export_id: int, db: Session = Depends(get_db), _: User = Depends(active_user),
                    settings: Settings = Depends(get_settings)):
    record = db.get(Export, export_id)
    path = settings.exports_dir / record.filename if record else None
    if record is None or path is None or not path.exists():
        raise HTTPException(404, "That export file no longer exists on the server. Create a new export.")
    return FileResponse(path, media_type="application/zip", filename=record.filename)


@router.get("/projects/{project_id}/image/{image_id}")
def image_in_project(project_id: int, image_id: int, db: Session = Depends(get_db),
                     user: User = Depends(active_user)) -> dict:
    img = get_image(image_id, db)
    if img.project_id != project_id:
        raise HTTPException(404, "Image not found in this project.")
    return {"image": serialize.image(db, img, user, detail=True)}


@router.get("/projects/{project_id}/summary")
def project_summary(project_id: int, db: Session = Depends(get_db), _: User = Depends(active_user)) -> dict:
    """Per-class pixel totals over approved versions (for the dashboard)."""
    project = get_project(project_id, db)
    totals: dict[str, int] = {}
    pixels = 0
    for img in project.images:
        v = workflow.latest(img, "approved")
        if v is None:
            continue
        pixels += img.width * img.height
        for k, n in v.pixels.items():
            totals[k] = totals.get(k, 0) + n
    return {"approved_pixels": pixels, "class_pixels": totals,
            "class_fractions": {k: (n / pixels if pixels else 0.0) for k, n in totals.items()},
            "counts": project_ops.status_counts(project),
            "classes": json.loads(json.dumps([serialize.label_class(c) for c in project.classes]))}
