from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from ..db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DatasetProject(Base):
    __tablename__ = "dataset_projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    task_type = Column(String(50), default="semantic_segmentation", nullable=False)
    created_by = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    classes = relationship("DatasetClass", back_populates="project", cascade="all, delete-orphan", order_by="DatasetClass.class_index")
    images = relationship("MicrographImage", back_populates="project", cascade="all, delete-orphan")


class DatasetClass(Base):
    __tablename__ = "dataset_classes"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("dataset_projects.id"), nullable=False)
    class_index = Column(Integer, nullable=False)  # 1, 2, 3 ... (0 is background)
    name = Column(String(100), nullable=False)
    color_hex = Column(String(16), nullable=False)  # e.g. #FF0000
    description = Column(String(255), nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)

    project = relationship("DatasetProject", back_populates="classes")
