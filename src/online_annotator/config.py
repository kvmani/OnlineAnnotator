"""Configuration: built-in defaults < YAML file < ``ONLINE_ANNOTATOR_*`` environment variables.

Every setting has a safe default so ``online-annotator serve`` works with no file at
all. Nested keys are overridden with a double underscore, for example
``ONLINE_ANNOTATOR_EMAIL__SMTP_HOST=mail.intranet``. Lists are given as JSON
(``ONLINE_ANNOTATOR_ALLOWED_EMAIL_DOMAINS=["barc.gov.in"]``).
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

ENV_PREFIX = "ONLINE_ANNOTATOR_"
CONFIG_ENV = ENV_PREFIX + "CONFIG"


class EmailSettings(BaseModel):
    """Optional internal SMTP relay used for one-time login codes."""

    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 25
    use_tls: bool = False
    username: str = ""
    password: str = ""
    from_address: str = "online-annotator@intranet.local"


class Settings(BaseModel):
    """All runtime settings. See ``config.example.yml`` for documentation of each key."""

    host: str = "127.0.0.1"
    port: int = 5070
    data_dir: Path = Path("data")
    database_url: str | None = None
    secret_key: str | None = None

    session_hours: int = Field(default=12, ge=1, le=24 * 30)
    lock_lease_seconds: int = Field(default=300, ge=30, le=3600)
    max_upload_mb: int = Field(default=200, ge=1)
    max_image_megapixels: float = Field(default=80.0, gt=0)
    login_attempts_per_15min: int = Field(default=10, ge=3)

    allow_self_approval: bool = False
    self_registration: bool = False
    allowed_email_domains: list[str] = Field(default_factory=list)
    cookie_secure: bool = False

    portal_url: str | None = None
    feedback_url: str | None = None
    site_name: str = "Online Annotator"

    demo: bool = False
    email: EmailSettings = Field(default_factory=EmailSettings)

    @field_validator("allowed_email_domains")
    @classmethod
    def _lower_domains(cls, value: list[str]) -> list[str]:
        return [d.strip().lower().lstrip("@") for d in value if d.strip()]

    # ----------------------------------------------------------------- derived paths
    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def masks_dir(self) -> Path:
        return self.data_dir / "masks"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def audit_file(self) -> Path:
        return self.data_dir / "audit" / "audit.jsonl"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'online_annotator.sqlite3').as_posix()}"

    @property
    def otp_login_enabled(self) -> bool:
        return self.email.enabled and bool(self.email.smtp_host)

    def prepare_storage(self) -> None:
        """Create the data directories and resolve a persistent secret key."""
        for folder in (self.data_dir, self.images_dir, self.masks_dir, self.exports_dir,
                       self.audit_file.parent):
            folder.mkdir(parents=True, exist_ok=True)
        if not self.secret_key:
            key_file = self.data_dir / "secret_key"
            if key_file.exists():
                self.secret_key = key_file.read_text(encoding="utf-8").strip()
            else:
                self.secret_key = secrets.token_urlsafe(48)
                key_file.write_text(self.secret_key, encoding="utf-8")
                try:
                    key_file.chmod(0o600)
                except OSError:  # pragma: no cover - Windows ACLs
                    pass


def _coerce(raw: str) -> Any:
    """Interpret an environment string as JSON when possible, else as text."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw


def _env_overrides(environ: dict[str, str]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for key, raw in environ.items():
        if not key.startswith(ENV_PREFIX) or key == CONFIG_ENV:
            continue
        path = key[len(ENV_PREFIX):].lower().split("__")
        target = overrides
        for part in path[:-1]:
            target = target.setdefault(part, {})
        value = _coerce(raw)
        # Keep secrets and hostnames as strings even if they look numeric.
        if path[-1] in {"secret_key", "password", "username", "smtp_host", "host", "portal_url",
                        "feedback_url", "database_url", "site_name", "from_address"}:
            value = raw
        target[path[-1]] = value
    return overrides


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(config_path: str | Path | None = None, environ: dict[str, str] | None = None,
                  **overrides: Any) -> Settings:
    """Build :class:`Settings` from file, environment and explicit keyword overrides."""
    environ = dict(os.environ if environ is None else environ)
    data: dict[str, Any] = {}
    path = Path(config_path) if config_path else None
    if path is None and environ.get(CONFIG_ENV):
        path = Path(environ[CONFIG_ENV])
    if path is None and Path("config.yml").exists():
        path = Path("config.yml")
    if path is not None:
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data = _deep_merge(data, _env_overrides(environ))
    data = _deep_merge(data, {k: v for k, v in overrides.items() if v is not None})
    return Settings(**data)
