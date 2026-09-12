"""ORM models.

The canonical annotation of an image is a *label map*: an 8-bit raster the size of
the image in which 0 is background and 1..255 are the project's class indices. The
working copy lives on disk as ``masks/<image_id>/working.png``; every submission
freezes an immutable :class:`Version` with its own PNG and SHA-256.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

ROLES = ("annotator", "reviewer", "admin")
IMAGE_STATUSES = ("new", "in_progress", "submitted", "changes_requested", "approved")
SPLITS = ("unassigned", "train", "val", "test")
VERSION_STATUSES = ("submitted", "approved", "changes_requested", "withdrawn", "superseded")

# Where the label map originally came from. "manual" = drawn from scratch in this tool;
# "imported" = an externally produced mask (another segmentation tool, a model prediction)
# was loaded as the starting point and then corrected here. The distinction is scientific
# provenance, so it is sticky: correcting an imported mask by hand never makes it "manual".
MASK_SOURCES = ("manual", "imported")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; every stored timestamp is UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="annotator")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def can_review(self) -> bool:
        return self.role in ("reviewer", "admin")

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class AuthSession(Base):
    """A login session. Only the SHA-256 of the bearer token is stored."""

    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship()


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    guidelines: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    classes: Mapped[list[LabelClass]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="LabelClass.index"
    )
    images: Mapped[list[Image]] = relationship(back_populates="project", cascade="all, delete-orphan")


class LabelClass(Base):
    __tablename__ = "label_classes"
    __table_args__ = (UniqueConstraint("project_id", "index", name="uq_class_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(String(7))
    description: Mapped[str] = mapped_column(Text, default="")

    project: Mapped[Project] = relationship(back_populates="classes")


class Image(Base):
    __tablename__ = "images"
    __table_args__ = (
        UniqueConstraint("project_id", "sha256", name="uq_image_sha"),
        UniqueConstraint("project_id", "stem", name="uq_image_stem"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stem: Mapped[str] = mapped_column(String(200))
    stored_name: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    source_mode: Mapped[str] = mapped_column(String(20), default="")
    conversion_note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    split: Mapped[str] = mapped_column(String(12), default="unassigned")
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    uploaded_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Working copy of the label map.
    working_revision: Mapped[int] = mapped_column(Integer, default=0)
    working_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    working_class_pixels: Mapped[str] = mapped_column(Text, default="{}")
    working_updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    working_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    working_origin: Mapped[str] = mapped_column(String(255), default="")

    # Provenance of the working label map (see MASK_SOURCES). Sticky across hand-correction.
    mask_source: Mapped[str] = mapped_column(String(20), default="manual")
    mask_source_tool: Mapped[str] = mapped_column(String(200), default="")
    mask_source_remarks: Mapped[str] = mapped_column(Text, default="")
    mask_source_file: Mapped[str] = mapped_column(String(255), default="")
    mask_imported_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mask_imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="images")
    versions: Mapped[list[Version]] = relationship(
        back_populates="image", cascade="all, delete-orphan", order_by="Version.number"
    )
    lock: Mapped[ImageLock | None] = relationship(back_populates="image", cascade="all, delete-orphan")

    @property
    def class_pixels(self) -> dict[str, int]:
        return json.loads(self.working_class_pixels or "{}")


class ImageLock(Base):
    """Exclusive, renewable editing lease on one image."""

    __tablename__ = "image_locks"

    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), primary_key=True)
    user_email: Mapped[str] = mapped_column(String(255))
    user_name: Mapped[str] = mapped_column(String(255), default="")
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    image: Mapped[Image] = relationship(back_populates="lock")


class Version(Base):
    """Immutable snapshot of a label map, created on submission (or reviewer-edited approval)."""

    __tablename__ = "versions"
    __table_args__ = (UniqueConstraint("image_id", "number", name="uq_version_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    mask_file: Mapped[str] = mapped_column(String(255))
    mask_sha256: Mapped[str] = mapped_column(String(64))
    class_pixels: Mapped[str] = mapped_column(Text, default="{}")
    kind: Mapped[str] = mapped_column(String(20), default="submission")
    status: Mapped[str] = mapped_column(String(20), default="submitted", index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, default="")

    # Frozen copy of the provenance the working map carried when this version was cut,
    # so an immutable submission can always answer "was this hand-drawn or imported?".
    mask_source: Mapped[str] = mapped_column(String(20), default="manual")
    mask_source_tool: Mapped[str] = mapped_column(String(200), default="")
    mask_source_remarks: Mapped[str] = mapped_column(Text, default="")
    mask_source_file: Mapped[str] = mapped_column(String(255), default="")

    image: Mapped[Image] = relationship(back_populates="versions")

    @property
    def pixels(self) -> dict[str, int]:
        return json.loads(self.class_pixels or "{}")


class AuditEvent(Base):
    """Append-only activity record, mirrored to ``audit/audit.jsonl``."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_email: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    image_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[str] = mapped_column(Text, default="{}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": as_utc(self.timestamp).isoformat(),
            "user_email": self.user_email,
            "action": self.action,
            "project_id": self.project_id,
            "image_id": self.image_id,
            "summary": self.summary,
            "details": json.loads(self.details or "{}"),
        }


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    options: Mapped[str] = mapped_column(Text, default="{}")
    summary: Mapped[str] = mapped_column(Text, default="{}")
