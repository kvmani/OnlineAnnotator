"""Shared request dependencies: settings, current user and role guards."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import get_db
from ..models import Image, Project, User
from ..services.auth import resolve_session

SESSION_COOKIE = "oa_session"
CLIENT_HEADER = "X-Requested-With"
CLIENT_HEADER_VALUE = "OnlineAnnotator"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def session_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.cookies.get(SESSION_COOKIE)


def current_user(request: Request, db: Session = Depends(get_db),
                 settings: Settings = Depends(get_settings)) -> User:
    user = resolve_session(db, session_token(request), settings)
    if user is None:
        raise HTTPException(401, "Please sign in to continue.")
    return user


def active_user(user: User = Depends(current_user)) -> User:
    """A signed-in user who has already replaced any temporary password."""
    if user.must_change_password:
        raise HTTPException(403, "Choose a new password before continuing.")
    return user


def reviewer(user: User = Depends(active_user)) -> User:
    if not user.can_review:
        raise HTTPException(403, "This action needs the reviewer or administrator role.")
    return user


def admin(user: User = Depends(active_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "This action needs the administrator role.")
    return user


def get_project(project_id: int, db: Session) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found. It may have been deleted.")
    return project


def get_image(image_id: int, db: Session) -> Image:
    image = db.get(Image, image_id)
    if image is None:
        raise HTTPException(404, "Image not found. It may have been deleted.")
    return image
