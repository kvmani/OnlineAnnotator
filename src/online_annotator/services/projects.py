"""Project, class and image management."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import Settings
from ..models import IMAGE_STATUSES, Image, LabelClass, Project, User, as_utc
from . import access, audit, imaging, workflow

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
DEFAULT_COLORS = ["#FF0000", "#2F80ED", "#27AE60", "#F2C94C", "#9B51E0", "#F2994A", "#56CCF2", "#EB5757"]


class ProjectError(ValueError):
    """Invalid project operation; message is safe to show."""


def validate_class(index: int, name: str, color: str) -> None:
    if not 1 <= index <= 255:
        raise ProjectError("Class numbers run from 1 to 255 (0 is reserved for background).")
    if not name.strip():
        raise ProjectError("Every class needs a name.")
    if not HEX_RE.match(color or ""):
        raise ProjectError("Class colours are written as #RRGGBB, for example #FF0000.")


def status_counts(project: Project) -> dict[str, int]:
    counts = {s: 0 for s in IMAGE_STATUSES}
    for image in project.images:
        counts[image.status] = counts.get(image.status, 0) + 1
    counts["total"] = len(project.images)
    return counts


def unique_stem(db: Session, project: Project, filename: str) -> str:
    stem = imaging.safe_stem(filename)
    existing = {s for (s,) in db.query(Image.stem).filter(Image.project_id == project.id)}
    candidate, n = stem, 2
    while candidate in existing:
        candidate = f"{stem}-{n}"
        n += 1
    return candidate


def add_uploaded_image(db: Session, settings: Settings, project: Project, user: User, raw: bytes,
                       filename: str, split: str = "unassigned") -> tuple[Image | None, str]:
    """Ingest one upload. Returns (image, message); image is None for duplicates."""
    info = imaging.ingest(raw, filename, settings.max_image_megapixels)
    duplicate = db.query(Image).filter(Image.project_id == project.id, Image.sha256 == info.sha256).first()
    if duplicate is not None:
        return None, f"{filename}: identical to {duplicate.original_filename}, already in this project."
    ext = Path(filename).suffix.lower()
    image = Image(project_id=project.id, original_filename=Path(filename).name,
                  stem=unique_stem(db, project, filename), stored_name="pending", display_name="pending",
                  sha256=info.sha256, width=info.width, height=info.height, source_mode=info.source_mode,
                  conversion_note=info.conversion_note, split=split if split in ("train", "val", "test") else
                  "unassigned", uploaded_by=user.email)
    db.add(image)
    db.flush()
    image.stored_name = f"{image.id}_original{ext}"
    image.display_name = f"{image.id}_display.png" if info.needs_display_copy else image.stored_name
    folder = workflow.image_dir(settings, image)
    folder.mkdir(parents=True, exist_ok=True)
    workflow.original_path(settings, image).write_bytes(raw)
    if info.display_png is not None:
        workflow.display_path(settings, image).write_bytes(info.display_png)
    workflow.thumb_path(settings, image).write_bytes(info.thumbnail_jpeg)
    db.commit()
    note = f" ({info.conversion_note})" if info.conversion_note else ""
    return image, f"{filename}: added as {image.stem}{note}"


def delete_image(db: Session, settings: Settings, image: Image, user: User) -> None:
    project_id, name = image.project_id, image.original_filename
    for path in (workflow.original_path(settings, image), workflow.display_path(settings, image),
                 workflow.thumb_path(settings, image)):
        path.unlink(missing_ok=True)
    shutil.rmtree(workflow.mask_dir(settings, image), ignore_errors=True)
    db.delete(image)
    db.commit()
    audit.record(db, settings.audit_file, user.email, "image_deleted", f"Deleted image {name}.",
                 project_id=project_id)


def review_queue(settings: Settings, project: Project, user: User) -> list[Image]:
    """Submissions this user may review, oldest submission first.

    Their own submissions are left out unless ``allow_self_approval`` is set, so nobody is
    ever handed their own work as something to approve.
    """
    ranked = []
    for img in project.images:
        pending = workflow.latest(img, "submitted") if img.status == "submitted" else None
        if pending is not None and access.may_review(settings, user, pending.created_by):
            ranked.append((as_utc(pending.created_at), img.id, img))
    return [img for _, _, img in sorted(ranked, key=lambda t: (t[0], t[1]))]


def annotate_queue(project: Project, user: User, after_id: int | None = None) -> list[Image]:
    """Images needing annotation, in the order this user should get them.

    My returned work, then my work in progress, then new images assigned to me, new
    unassigned images, and finally returned work nobody is assigned to.
    """
    images = sorted(project.images, key=lambda i: i.id)
    if after_id is not None:
        images = [i for i in images if i.id > after_id] + [i for i in images if i.id <= after_id]

    def mine(img: Image) -> bool:
        return img.assigned_to == user.email or img.working_updated_by == user.email

    tiers = [
        [i for i in images if i.status == "changes_requested" and mine(i)],
        [i for i in images if i.status == "in_progress" and mine(i)],
        [i for i in images if i.status == "new" and i.assigned_to == user.email],
        [i for i in images if i.status == "new" and not i.assigned_to],
        [i for i in images if i.status == "changes_requested" and not i.assigned_to],
    ]
    return [img for tier in tiers for img in tier]


def queue_counts(settings: Settings, project: Project, user: User) -> dict[str, int]:
    """How much work waits for this user in each mode (edit leases are not considered)."""
    own_pending = 0
    for img in project.images:
        pending = workflow.latest(img, "submitted") if img.status == "submitted" else None
        if pending is not None and pending.created_by == user.email:
            own_pending += 1
    return {"annotate": len(annotate_queue(project, user)), "review": len(review_queue(settings, project, user)),
            "own_pending": own_pending}


def next_image(db: Session, settings: Settings, project: Project, user: User, after_id: int | None = None,
               mode: str = "annotate") -> Image | None:
    """The image a user should open next in ``mode``; images someone else is editing are skipped."""

    def free(img: Image) -> bool:
        state = workflow.lock_state(db, img, user)
        return not state.locked or state.by_me

    if mode == access.REVIEW:
        candidates = [i for i in review_queue(settings, project, user) if i.id != after_id]
    else:
        candidates = annotate_queue(project, user, after_id)
    return next((img for img in candidates if free(img)), None)


def add_class(db: Session, project: Project, name: str, color: str | None, description: str,
              index: int | None = None) -> LabelClass:
    used = {c.index for c in project.classes}
    index = index or next(i for i in range(1, 256) if i not in used)
    if index in used:
        raise ProjectError(f"Class number {index} is already used in this project.")
    color = color or DEFAULT_COLORS[(index - 1) % len(DEFAULT_COLORS)]
    validate_class(index, name, color)
    if name.strip().lower() in {c.name.lower() for c in project.classes}:
        raise ProjectError(f"A class called {name.strip()!r} already exists.")
    label = LabelClass(index=index, name=name.strip(), color=color.upper(), description=description.strip())
    project.classes.append(label)
    db.commit()
    return label


def class_in_use(project: Project, index: int) -> bool:
    key = str(index)
    for image in project.images:
        if image.class_pixels.get(key):
            return True
        if any(v.pixels.get(key) for v in image.versions):
            return True
    return False
