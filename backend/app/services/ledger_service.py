from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from ..config import get_config
from ..models.annotation import AnnotationDraft
from ..models.image import MicrographImage
from ..models.ledger import LedgerRecord
from ..models.dataset import DatasetProject

logger = logging.getLogger(__name__)


def record_ledger_event(
    db: Session,
    event_type: str,
    user_email: str,
    summary: str,
    project_id: Optional[int] = None,
    image_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> LedgerRecord:
    """Record an event in the database ledger and append to data/ledger.json mirror."""
    now = datetime.now(timezone.utc)
    details_str = json.dumps(details or {})

    record = LedgerRecord(
        timestamp=now,
        event_type=event_type,
        user_email=user_email,
        project_id=project_id,
        image_id=image_id,
        summary=summary,
        details_json=details_str,
    )
    db.add(record)
    db.commit()

    # Mirror to data/ledger.json
    try:
        config = get_config()
        ledger_path = Path(config.storage.ledger_file)
        ledger_path.parent.mkdir(parents=True, exist_ok=True)

        log_entry = {
            "id": record.id,
            "timestamp": now.isoformat(),
            "event_type": event_type,
            "user_email": user_email,
            "project_id": project_id,
            "image_id": image_id,
            "summary": summary,
            "details": details or {},
        }

        # Append JSON line or maintain list
        existing = []
        if ledger_path.exists():
            try:
                with open(ledger_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []
        existing.append(log_entry)
        # Keep last 500 records in JSON mirror to prevent unbounded growth
        if len(existing) > 500:
            existing = existing[-500:]
        with open(ledger_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        logger.warning("Failed to update ledger mirror file: %s", e)

    return record


def get_user_resumption_state(db: Session, user_email: str) -> Dict[str, Any]:
    """
    Retrieve the user's latest active project, image, and draft
    so they can pick up right where they left off.
    """
    draft = (
        db.query(AnnotationDraft)
        .filter(AnnotationDraft.user_email == user_email)
        .order_by(AnnotationDraft.updated_at.desc())
        .first()
    )

    if not draft:
        # Fall back to the most recently created or updated image
        image = db.query(MicrographImage).order_by(MicrographImage.updated_at.desc()).first()
        if not image:
            return {"can_resume": False}
        return {
            "can_resume": True,
            "project_id": image.project_id,
            "image_id": image.id,
            "filename": image.filename,
            "zoom_level": 1.0,
            "pan_x": 0.0,
            "pan_y": 0.0,
            "has_draft": False,
        }

    image = db.query(MicrographImage).filter(MicrographImage.id == draft.image_id).first()
    if not image:
        return {"can_resume": False}

    return {
        "can_resume": True,
        "project_id": image.project_id,
        "image_id": image.id,
        "filename": image.filename,
        "zoom_level": draft.zoom_level,
        "pan_x": draft.pan_x,
        "pan_y": draft.pan_y,
        "active_class_index": draft.active_class_index,
        "active_tool": draft.active_tool,
        "brush_size": draft.brush_size,
        "has_draft": True,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }


def get_recent_ledger(db: Session, limit: int = 50) -> List[Dict[str, Any]]:
    records = db.query(LedgerRecord).order_by(LedgerRecord.timestamp.desc()).limit(limit).all()
    results = []
    for r in records:
        details = {}
        if r.details_json:
            try:
                details = json.loads(r.details_json)
            except Exception:
                pass
        results.append({
            "id": r.id,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "event_type": r.event_type,
            "user_email": r.user_email,
            "project_id": r.project_id,
            "image_id": r.image_id,
            "summary": r.summary,
            "details": details,
        })
    return results
