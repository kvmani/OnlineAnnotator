"""Append-only activity ledger: database rows plus a JSON-lines mirror on disk."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditEvent, utcnow

logger = logging.getLogger(__name__)
_file_lock = threading.Lock()


def record(
    db: Session,
    audit_file: Path | None,
    user_email: str,
    action: str,
    summary: str,
    *,
    project_id: int | None = None,
    image_id: int | None = None,
    details: dict[str, Any] | None = None,
    commit: bool = True,
) -> AuditEvent:
    """Record one event. The JSONL mirror is best-effort and never blocks the user action."""
    event = AuditEvent(
        timestamp=utcnow(),
        user_email=user_email,
        action=action,
        project_id=project_id,
        image_id=image_id,
        summary=summary,
        details=json.dumps(details or {}, sort_keys=True),
    )
    db.add(event)
    if commit:
        db.commit()
    else:
        db.flush()
    if audit_file is not None:
        try:
            line = json.dumps(event.as_dict(), sort_keys=True)
            with _file_lock:
                audit_file.parent.mkdir(parents=True, exist_ok=True)
                with audit_file.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except OSError as exc:  # pragma: no cover - disk failure path
            logger.warning("Audit mirror write failed: %s", exc)
    return event
