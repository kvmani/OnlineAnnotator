from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Optional
import yaml
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 5070
    base_path: str = ""
    cors_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:5070",
            "http://127.0.0.1:5070",
            "http://localhost:5000",
            "http://127.0.0.1:5000",
        ]
    )


class SecurityConfig(BaseModel):
    secret_key: str = "online-annotator-secure-intranet-secret-key-change-in-production"
    session_expire_days: int = 7
    otp_expire_seconds: int = 600
    lock_lease_seconds: int = 600
    allowed_email_domains: List[str] = Field(default_factory=list)


class DatabaseConfig(BaseModel):
    url: str = "sqlite:///data/annotator.sqlite3"


class StorageConfig(BaseModel):
    data_dir: str = "data"
    images_dir: str = "data/images"
    masks_dir: str = "data/masks"
    exports_dir: str = "data/exports"
    ledger_file: str = "data/ledger.json"


class EmailConfig(BaseModel):
    enabled: bool = False
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 25
    use_tls: bool = False
    username: str = ""
    password: str = ""
    from_address: str = "annotator-noreply@intranet.local"


class DefaultClassConfig(BaseModel):
    name: str
    color_hex: str
    class_index: int
    description: str = ""


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    default_classes: List[DefaultClassConfig] = Field(default_factory=list)


_CONFIG_INSTANCE: Optional[AppConfig] = None


def find_config_path() -> Path:
    env_path = os.getenv("ONLINE_ANNOTATOR_CONFIG")
    if env_path and Path(env_path).exists():
        return Path(env_path)

    # Look in working directory and parent directories
    candidates = [
        Path("config.yml"),
        Path("../config.yml"),
        Path(__file__).resolve().parents[2] / "config.yml",
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    return Path("config.yml")


def load_config() -> AppConfig:
    global _CONFIG_INSTANCE
    if _CONFIG_INSTANCE is not None:
        return _CONFIG_INSTANCE

    path = find_config_path()
    data: dict[str, Any] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    config = AppConfig(**data)

    # Environment variable overrides
    port_env = os.getenv("ONLINE_ANNOTATOR_PORT")
    if port_env:
        try:
            config.server.port = int(port_env)
        except ValueError:
            pass

    host_env = os.getenv("ONLINE_ANNOTATOR_HOST")
    if host_env:
        config.server.host = host_env

    secret_env = os.getenv("ONLINE_ANNOTATOR_SECRET_KEY")
    if secret_env:
        config.security.secret_key = secret_env

    # Ensure storage paths exist
    for p in [config.storage.data_dir, config.storage.images_dir, config.storage.masks_dir, config.storage.exports_dir]:
        Path(p).mkdir(parents=True, exist_ok=True)

    _CONFIG_INSTANCE = config
    return config


def get_config() -> AppConfig:
    return load_config()
