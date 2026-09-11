from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Cookie, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session
import bcrypt

from ..config import get_config
from ..db import get_db
from ..models.user import SessionToken, User

SESSION_COOKIE_NAME = "annotator_session"


def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        pwd_bytes = plain_password.encode("utf-8")[:72]
        hash_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(pwd_bytes, hash_bytes)
    except Exception:
        return False


def create_session_token(db: Session, user: User) -> str:
    config = get_config()
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=config.security.session_expire_days)

    session_record = SessionToken(
        token=token,
        user_id=user.id,
        created_at=now,
        expires_at=expires_at,
        last_activity=now,
    )
    db.add(session_record)
    db.commit()
    return token


def set_auth_cookie(response: Response, token: str):
    config = get_config()
    max_age = config.security.session_expire_days * 86400
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=False,  # Intranet HTTP safe
    )


def clear_auth_cookie(response: Response):
    response.delete_cookie(key=SESSION_COOKIE_NAME)


def get_token_from_request(
    authorization: Optional[str] = Header(None),
    cookie_token: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),
) -> Optional[str]:
    if authorization and authorization.startswith("Bearer "):
        return authorization.split(" ", 1)[1].strip()
    return cookie_token


def get_current_user(
    token: Optional[str] = Depends(get_token_from_request),
    db: Session = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    session_record = db.query(SessionToken).filter(SessionToken.token == token).first()
    if not session_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    now = datetime.now(timezone.utc)
    exp = session_record.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)

    if now > exp:
        db.delete(session_record)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Refresh last activity
    session_record.last_activity = now
    db.commit()

    user = db.query(User).filter(User.id == session_record.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or not found.",
        )

    return user


def require_role(*roles: str):
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles and current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: requires one of {roles} privileges.",
            )
        return current_user
    return role_checker
