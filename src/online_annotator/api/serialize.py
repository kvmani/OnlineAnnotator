"""Dict renderings of ORM objects for JSON responses."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import Session

from ..models import Export, Image, LabelClass, Project, User, Version, as_utc
from ..services import projects as project_ops
from ..services import workflow


def iso(value) -> str | None:
    value = as_utc(value)
    return value.isoformat() if value else None


def user(u: User) -> dict[str, Any]:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active,
            "must_change_password": u.must_change_password, "created_at": iso(u.created_at),
            "last_login_at": iso(u.last_login_at)}


def label_class(c: LabelClass) -> dict[str, Any]:
    return {"id": c.id, "index": c.index, "name": c.name, "color": c.color, "description": c.description}


def project(p: Project, detail: bool = False) -> dict[str, Any]:
    out = {"id": p.id, "name": p.name, "description": p.description, "archived": p.archived,
           "created_by": p.created_by, "created_at": iso(p.created_at),
           "counts": project_ops.status_counts(p), "classes": [label_class(c) for c in p.classes]}
    if detail:
        out["guidelines"] = p.guidelines
    return out


def version(v: Version) -> dict[str, Any]:
    return {"id": v.id, "number": v.number, "kind": v.kind, "status": v.status, "created_by": v.created_by,
            "created_at": iso(v.created_at), "note": v.note, "reviewed_by": v.reviewed_by,
            "reviewed_at": iso(v.reviewed_at), "review_comment": v.review_comment,
            "class_pixels": v.pixels, "mask_sha256": v.mask_sha256}


def image(db: Session, img: Image, viewer: User, detail: bool = False) -> dict[str, Any]:
    lock = workflow.lock_state(db, img, viewer)
    last = max(img.versions, key=lambda v: v.number) if img.versions else None
    out = {
        "id": img.id, "project_id": img.project_id, "original_filename": img.original_filename,
        "stem": img.stem, "width": img.width, "height": img.height, "status": img.status, "split": img.split,
        "assigned_to": img.assigned_to, "notes": img.notes, "uploaded_by": img.uploaded_by,
        "created_at": iso(img.created_at), "working_revision": img.working_revision,
        "working_updated_by": img.working_updated_by, "working_updated_at": iso(img.working_updated_at),
        "class_pixels": img.class_pixels, "lock": asdict(lock),
        "latest_version": version(last) if last else None,
        "thumb_url": f"api/v1/images/{img.id}/thumb?r={img.working_revision}",
    }
    if detail:
        out.update({
            "source_mode": img.source_mode, "conversion_note": img.conversion_note,
            "working_origin": img.working_origin, "sha256": img.sha256,
            "versions": [version(v) for v in sorted(img.versions, key=lambda v: -v.number)],
            "display_url": f"api/v1/images/{img.id}/display",
        })
    return out


def export(e: Export) -> dict[str, Any]:
    return {"id": e.id, "project_id": e.project_id, "created_by": e.created_by, "created_at": iso(e.created_at),
            "filename": e.filename, "size_bytes": e.size_bytes, "sha256": e.sha256, "image_count": e.image_count,
            "options": json.loads(e.options or "{}"), "summary": json.loads(e.summary or "{}"),
            "download_url": f"api/v1/exports/{e.id}/download"}
