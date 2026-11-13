"""Runtime configuration, loaded from environment variables (and a local .env file).

The master key never lives in code or in the database. Startup fails if it is missing.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

load_dotenv(PROJECT_DIR / ".env")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")  # silence a joblib core-count probe on Windows


class ConfigError(RuntimeError):
    pass


def _decode_key(b64: str, name: str) -> bytes:
    try:
        key = base64.b64decode(b64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"{name} is not valid base64") from exc
    if len(key) != 32:
        raise ConfigError(f"{name} must decode to exactly 32 bytes (256-bit AES key)")
    return key


@dataclass
class Settings:
    database_url: str
    master_key: bytes
    master_key_version: int
    previous_master_keys: dict[int, bytes]
    data_dir: Path
    sim_keystore_path: Path
    sim_passphrase: str
    self_url: str
    tls_verify: str | bool
    secure_cookies: bool
    allowed_origins: list[str] = field(default_factory=list)
    session_idle_minutes: int = 30
    session_absolute_hours: int = 8
    ingest_skew_seconds: int = 60
    audit_checkpoint_every: int = 50
    pbkdf2_iterations: int = 210_000

    def key_for_version(self, version: int) -> bytes:
        if version == self.master_key_version:
            return self.master_key
        if version in self.previous_master_keys:
            return self.previous_master_keys[version]
        raise ConfigError(f"No master key available for version {version}")


def load_settings() -> Settings:
    raw = os.environ.get("RPM_MASTER_KEY")
    if not raw:
        raise ConfigError(
            "RPM_MASTER_KEY is not set. Run `python scripts/init_env.py` to create a .env file."
        )
    master = _decode_key(raw, "RPM_MASTER_KEY")
    version = int(os.environ.get("RPM_MASTER_KEY_VERSION", "1"))

    previous: dict[int, bytes] = {}
    for item in filter(None, os.environ.get("RPM_PREVIOUS_MASTER_KEYS", "").split(",")):
        ver, _, b64 = item.partition(":")
        previous[int(ver)] = _decode_key(b64.strip(), f"previous master key v{ver}")

    data_dir = Path(os.environ.get("RPM_DATA_DIR", BACKEND_DIR / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)

    tls_verify_env = os.environ.get("RPM_TLS_VERIFY", str(PROJECT_DIR / "certs" / "dev-cert.pem"))
    tls_verify: str | bool = False if tls_verify_env.lower() == "false" else tls_verify_env

    return Settings(
        database_url=os.environ.get("DATABASE_URL", f"sqlite:///{(data_dir / 'rpm.db').as_posix()}"),
        master_key=master,
        master_key_version=version,
        previous_master_keys=previous,
        data_dir=data_dir,
        sim_keystore_path=Path(
            os.environ.get("RPM_SIM_KEYSTORE", PROJECT_DIR / "simulator_keys" / "keystore.json")
        ),
        sim_passphrase=os.environ.get("RPM_SIM_PASSPHRASE", ""),
        self_url=os.environ.get("RPM_SELF_URL", "https://localhost:8443"),
        tls_verify=tls_verify,
        secure_cookies=os.environ.get("RPM_SECURE_COOKIES", "true").lower() == "true",
        allowed_origins=[
            o.strip()
            for o in os.environ.get(
                "RPM_ALLOWED_ORIGINS", "https://localhost:8443,https://127.0.0.1:8443"
            ).split(",")
            if o.strip()
        ],
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings() -> None:
    """Used by tests and scripts after changing environment variables."""
    global _settings
    _settings = None
