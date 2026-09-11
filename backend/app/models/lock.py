from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from ..db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ImageLock(Base):
    __tablename__ = "image_locks"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(Integer, ForeignKey("micrograph_images.id"), unique=True, nullable=False)
    user_email = Column(String(255), nullable=False)
    acquired_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    client_heartbeat = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    image = relationship("MicrographImage", back_populates="lock")

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > (self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc))
