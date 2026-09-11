from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from ..db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AnnotationDraft(Base):
    __tablename__ = "annotation_drafts"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(Integer, ForeignKey("micrograph_images.id"), unique=True, nullable=False)
    user_email = Column(String(255), nullable=False)
    vector_data = Column(Text, nullable=False, default="[]")  # JSON string of polygons, strokes, shapes
    mask_path = Column(String(500), nullable=True)  # Path to generated raster mask cache
    zoom_level = Column(Float, default=1.0, nullable=False)
    pan_x = Column(Float, default=0.0, nullable=False)
    pan_y = Column(Float, default=0.0, nullable=False)
    active_class_index = Column(Integer, default=1, nullable=False)
    active_tool = Column(String(50), default="brush", nullable=False)
    brush_size = Column(Integer, default=10, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    image = relationship("MicrographImage", back_populates="draft")


class AnnotationVersion(Base):
    __tablename__ = "annotation_versions"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(Integer, ForeignKey("micrograph_images.id"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    created_by = Column(String(255), nullable=False)
    vector_data = Column(Text, nullable=False)
    mask_path = Column(String(500), nullable=False)  # Stored raster PNG
    status = Column(String(50), default="draft", nullable=False)  # draft, submitted_for_review, approved, rejected
    review_comment = Column(Text, nullable=True)
    reviewed_by = Column(String(255), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    image = relationship("MicrographImage", back_populates="versions")
