from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from ..config import get_config
from ..models.image import MicrographImage
from ..models.lock import ImageLock
from ..schemas.image import ImageLockInfo


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def get_lock_info(db: Session, image_id: int, current_user_email: Optional[str] = None) -> ImageLockInfo:
    lock = db.query(ImageLock).filter(ImageLock.image_id == image_id).first()
    if not lock:
        return ImageLockInfo(is_locked=False)

    now = _utcnow()
    exp = _to_utc(lock.expires_at)
    if now > exp:
        # Lock has expired, cleanly delete it
        db.delete(lock)
        db.commit()
        return ImageLockInfo(is_locked=False)

    remaining = max(0, int((exp - now).total_seconds()))
    locked_by_me = (current_user_email is not None and lock.user_email.lower() == current_user_email.lower())

    return ImageLockInfo(
        is_locked=True,
        locked_by=lock.user_email,
        locked_by_me=locked_by_me,
        expires_at=exp,
        seconds_remaining=remaining,
    )


def acquire_or_renew_lock(db: Session, image_id: int, user_email: str) -> Tuple[bool, str, Optional[datetime], int]:
    """
    Acquire or renew an editing lease lock.
    Returns (success, message, expires_at, lease_seconds).
    """
    config = get_config()
    lease_seconds = config.security.lock_lease_seconds
    now = _utcnow()
    expires_at = now + timedelta(seconds=lease_seconds)

    lock = db.query(ImageLock).filter(ImageLock.image_id == image_id).first()

    if lock:
        lock_exp = _to_utc(lock.expires_at)
        if now > lock_exp:
            # Stale lock, can be claimed
            lock.user_email = user_email
            lock.acquired_at = now
            lock.expires_at = expires_at
            lock.client_heartbeat = now
            db.commit()
            return True, "Lock acquired (previous lock had expired).", expires_at, lease_seconds

        if lock.user_email.lower() == user_email.lower():
            # Renew existing lock
            lock.expires_at = expires_at
            lock.client_heartbeat = now
            db.commit()
            return True, "Lock lease renewed successfully.", expires_at, lease_seconds

        # Locked by someone else
        remaining = int((lock_exp - now).total_seconds())
        return False, f"Image is currently locked by {lock.user_email} ({remaining}s remaining).", lock_exp, remaining

    # Create new lock
    new_lock = ImageLock(
        image_id=image_id,
        user_email=user_email,
        acquired_at=now,
        expires_at=expires_at,
        client_heartbeat=now,
    )
    db.add(new_lock)
    db.commit()
    return True, "Lock lease acquired successfully.", expires_at, lease_seconds


def release_lock(db: Session, image_id: int, user_email: str, force: bool = False) -> Tuple[bool, str]:
    lock = db.query(ImageLock).filter(ImageLock.image_id == image_id).first()
    if not lock:
        return True, "No active lock found."

    if not force and lock.user_email.lower() != user_email.lower():
        return False, f"Cannot release lock held by {lock.user_email}."

    db.delete(lock)
    db.commit()
    return True, "Lock released successfully."


def cleanup_expired_locks(db: Session) -> int:
    now = _utcnow()
    # Query locks whose expires_at is before now
    expired = [l for l in db.query(ImageLock).all() if _to_utc(l.expires_at) < now]
    count = len(expired)
    for l in expired:
        db.delete(l)
    if count > 0:
        db.commit()
    return count
