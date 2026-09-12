"""Editing leases and the annotation review workflow.

Image status machine::

    new ──save──▶ in_progress ──submit──▶ submitted ──approve──▶ approved
                     ▲    ▲                   │  │                  │
                     │    └──────withdraw─────┘  └─request changes─▶ changes_requested
                     └───────────────save (re-opens an approved image)─┘       │
                                                                  submit ◀─────┘

Rules enforced here (never only in the browser):

* every change to a label map requires the caller to hold the image's lease;
* a save must name the revision it was based on (no silent lost updates);
* a submitted image can be edited only by a reviewer (or after withdrawal);
* nobody approves their own submission unless ``allow_self_approval`` is set;
* exports read the latest **approved** version, never the working copy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Image, ImageLock, User, Version, as_utc, utcnow
from . import labels as label_ops


class WorkflowError(Exception):
    """A request that conflicts with the workflow; ``status`` is the HTTP code to use."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- storage paths
def image_dir(settings: Settings, image: Image) -> Path:
    return settings.images_dir / str(image.project_id)


def original_path(settings: Settings, image: Image) -> Path:
    return image_dir(settings, image) / image.stored_name


def display_path(settings: Settings, image: Image) -> Path:
    return image_dir(settings, image) / image.display_name


def thumb_path(settings: Settings, image: Image) -> Path:
    return image_dir(settings, image) / f"{image.id}_thumb.jpg"


def mask_dir(settings: Settings, image: Image) -> Path:
    return settings.masks_dir / str(image.id)


def working_path(settings: Settings, image: Image) -> Path:
    return mask_dir(settings, image) / "working.png"


def version_path(settings: Settings, image: Image, version: Version) -> Path:
    return mask_dir(settings, image) / version.mask_file


# ----------------------------------------------------------------------------------- leases
@dataclass
class LockState:
    locked: bool
    by_me: bool = False
    user_email: str | None = None
    user_name: str | None = None
    expires_at: str | None = None
    seconds_left: int = 0


def lock_state(db: Session, image: Image, user: User | None) -> LockState:
    lock = db.get(ImageLock, image.id)
    if lock is None:
        return LockState(locked=False)
    now = utcnow()
    expires = as_utc(lock.expires_at)
    if expires <= now:
        db.delete(lock)
        db.commit()
        return LockState(locked=False)
    return LockState(
        locked=True,
        by_me=user is not None and lock.user_email == user.email,
        user_email=lock.user_email,
        user_name=lock.user_name,
        expires_at=expires.isoformat(),
        seconds_left=int((expires - now).total_seconds()),
    )


def acquire_lock(db: Session, settings: Settings, image: Image, user: User) -> LockState:
    """Acquire or renew the lease. Raises if another user holds a live lease."""
    now = utcnow()
    expires = now + timedelta(seconds=settings.lock_lease_seconds)
    lock = db.get(ImageLock, image.id)
    if lock is not None and as_utc(lock.expires_at) > now and lock.user_email != user.email:
        name = lock.user_name or lock.user_email
        raise WorkflowError(
            f"{name} is editing this image right now. You can view it; editing unlocks when they "
            "leave or after the lease expires.",
            status=423,
        )
    if lock is None:
        lock = ImageLock(image_id=image.id, user_email=user.email, user_name=user.full_name,
                         acquired_at=now, expires_at=expires)
        db.add(lock)
    else:
        if lock.user_email != user.email:
            lock.acquired_at = now
        lock.user_email = user.email
        lock.user_name = user.full_name
        lock.expires_at = expires
    db.commit()
    return lock_state(db, image, user)


def release_lock(db: Session, image: Image, user: User, force: bool = False) -> bool:
    lock = db.get(ImageLock, image.id)
    if lock is None:
        return False
    if lock.user_email != user.email and not (force and user.is_admin):
        raise WorkflowError("Only the person editing (or an administrator) can release this lock.", 403)
    db.delete(lock)
    db.commit()
    return True


def require_lock(db: Session, image: Image, user: User) -> None:
    state = lock_state(db, image, user)
    if not state.by_me:
        if state.locked:
            raise WorkflowError(f"{state.user_name or state.user_email} is editing this image; your change "
                                "was not saved.", 423)
        raise WorkflowError("Your editing session for this image expired. Re-open the image to continue; "
                            "your unsaved strokes are still in the browser.", 423)


# ------------------------------------------------------------------------------ label maps
def allowed_indices(image: Image) -> list[int]:
    return [c.index for c in image.project.classes]


def palette(image: Image) -> dict[int, str]:
    return {c.index: c.color for c in image.project.classes}


def load_working(settings: Settings, image: Image) -> np.ndarray:
    return label_ops.load(working_path(settings, image), image.width, image.height)


def load_version(settings: Settings, image: Image, version: Version) -> np.ndarray:
    return label_ops.load(version_path(settings, image, version), image.width, image.height)


def _store_working(settings: Settings, image: Image, labels: np.ndarray, user: User, origin: str) -> None:
    digest = label_ops.save(labels, working_path(settings, image))
    image.working_sha256 = digest
    image.working_class_pixels = json.dumps(label_ops.class_pixels(labels), sort_keys=True)
    image.working_revision += 1
    image.working_updated_by = user.email
    image.working_updated_at = utcnow()
    image.working_origin = origin
    # mask_source is deliberately NOT reset here: correcting an imported mask by hand does
    # not make the ground truth hand-drawn, and provenance must survive ordinary editing.


def save_working(db: Session, settings: Settings, image: Image, user: User, labels: np.ndarray,
                 base_revision: int, origin: str = "edited in browser") -> None:
    if image.status == "submitted" and not user.can_review:
        raise WorkflowError("This image is waiting for review. Withdraw the submission to edit it again.")
    require_lock(db, image, user)
    if base_revision != image.working_revision:
        raise WorkflowError(
            f"The saved annotation changed (revision {image.working_revision}) since you opened it "
            f"(revision {base_revision}). Reload the image to see the latest work before editing.",
        )
    label_ops.validate(labels, allowed_indices(image), image.width, image.height)
    _store_working(settings, image, labels, user, origin)
    if image.status in ("new", "approved"):
        image.status = "in_progress"
    db.commit()


def import_working(db: Session, settings: Settings, image: Image, user: User, labels: np.ndarray,
                   origin: str, source_file: str = "", source_tool: str = "",
                   source_remarks: str = "") -> None:
    """Replace the working copy with a mask produced outside this tool.

    The annotator then corrects it instead of starting from scratch. The image is marked
    ``mask_source = "imported"`` together with the tool that made the mask and the
    annotator's remarks, so every later version and export can say the ground truth began
    as an import rather than as hand-drawn work.
    """
    if image.status in ("submitted", "approved"):
        raise WorkflowError(f"{image.original_filename} is {image.status}; imports only replace work in progress.")
    state = lock_state(db, image, user)
    if state.locked and not state.by_me:
        raise WorkflowError(f"{image.original_filename} is being edited by {state.user_name or state.user_email}.")
    label_ops.validate(labels, allowed_indices(image), image.width, image.height)
    _store_working(settings, image, labels, user, origin)
    image.mask_source = "imported"
    image.mask_source_file = source_file[:255]
    image.mask_source_tool = source_tool.strip()[:200]
    image.mask_source_remarks = source_remarks.strip()
    image.mask_imported_by = user.email
    image.mask_imported_at = utcnow()
    if image.status == "new":
        image.status = "in_progress"


def describe_source(image: Image) -> str:
    """One-line, user-facing summary of where this image's label map came from."""
    if image.mask_source != "imported":
        return "Drawn in Online Annotator."
    parts = [f"Imported from {image.mask_source_file}" if image.mask_source_file else "Imported mask"]
    if image.mask_source_tool:
        parts.append(f"made with {image.mask_source_tool}")
    if image.mask_imported_by:
        parts.append(f"loaded by {image.mask_imported_by}")
    return ", ".join(parts) + ", then corrected here."


def set_source_remarks(db: Session, image: Image, tool: str | None, remarks: str | None) -> None:
    """Update the remarks kept alongside an imported mask (never invents an import)."""
    if image.mask_source != "imported":
        raise WorkflowError(
            "This image's annotation was drawn here, not imported, so there is no import to describe."
        )
    if tool is not None:
        image.mask_source_tool = tool.strip()[:200]
    if remarks is not None:
        image.mask_source_remarks = remarks.strip()
    db.commit()


def _next_number(image: Image) -> int:
    return (max((v.number for v in image.versions), default=0)) + 1


def _snapshot(settings: Settings, image: Image, labels: np.ndarray, user: User, kind: str,
              status: str, note: str) -> Version:
    number = _next_number(image)
    version = Version(image_id=image.id, number=number, mask_file=f"v{number:04d}.png", kind=kind,
                      status=status, created_by=user.email, note=note.strip(), created_at=utcnow(),
                      class_pixels=json.dumps(label_ops.class_pixels(labels), sort_keys=True),
                      mask_sha256="",
                      mask_source=image.mask_source, mask_source_tool=image.mask_source_tool,
                      mask_source_remarks=image.mask_source_remarks,
                      mask_source_file=image.mask_source_file)
    version.mask_sha256 = label_ops.save(labels, mask_dir(settings, image) / version.mask_file)
    image.versions.append(version)
    return version


def latest(image: Image, status: str) -> Version | None:
    candidates = [v for v in image.versions if v.status == status]
    return max(candidates, key=lambda v: v.number) if candidates else None


def submit(db: Session, settings: Settings, image: Image, user: User, note: str = "") -> Version:
    require_lock(db, image, user)
    if image.status == "submitted":
        raise WorkflowError("This image is already waiting for review.")
    if image.working_revision == 0:
        raise WorkflowError("Save the annotation at least once before submitting it for review.")
    labels = load_working(settings, image)
    for v in image.versions:
        if v.status == "submitted":
            v.status = "superseded"
    version = _snapshot(settings, image, labels, user, "submission", "submitted", note)
    image.status = "submitted"
    # The submitter can no longer edit, so the lease is handed back for the reviewer.
    lock = db.get(ImageLock, image.id)
    if lock is not None:
        db.delete(lock)
    db.commit()
    return version


def withdraw(db: Session, image: Image, user: User) -> Version:
    if image.status != "submitted":
        raise WorkflowError("Only a submitted image can be withdrawn.")
    version = latest(image, "submitted")
    if version is None:  # pragma: no cover - defensive
        raise WorkflowError("No pending submission was found.")
    if version.created_by != user.email and not user.can_review:
        raise WorkflowError("Only the person who submitted (or a reviewer) can withdraw it.", 403)
    version.status = "withdrawn"
    image.status = "in_progress"
    db.commit()
    return version


def review(db: Session, settings: Settings, image: Image, reviewer: User, decision: str,
           comment: str = "") -> Version:
    """Approve or request changes on the pending submission.

    If the reviewer corrected the working copy during review, approval snapshots the
    corrected labels as a new ``reviewer_edit`` version and approves that instead, so
    the approved record always matches exactly what the reviewer saw.
    """
    if not reviewer.can_review:
        raise WorkflowError("Only reviewers and administrators can review.", 403)
    if image.status != "submitted":
        raise WorkflowError("There is no submission waiting for review on this image.")
    pending = latest(image, "submitted")
    if pending is None:  # pragma: no cover - defensive
        raise WorkflowError("No pending submission was found.")
    comment = (comment or "").strip()
    now = utcnow()
    if decision == "request_changes":
        if not comment:
            raise WorkflowError("Tell the annotator what to change: a comment is required.", 422)
        pending.status = "changes_requested"
        pending.reviewed_by, pending.reviewed_at, pending.review_comment = reviewer.email, now, comment
        image.status = "changes_requested"
        db.commit()
        return pending
    if decision != "approve":
        raise WorkflowError("Decision must be 'approve' or 'request_changes'.", 422)

    if pending.created_by == reviewer.email and not settings.allow_self_approval:
        raise WorkflowError("You submitted this annotation, so another reviewer must approve it "
                            "(an administrator can allow self-approval in the configuration).", 403)
    edited = image.working_sha256 is not None and image.working_sha256 != pending.mask_sha256
    if edited:
        require_lock(db, image, reviewer)
        labels = load_working(settings, image)
        pending.status = "superseded"
        pending.reviewed_by, pending.reviewed_at = reviewer.email, now
        pending.review_comment = comment or "Corrected by the reviewer and approved as a new version."
        approved = _snapshot(settings, image, labels, reviewer, "reviewer_edit", "approved",
                             f"Reviewer corrections to v{pending.number}")
    else:
        approved = pending
        approved.status = "approved"
    approved.reviewed_by, approved.reviewed_at = reviewer.email, utcnow()
    approved.review_comment = approved.review_comment or comment
    image.status = "approved"
    db.commit()
    return approved


def restore(db: Session, settings: Settings, image: Image, user: User, version: Version) -> None:
    """Copy an earlier version into the working copy (the history itself is never altered)."""
    labels = load_version(settings, image, version)
    save_working(db, settings, image, user, labels, image.working_revision,
                 origin=f"restored from v{version.number}")
    # The restored pixels carry the provenance frozen with that version, not whatever the
    # working copy happened to say a moment ago.
    image.mask_source = version.mask_source
    image.mask_source_tool = version.mask_source_tool
    image.mask_source_remarks = version.mask_source_remarks
    image.mask_source_file = version.mask_source_file
    db.commit()
