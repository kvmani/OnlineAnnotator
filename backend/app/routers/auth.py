from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.user import User
from ..schemas.auth import (
    ChangePasswordRequest,
    EmailOtpConfirmRequest,
    EmailOtpRequest,
    EmailOtpRequestResponse,
    LoginRequest,
    LoginResponse,
    RegisterUserRequest,
    UserProfileResponse,
)
from ..services.auth_service import (
    clear_auth_cookie,
    create_session_token,
    get_current_user,
    get_password_hash,
    set_auth_cookie,
    verify_password,
)
from ..services.ledger_service import record_ledger_event
from ..services.otp_service import confirm_otp_challenge, request_otp_for_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login_with_password(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """Authenticate using stored office email and password."""
    clean_email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == clean_email).first()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid office email or password.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Please contact your intranet administrator.",
        )

    token = create_session_token(db, user)
    set_auth_cookie(response, token)
    record_ledger_event(db, "LOGIN_PASSWORD", user.email, f"User {user.email} logged in via password.")

    return LoginResponse(
        token=token,
        user=UserProfileResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
        ),
        message="Login successful.",
    )


@router.post("/email-otp/request", response_model=EmailOtpRequestResponse)
def request_email_otp(payload: EmailOtpRequest, db: Session = Depends(get_db)):
    """Request a 6-digit login OTP delivered to office email."""
    challenge_id, dev_otp = request_otp_for_user(db, payload.email)
    record_ledger_event(db, "OTP_REQUESTED", payload.email, f"OTP requested for {payload.email}.")

    return EmailOtpRequestResponse(
        challenge_id=challenge_id,
        message="If your email is authorized, an OTP has been sent to your office inbox.",
        expires_in_seconds=600,
        dev_otp=dev_otp,
    )


@router.post("/email-otp/confirm", response_model=LoginResponse)
def confirm_email_otp(payload: EmailOtpConfirmRequest, response: Response, db: Session = Depends(get_db)):
    """Confirm 6-digit OTP and establish user session."""
    try:
        user = confirm_otp_challenge(db, payload.challenge_id, payload.otp)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    token = create_session_token(db, user)
    set_auth_cookie(response, token)
    record_ledger_event(db, "LOGIN_OTP", user.email, f"User {user.email} logged in via email OTP.")

    return LoginResponse(
        token=token,
        user=UserProfileResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
        ),
        message="Email OTP verified successfully.",
    )


@router.get("/me", response_model=UserProfileResponse)
def get_current_profile(current_user: User = Depends(get_current_user)):
    """Retrieve active authenticated user details."""
    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
    )


@router.post("/logout")
def logout(response: Response, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Logout current user and invalidate cookie."""
    clear_auth_cookie(response)
    record_ledger_event(db, "LOGOUT", current_user.email, f"User {current_user.email} logged out.")
    return {"message": "Logged out successfully."}


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update stored credentials."""
    if not verify_password(payload.old_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password incorrect.")

    current_user.hashed_password = get_password_hash(payload.new_password)
    current_user.needs_password_change = False
    db.commit()
    record_ledger_event(db, "PASSWORD_CHANGED", current_user.email, "Password updated successfully.")
    return {"message": "Password changed successfully."}
