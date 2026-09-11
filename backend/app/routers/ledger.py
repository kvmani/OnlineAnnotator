from __future__ import annotations

from typing import Any, Dict, List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.user import User
from ..services.auth_service import get_current_user
from ..services.ledger_service import get_recent_ledger, get_user_resumption_state

router = APIRouter(prefix="/api/v1/ledger", tags=["ledger"])


@router.get("/resume")
def get_resume_state(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Retrieve state to resume the user's latest annotation session."""
    return get_user_resumption_state(db, current_user.email)


@router.get("/recent")
def list_recent_ledger(limit: int = 50, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Retrieve audit and progress ledger history."""
    return get_recent_ledger(db, limit=limit)
