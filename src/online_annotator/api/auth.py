"""Sign-in, sign-out, password change, one-time e-mail codes and user administration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import get_db
from ..models import User
from ..services import audit
from ..services import auth as auth_ops
from . import serialize
from .deps import SESSION_COOKIE, admin, current_user, get_settings, session_token
from .schemas import (
    ChangePasswordBody,
    LoginBody,
    OtpRequestBody,
    OtpVerifyBody,
    UserCreateBody,
    UserUpdateBody,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])


def _client_key(request: Request, email: str) -> str:
    host = request.client.host if request.client else "?"
    return f"{email.strip().lower()}|{host}"


def _start_session(response: Response, db: Session, settings: Settings, user: User) -> dict:
    token = auth_ops.create_session(db, user, settings)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=settings.cookie_secure,
                        max_age=settings.session_hours * 3600, path="/")
    return {"user": serialize.user(user)}


@router.get("/auth/options")
def auth_options(settings: Settings = Depends(get_settings)) -> dict:
    return {"password": True, "otp": settings.otp_login_enabled, "self_registration": settings.self_registration,
            "demo": settings.demo}


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db),
          settings: Settings = Depends(get_settings)) -> dict:
    limiter: auth_ops.LoginRateLimiter = request.app.state.login_limiter
    key = _client_key(request, body.email)
    try:
        limiter.check(key)
        user = auth_ops.authenticate(db, body.email, body.password)
    except auth_ops.AuthError as exc:
        limiter.fail(key)
        raise HTTPException(401, str(exc)) from exc
    limiter.reset(key)
    audit.record(db, settings.audit_file, user.email, "login", f"{user.email} signed in with a password.")
    return _start_session(response, db, settings, user)


@router.post("/auth/otp/request")
def otp_request(body: OtpRequestBody, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    try:
        challenge = auth_ops.request_otp(db, settings, body.email)
    except auth_ops.AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(502, "The e-mail server could not be reached. Sign in with your password or "
                                 "ask an administrator.") from exc
    return {"challenge_id": challenge,
            "message": "If that address has an account, a 6-digit code is on its way. It expires in 10 minutes."}


@router.post("/auth/otp/verify")
def otp_verify(body: OtpVerifyBody, response: Response, db: Session = Depends(get_db),
               settings: Settings = Depends(get_settings)) -> dict:
    try:
        user = auth_ops.verify_otp(db, settings, body.challenge_id, body.code)
    except auth_ops.AuthError as exc:
        raise HTTPException(401, str(exc)) from exc
    audit.record(db, settings.audit_file, user.email, "login", f"{user.email} signed in with an e-mail code.")
    return _start_session(response, db, settings, user)


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    auth_ops.end_session(db, session_token(request))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"user": serialize.user(user)}


@router.post("/auth/change-password")
def change_password(body: ChangePasswordBody, request: Request, response: Response,
                    user: User = Depends(current_user), db: Session = Depends(get_db),
                    settings: Settings = Depends(get_settings)) -> dict:
    if not auth_ops.verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Your current password is not correct.")
    if body.new_password == body.current_password:
        raise HTTPException(400, "Choose a password different from the current one.")
    try:
        auth_ops.validate_password(body.new_password)
    except auth_ops.AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    user.password_hash = auth_ops.hash_password(body.new_password)
    user.must_change_password = False
    auth_ops.end_all_sessions(db, user.id)
    audit.record(db, settings.audit_file, user.email, "password_changed", f"{user.email} changed their password.")
    return _start_session(response, db, settings, user)


# ------------------------------------------------------------------------------ users
@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    users = db.query(User).order_by(User.full_name).all()
    return {"users": [serialize.user(u) for u in users]}


@router.post("/users")
def create_user(body: UserCreateBody, db: Session = Depends(get_db), actor: User = Depends(admin),
                settings: Settings = Depends(get_settings)) -> dict:
    try:
        email = auth_ops.normalize_email(body.email)
        auth_ops.check_email_domain(email, settings)
        if body.password:
            auth_ops.validate_password(body.password)
    except auth_ops.AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, f"{email} already has an account.")
    password = body.password or auth_ops.generate_temporary_password()
    user = User(email=email, full_name=body.full_name.strip(), role=body.role,
                password_hash=auth_ops.hash_password(password), must_change_password=True)
    db.add(user)
    db.commit()
    audit.record(db, settings.audit_file, actor.email, "user_created", f"Created {body.role} account {email}.")
    return {"user": serialize.user(user), "temporary_password": password}


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdateBody, db: Session = Depends(get_db), actor: User = Depends(admin),
                settings: Settings = Depends(get_settings)) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found.")
    if user.id == actor.id and (body.role not in (None, "admin") or body.is_active is False):
        raise HTTPException(400, "You cannot remove your own administrator access. Ask another administrator.")
    changes = body.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(user, key, value)
    if body.is_active is False:
        auth_ops.end_all_sessions(db, user.id)
    db.commit()
    audit.record(db, settings.audit_file, actor.email, "user_updated", f"Updated {user.email}: {changes}.")
    return {"user": serialize.user(user)}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, db: Session = Depends(get_db), actor: User = Depends(admin),
                   settings: Settings = Depends(get_settings)) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found.")
    password = auth_ops.generate_temporary_password()
    user.password_hash = auth_ops.hash_password(password)
    user.must_change_password = True
    auth_ops.end_all_sessions(db, user.id)
    audit.record(db, settings.audit_file, actor.email, "password_reset", f"Reset the password of {user.email}.")
    return {"user": serialize.user(user), "temporary_password": password}
