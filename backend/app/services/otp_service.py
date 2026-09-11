from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from ..config import get_config
from ..models.user import LoginOtpChallenge, User

logger = logging.getLogger(__name__)


def _generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_otp(challenge_id: str, user_id: int, otp: str, secret_key: str) -> str:
    material = f"otp:{challenge_id}:{user_id}:{otp}".encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), material, hashlib.sha256).hexdigest()


def _verify_otp_hash(challenge: LoginOtpChallenge, otp: str, secret_key: str) -> bool:
    expected = _hash_otp(challenge.challenge_id, challenge.user_id, otp, secret_key)
    return hmac.compare_digest(expected, challenge.otp_hash)


def send_otp_email(to_email: str, otp: str) -> bool:
    config = get_config()
    email_cfg = config.email
    if not email_cfg.enabled:
        logger.info("[DEV EMAIL OTP] Delivered to %s: Code is %s", to_email, otp)
        return True

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "OnlineAnnotator - Office Email Login OTP"
        msg["From"] = email_cfg.from_address
        msg["To"] = to_email

        text = f"Your OnlineAnnotator verification code is: {otp}\n\nThis code will expire in 10 minutes.\nIf you did not request this code, please ignore this email."
        html = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px; color: #1e293b;">
            <h2 style="color: #4338ca;">OnlineAnnotator Intranet Verification</h2>
            <p>Your one-time login code is:</p>
            <div style="font-size: 32px; font-weight: bold; letter-spacing: 4px; color: #4338ca; padding: 12px; background: #eef2ff; border-radius: 8px; display: inline-block;">
                {otp}
            </div>
            <p style="margin-top: 20px; font-size: 14px; color: #64748b;">
                This code is valid for 10 minutes on your office intranet. Never share this code.
            </p>
        </div>
        """
        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(email_cfg.smtp_host, email_cfg.smtp_port, timeout=10) as server:
            if email_cfg.use_tls:
                server.starttls()
            if email_cfg.username and email_cfg.password:
                server.login(email_cfg.username, email_cfg.password)
            server.send_message(msg)
        return True
    except Exception as e:
        logger.error("Failed to send OTP email to %s: %s", to_email, e)
        # In case SMTP fails, log OTP as fallback so annotator is never locked out
        logger.warning("[FALLBACK OTP] %s : %s", to_email, otp)
        return False


def request_otp_for_user(db: Session, email: str) -> Tuple[str, Optional[str]]:
    """Generate and store OTP challenge. Returns (challenge_id, dev_otp_if_dev_mode)."""
    config = get_config()
    clean_email = email.strip().lower()

    # Find user or auto-register if authorized office domain
    user = db.query(User).filter(User.email == clean_email).first()
    if not user:
        # Check domain restrictions
        allowed_domains = config.security.allowed_email_domains
        user_domain = clean_email.split("@")[-1]
        if allowed_domains and user_domain not in allowed_domains:
            # Generic response to prevent enumeration
            dummy_challenge = secrets.token_urlsafe(24)
            return dummy_challenge, None

        # Auto-create user with a default secure password
        from .auth_service import get_password_hash
        user = User(
            email=clean_email,
            full_name=clean_email.split("@")[0].replace(".", " ").title(),
            role="annotator",
            hashed_password=get_password_hash(secrets.token_urlsafe(16)),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    otp = _generate_otp()
    challenge_id = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=config.security.otp_expire_seconds)
    otp_hash = _hash_otp(challenge_id, user.id, otp, config.security.secret_key)

    # Invalidate previous unexpired challenges for this user
    db.query(LoginOtpChallenge).filter(
        LoginOtpChallenge.user_id == user.id,
        LoginOtpChallenge.is_used == False,
    ).update({"is_used": True})

    challenge = LoginOtpChallenge(
        challenge_id=challenge_id,
        user_id=user.id,
        otp_hash=otp_hash,
        expires_at=expires_at,
        is_used=False,
    )
    db.add(challenge)
    db.commit()

    # Deliver OTP via email or dev fallback
    send_otp_email(user.email, otp)

    dev_otp = otp if not config.email.enabled else None
    return challenge_id, dev_otp


def confirm_otp_challenge(db: Session, challenge_id: str, otp: str) -> User:
    """Validate OTP challenge and return the authenticated User."""
    config = get_config()
    challenge = db.query(LoginOtpChallenge).filter(LoginOtpChallenge.challenge_id == challenge_id).first()

    if not challenge or challenge.is_used:
        raise ValueError("Invalid or expired OTP challenge.")

    now = datetime.now(timezone.utc)
    exp = challenge.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)

    if now > exp:
        challenge.is_used = True
        db.commit()
        raise ValueError("OTP has expired. Please request a new one.")

    challenge.attempts += 1
    if challenge.attempts > 5:
        challenge.is_used = True
        db.commit()
        raise ValueError("Too many incorrect attempts. Please request a new OTP.")

    if not _verify_otp_hash(challenge, otp.strip(), config.security.secret_key):
        db.commit()
        raise ValueError("Incorrect OTP code. Please try again.")

    # Mark challenge as consumed
    challenge.is_used = True
    db.commit()

    user = db.query(User).filter(User.id == challenge.user_id).first()
    if not user or not user.is_active:
        raise ValueError("User account is inactive or not found.")

    return user
