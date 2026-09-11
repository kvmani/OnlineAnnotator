"""Passwords, sessions, one-time codes and role checks."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import smtplib
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta
from email.message import EmailMessage

import bcrypt
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import AuthSession, OtpChallenge, User, as_utc, utcnow

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
MIN_PASSWORD_LENGTH = 8
OTP_TTL_SECONDS = 600
OTP_MAX_ATTEMPTS = 5


class AuthError(Exception):
    """Authentication failure with a message that is safe to show to the user."""


def normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if not EMAIL_RE.match(value):
        raise AuthError("Enter a valid office e-mail address, for example name@lab.example.")
    return value


def check_email_domain(email: str, settings: Settings) -> None:
    domains = settings.allowed_email_domains
    if domains and email.rsplit("@", 1)[-1] not in domains:
        raise AuthError("That e-mail domain is not allowed on this server: use your office address.")


def validate_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Passwords need at least {MIN_PASSWORD_LENGTH} characters.")
    if password.isdigit() or password.isalpha():
        raise AuthError("Use a mix of letters and numbers or symbols in the password.")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw((password or "").encode("utf-8")[:72], password_hash.encode("ascii"))
    except ValueError:
        return False


def generate_temporary_password() -> str:
    """Readable one-time password: four groups, mixed case and digits."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    return "-".join(groups) + str(secrets.randbelow(10))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User, settings: Settings) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    db.add(AuthSession(token_hash=_token_hash(token), user_id=user.id, created_at=now,
                       expires_at=now + timedelta(hours=settings.session_hours), last_seen_at=now))
    user.last_login_at = now
    db.commit()
    return token


def resolve_session(db: Session, token: str | None, settings: Settings) -> User | None:
    """Return the active user for a token, sliding the expiry forward on use."""
    if not token:
        return None
    record = db.get(AuthSession, _token_hash(token))
    if record is None:
        return None
    now = utcnow()
    if as_utc(record.expires_at) < now:
        db.delete(record)
        db.commit()
        return None
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        return None
    # Sliding expiry, written at most once a minute to keep reads cheap.
    if (now - as_utc(record.last_seen_at)).total_seconds() > 60:
        record.last_seen_at = now
        record.expires_at = now + timedelta(hours=settings.session_hours)
        db.commit()
    return user


def end_session(db: Session, token: str | None) -> None:
    if token:
        record = db.get(AuthSession, _token_hash(token))
        if record is not None:
            db.delete(record)
            db.commit()


def end_all_sessions(db: Session, user_id: int) -> None:
    db.query(AuthSession).filter(AuthSession.user_id == user_id).delete()
    db.commit()


class LoginRateLimiter:
    """In-memory sliding-window limiter on failed logins per (email, client)."""

    def __init__(self, limit: int, window_seconds: int = 900) -> None:
        self.limit = limit
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        bucket = self._failures[key]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        return bucket

    def check(self, key: str) -> None:
        with self._lock:
            if len(self._prune(key, time.monotonic())) >= self.limit:
                raise AuthError("Too many failed attempts. Wait 15 minutes or ask an administrator.")

    def fail(self, key: str) -> None:
        with self._lock:
            self._prune(key, time.monotonic()).append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


_dummy_hash: str | None = None


def _timing_dummy_hash() -> str:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(secrets.token_urlsafe(16))
    return _dummy_hash


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.query(User).filter(User.email == normalize_email(email)).first()
    # Always spend bcrypt time so response timing does not reveal whether an account exists.
    ok = verify_password(password, user.password_hash if user else _timing_dummy_hash())
    if user is None or not ok:
        raise AuthError("E-mail or password is not correct.")
    if not user.is_active:
        raise AuthError("This account is disabled. Ask an administrator to re-enable it.")
    return user


# ---------------------------------------------------------------------- one-time codes
def _otp_hash(challenge_id: str, code: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), f"{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


def send_mail(settings: Settings, to_address: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.email.from_address
    msg["To"] = to_address
    msg.set_content(body)
    with smtplib.SMTP(settings.email.smtp_host, settings.email.smtp_port, timeout=15) as smtp:
        if settings.email.use_tls:
            smtp.starttls()
        if settings.email.username:
            smtp.login(settings.email.username, settings.email.password)
        smtp.send_message(msg)


def request_otp(db: Session, settings: Settings, email: str, mailer=None) -> str:
    """Create a login code and e-mail it. Always returns a challenge id (no account enumeration).

    Codes are never returned to the browser. With ``self_registration`` enabled an
    unknown address in an allowed domain gets a new *annotator* account on first
    successful verification only.
    """
    if not settings.otp_login_enabled:
        raise AuthError("One-time e-mail codes are not enabled on this server. Sign in with your password.")
    address = normalize_email(email)
    challenge_id = secrets.token_urlsafe(24)
    user = db.query(User).filter(User.email == address).first()
    if user is None and settings.self_registration:
        try:
            check_email_domain(address, settings)
        except AuthError:
            return challenge_id
        user = User(email=address, full_name=address.split("@")[0].replace(".", " ").title(),
                    role="annotator", password_hash=hash_password(secrets.token_urlsafe(24)),
                    is_active=True)
        db.add(user)
        db.flush()
    if user is None or not user.is_active:
        return challenge_id
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.query(OtpChallenge).filter(OtpChallenge.user_id == user.id, OtpChallenge.used.is_(False)).update(
        {"used": True})
    db.add(OtpChallenge(id=challenge_id, user_id=user.id, code_hash=_otp_hash(challenge_id, code, settings.secret_key),
                        expires_at=utcnow() + timedelta(seconds=OTP_TTL_SECONDS)))
    db.commit()
    (mailer or send_mail)(settings, address, f"{settings.site_name}: your sign-in code",
           f"Your one-time sign-in code is {code}.\n\nIt expires in {OTP_TTL_SECONDS // 60} minutes. "
           "If you did not ask for it, you can ignore this message.")
    return challenge_id


def verify_otp(db: Session, settings: Settings, challenge_id: str, code: str) -> User:
    challenge = db.get(OtpChallenge, challenge_id or "")
    if challenge is None or challenge.used or as_utc(challenge.expires_at) < utcnow():
        raise AuthError("That code has expired or was already used. Request a new one.")
    challenge.attempts += 1
    if challenge.attempts > OTP_MAX_ATTEMPTS:
        challenge.used = True
        db.commit()
        raise AuthError("Too many wrong codes. Request a new one.")
    if not hmac.compare_digest(challenge.code_hash, _otp_hash(challenge.id, (code or "").strip(), settings.secret_key)):
        db.commit()
        raise AuthError("That code is not correct. Check the e-mail and try again.")
    challenge.used = True
    db.commit()
    user = db.get(User, challenge.user_id)
    if user is None or not user.is_active:
        raise AuthError("This account is disabled. Ask an administrator to re-enable it.")
    return user
