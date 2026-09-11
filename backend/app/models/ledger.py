from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text
from ..db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LedgerRecord(Base):
    __tablename__ = "ledger_records"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    user_email = Column(String(255), nullable=False, index=True)
    project_id = Column(Integer, nullable=True, index=True)
    image_id = Column(Integer, nullable=True, index=True)
    summary = Column(String(255), nullable=False)
    details_json = Column(Text, nullable=True)
