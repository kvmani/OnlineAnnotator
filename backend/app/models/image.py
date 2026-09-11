from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from ..db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MicrographImage(Base):
    __tablename__ = "micrograph_images"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("dataset_projects.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    width = Column(Integer, nullable=False, default=0)
    height = Column(Integer, nullable=False, default=0)
    channels = Column(Integer, nullable=False, default=3)
    checksum_sha256 = Column(String(64), nullable=False, index=True)
    status = Column(String(50), default="unannotated", nullable=False, index=True)  # unannotated, in_progress, under_review, completed
    assigned_to = Column(String(255), nullable=True)  # user email
    split_assignment = Column(String(20), default="train", nullable=False)  # train, val, test
    metadata_json = Column(Text, nullable=True)  # material, magnification, scale, notes
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    project = relationship("DatasetProject", back_populates="images")
    lock = relationship("ImageLock", back_populates="image", uselist=False, cascade="all, delete-orphan")
    draft = relationship("AnnotationDraft", back_populates="image", uselist=False, cascade="all, delete-orphan")
    versions = relationship("AnnotationVersion", back_populates="image", cascade="all, delete-orphan", order_by="AnnotationVersion.version_number")
