"""Per-image endpoints: pixels, label maps, leases and the review workflow."""

from __future__ import annotations

import io
from dataclasses import asdict
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from PIL import Image as PILImage
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import get_db
from ..models import Image, User, Version
from ..services import access, audit, imaging, workflow
from ..services import labels as label_ops
from ..services import projects as project_ops
from . import serialize
from .deps import active_user, admin, current_user, get_image, get_settings
from .schemas import ImageUpdateBody, MaskRemarksBody, ReviewBody, SubmitBody

router = APIRouter(prefix="/api/v1/images", tags=["images"])
PRIVATE_CACHE = {"Cache-Control": "private, max-age=3600"}


def _workflow_error(exc: access.Refused) -> HTTPException:
    return HTTPException(exc.status, str(exc))


def _version(image: Image, number: int) -> Version:
    for v in image.versions:
        if v.number == number:
            return v
    raise HTTPException(404, f"Version {number} does not exist for this image.")


@router.get("/{image_id}")
def image_detail(image_id: int, db: Session = Depends(get_db), user: User = Depends(active_user)) -> dict:
    return {"image": serialize.image(db, get_image(image_id, db), user, detail=True)}


@router.patch("/{image_id}")
def update_image(image_id: int, body: ImageUpdateBody, db: Session = Depends(get_db),
                 user: User = Depends(active_user), settings: Settings = Depends(get_settings)) -> dict:
    img = get_image(image_id, db)
    changes = body.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(img, key, (value or None) if key == "assigned_to" else value)
    db.commit()
    audit.record(db, settings.audit_file, user.email, "image_updated",
                 f"Updated {img.stem}: {', '.join(changes)}.", project_id=img.project_id, image_id=img.id)
    return {"image": serialize.image(db, img, user, detail=True)}


@router.delete("/{image_id}")
def delete_image(image_id: int, db: Session = Depends(get_db), actor: User = Depends(admin),
                 settings: Settings = Depends(get_settings)) -> dict:
    project_ops.delete_image(db, settings, get_image(image_id, db), actor)
    return {"ok": True}


# ------------------------------------------------------------------------------ pixels
@router.get("/{image_id}/display")
def display(image_id: int, db: Session = Depends(get_db), _: User = Depends(current_user),
            settings: Settings = Depends(get_settings)):
    img = get_image(image_id, db)
    return FileResponse(workflow.display_path(settings, img), headers=PRIVATE_CACHE)


@router.get("/{image_id}/original")
def original(image_id: int, db: Session = Depends(get_db), _: User = Depends(current_user),
             settings: Settings = Depends(get_settings)):
    img = get_image(image_id, db)
    return FileResponse(workflow.original_path(settings, img), filename=img.original_filename)


@router.get("/{image_id}/thumb")
def thumb(image_id: int, db: Session = Depends(get_db), _: User = Depends(current_user),
          settings: Settings = Depends(get_settings)):
    img = get_image(image_id, db)
    return FileResponse(workflow.thumb_path(settings, img), media_type="image/jpeg", headers=PRIVATE_CACHE)


@router.get("/{image_id}/grey")
def grey(image_id: int, db: Session = Depends(get_db), _: User = Depends(current_user),
         settings: Settings = Depends(get_settings)) -> Response:
    """Exact 8-bit luminance, row-major, gzip-encoded: input for the assisted tools."""
    img = get_image(image_id, db)
    data = label_ops.to_raw_gzip(imaging.grey_levels(workflow.display_path(settings, img)))
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Encoding": "gzip", **PRIVATE_CACHE})


@router.get("/{image_id}/labels")
def get_labels(image_id: int, version: int | None = None, db: Session = Depends(get_db),
               _: User = Depends(current_user), settings: Settings = Depends(get_settings)) -> Response:
    """Label map as raw bytes (gzip). ``version`` selects a frozen version instead of the working copy."""
    img = get_image(image_id, db)
    if version is None:
        arr, revision = workflow.load_working(settings, img), img.working_revision
    else:
        arr, revision = workflow.load_version(settings, img, _version(img, version)), -1
    return Response(label_ops.to_raw_gzip(arr), media_type="application/octet-stream",
                    headers={"Content-Encoding": "gzip", "Cache-Control": "no-store",
                             "X-Revision": str(revision)})


@router.put("/{image_id}/labels")
async def put_labels(image_id: int, request: Request, base_revision: int, db: Session = Depends(get_db),
                     user: User = Depends(active_user), settings: Settings = Depends(get_settings)) -> dict:
    img = get_image(image_id, db)
    body = await request.body()
    if len(body) > img.width * img.height + 1024 * 1024:
        raise HTTPException(413, "Label payload is larger than the image.")
    try:
        arr = label_ops.decode_raw(body, img.width, img.height,
                                   gzipped=request.headers.get("Content-Encoding", "") == "gzip")
        workflow.save_working(db, settings, img, user, arr, base_revision)
    except label_ops.LabelError as exc:
        raise HTTPException(422, str(exc)) from exc
    except access.Refused as exc:
        raise _workflow_error(exc) from exc
    audit.record(db, settings.audit_file, user.email, "labels_saved",
                 f"Saved {img.stem} (revision {img.working_revision}).", project_id=img.project_id,
                 image_id=img.id, details={"class_pixels": img.class_pixels})
    return {"revision": img.working_revision, "class_pixels": img.class_pixels, "status": img.status}


@router.get("/{image_id}/mask.png")
def mask_png(image_id: int, style: str = "colour", target: int | None = None, version: int | None = None,
             db: Session = Depends(get_db), _: User = Depends(current_user),
             settings: Settings = Depends(get_settings)) -> Response:
    img = get_image(image_id, db)
    arr = (workflow.load_working(settings, img) if version is None
           else workflow.load_version(settings, img, _version(img, version)))
    palette = workflow.palette(img)
    if style == "indexed":
        out = arr
    elif style == "binary":
        out = label_ops.binary(arr, target or min(palette))
    else:
        out = label_ops.colourize(arr, palette)
    buf = io.BytesIO()
    PILImage.fromarray(out).save(buf, format="PNG")
    suffix = f"_v{version}" if version else ""
    return Response(buf.getvalue(), media_type="image/png", headers={
        "Content-Disposition": f'attachment; filename="{img.stem}{suffix}_mask_{style}.png"'})


# ------------------------------------------------------------------------------- leases
@router.post("/{image_id}/lock")
def acquire(image_id: int, db: Session = Depends(get_db), user: User = Depends(active_user),
            settings: Settings = Depends(get_settings)) -> dict:
    img = get_image(image_id, db)
    before = workflow.lock_state(db, img, user)
    try:
        state = workflow.acquire_lock(db, settings, img, user)
    except access.Refused as exc:
        raise _workflow_error(exc) from exc
    if not before.by_me:
        audit.record(db, settings.audit_file, user.email, "lock_acquired", f"Started editing {img.stem}.",
                     project_id=img.project_id, image_id=img.id)
    return {"lock": asdict(state), "lease_seconds": settings.lock_lease_seconds}


@router.delete("/{image_id}/lock")
def release(image_id: int, force: bool = False, db: Session = Depends(get_db), user: User = Depends(active_user),
            settings: Settings = Depends(get_settings)) -> dict:
    img = get_image(image_id, db)
    try:
        released = workflow.release_lock(db, img, user, force=force)
    except access.Refused as exc:
        raise _workflow_error(exc) from exc
    if released:
        audit.record(db, settings.audit_file, user.email, "lock_released",
                     f"{'Broke the lock on' if force else 'Stopped editing'} {img.stem}.",
                     project_id=img.project_id, image_id=img.id)
    return {"released": released}


@router.post("/{image_id}/lock/release")
def release_beacon(image_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """``navigator.sendBeacon`` target used when a tab closes (cannot send custom headers)."""
    img = get_image(image_id, db)
    try:
        return {"released": workflow.release_lock(db, img, user)}
    except workflow.WorkflowError:
        return {"released": False}


# ----------------------------------------------------------------------------- workflow
@router.post("/{image_id}/submit")
def submit(image_id: int, body: SubmitBody, db: Session = Depends(get_db), user: User = Depends(active_user),
           settings: Settings = Depends(get_settings)) -> dict:
    img = get_image(image_id, db)
    try:
        version = workflow.submit(db, settings, img, user, body.note)
    except access.Refused as exc:
        raise _workflow_error(exc) from exc
    audit.record(db, settings.audit_file, user.email, "submitted", f"Submitted {img.stem} v{version.number} "
                 "for review.", project_id=img.project_id, image_id=img.id, details={"note": body.note})
    return {"image": serialize.image(db, img, user, detail=True)}


@router.post("/{image_id}/withdraw")
def withdraw(image_id: int, db: Session = Depends(get_db), user: User = Depends(active_user),
             settings: Settings = Depends(get_settings)) -> dict:
    img = get_image(image_id, db)
    try:
        version = workflow.withdraw(db, img, user)
    except access.Refused as exc:
        raise _workflow_error(exc) from exc
    audit.record(db, settings.audit_file, user.email, "withdrawn", f"Withdrew {img.stem} v{version.number}.",
                 project_id=img.project_id, image_id=img.id)
    return {"image": serialize.image(db, img, user, detail=True)}


@router.post("/{image_id}/review")
def review(image_id: int, body: ReviewBody, db: Session = Depends(get_db), user: User = Depends(active_user),
           settings: Settings = Depends(get_settings)) -> dict:
    img = get_image(image_id, db)
    try:
        version = workflow.review(db, settings, img, user, body.decision, body.comment)
    except access.Refused as exc:
        raise _workflow_error(exc) from exc
    verb = "Approved" if body.decision == "approve" else "Requested changes on"
    audit.record(db, settings.audit_file, user.email, body.decision, f"{verb} {img.stem} v{version.number}.",
                 project_id=img.project_id, image_id=img.id, details={"comment": body.comment})
    return {"image": serialize.image(db, img, user, detail=True)}


@router.post("/{image_id}/mask-import")
async def import_mask(image_id: int, file: UploadFile = File(...), import_class: int | None = Form(None),
                      source_tool: str = Form(""), remarks: str = Form(""),
                      db: Session = Depends(get_db), user: User = Depends(active_user),
                      settings: Settings = Depends(get_settings)) -> dict:
    """Load one externally produced mask as this image's working copy, to be corrected here.

    For annotators who already have a mask for this micrograph -- from another segmentation
    tool, an in-house script or a model prediction -- and want to fix its mistakes instead of
    labelling from scratch. The image records that its annotation was imported, which tool
    produced it and the annotator's remarks; that provenance follows every submitted version
    into the export manifest.
    """
    img = get_image(image_id, db)
    classes = {c.index: c.color for c in img.project.classes}
    if not classes:
        raise HTTPException(400, "This project has no classes yet, so a mask cannot be interpreted.")
    target = import_class if import_class in classes else min(classes)
    name = PurePosixPath((file.filename or "mask").replace("\\", "/")).name
    try:
        labels_arr, kind = label_ops.decode_mask_file(await file.read(), img.width, img.height, classes, target)
        workflow.import_working(db, settings, img, user, labels_arr,
                                origin=f"imported from {name} ({kind})", source_file=name,
                                source_tool=source_tool, source_remarks=remarks)
        db.commit()
    except label_ops.LabelError as exc:
        db.rollback()
        raise HTTPException(400, f"{name}: {exc}") from exc
    except access.Refused as exc:
        db.rollback()
        raise _workflow_error(exc) from exc
    audit.record(db, settings.audit_file, user.email, "mask_imported",
                 f"Imported {name} ({kind} mask) as the working copy of {img.stem}.",
                 project_id=img.project_id, image_id=img.id,
                 details={"file": name, "kind": kind, "source_tool": source_tool, "remarks": remarks})
    return {"image": serialize.image(db, img, user, detail=True), "kind": kind,
            "message": f"Loaded {name} as a {kind} mask. Correct it, then submit for review."}


@router.patch("/{image_id}/mask-source")
def update_mask_source(image_id: int, body: MaskRemarksBody, db: Session = Depends(get_db),
                       user: User = Depends(active_user),
                       settings: Settings = Depends(get_settings)) -> dict:
    """Edit the tool name and remarks recorded for an imported mask."""
    img = get_image(image_id, db)
    try:
        workflow.set_source_remarks(db, img, body.source_tool, body.remarks)
    except access.Refused as exc:
        raise _workflow_error(exc) from exc
    audit.record(db, settings.audit_file, user.email, "mask_source_updated",
                 f"Updated the import remarks for {img.stem}.", project_id=img.project_id, image_id=img.id,
                 details={"source_tool": img.mask_source_tool, "remarks": img.mask_source_remarks})
    return {"image": serialize.image(db, img, user, detail=True)}


@router.post("/{image_id}/restore/{number}")
def restore(image_id: int, number: int, db: Session = Depends(get_db), user: User = Depends(active_user),
            settings: Settings = Depends(get_settings)) -> dict:
    img = get_image(image_id, db)
    try:
        workflow.restore(db, settings, img, user, _version(img, number))
    except access.Refused as exc:
        raise _workflow_error(exc) from exc
    audit.record(db, settings.audit_file, user.email, "restored", f"Restored v{number} of {img.stem} into the "
                 "working copy.", project_id=img.project_id, image_id=img.id)
    return {"image": serialize.image(db, img, user, detail=True)}
