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
    except Exception as exc:
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
    retention_days: int = 365
    run_jobs: bool = True
    demo_mode: bool = False

    def key_for_version(self, version: int) -> bytes:
        if version == self.master_key_version:
            return self.master_key
        if version in self.previous_master_keys:
            return self.previous_master_keys[version]
        raise ConfigError(f"No master key available for version {version}")


def _int_env(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    return value


def _env_master_keys() -> tuple[bytes, int, dict[int, bytes]]:
    raw = os.environ.get("RPM_MASTER_KEY")
    if not raw:
        raise ConfigError(
            "RPM_MASTER_KEY is not set. Run `python scripts/init_env.py` to create a .env file."
        )
    master = _decode_key(raw, "RPM_MASTER_KEY")
    version = _int_env("RPM_MASTER_KEY_VERSION", 1, minimum=1)

    previous: dict[int, bytes] = {}
    for item in filter(None, os.environ.get("RPM_PREVIOUS_MASTER_KEYS", "").split(",")):
        ver, _, b64 = item.partition(":")
        if not ver.strip().isdigit() or not b64:
            raise ConfigError("RPM_PREVIOUS_MASTER_KEYS must look like '1:<base64>,2:<base64>'")
        previous[int(ver)] = _decode_key(b64.strip(), f"previous master key v{ver}")
    if version in previous:
        raise ConfigError("RPM_PREVIOUS_MASTER_KEYS must not contain the current key version")
    return master, version, previous


def _master_keys() -> tuple[bytes, int, dict[int, bytes]]:
    """Master keys from the configured source (env, sealed file, or an HSM/KMS command); see keysource.py."""
    from . import keysource

    try:
        bundle = keysource.load()
    except keysource.KeySourceError as exc:
        raise ConfigError(str(exc)) from exc
    if bundle is None:
        return _env_master_keys()
    return bundle.key, bundle.version, bundle.previous


def load_settings() -> Settings:
    master, version, previous = _master_keys()

    data_dir = Path(os.environ.get("RPM_DATA_DIR", BACKEND_DIR / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)

    tls_verify_env = os.environ.get("RPM_TLS_VERIFY", str(PROJECT_DIR / "certs" / "dev-cert.pem"))
    tls_verify: str | bool = False if tls_verify_env.lower() == "false" else tls_verify_env

    origins = [o.strip() for o in os.environ.get(
        "RPM_ALLOWED_ORIGINS", "https://localhost:8443,https://127.0.0.1:8443").split(",") if o.strip()]
    bad = [o for o in origins if not o.startswith(("https://", "http://localhost", "http://127.0.0.1"))]
    if bad:
        raise ConfigError(f"RPM_ALLOWED_ORIGINS entries must be https (or http on localhost): {bad}")

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
        retention_days=_int_env("RPM_RETENTION_DAYS", 365, minimum=0),
        run_jobs=os.environ.get("RPM_RUN_JOBS", "true").lower() == "true",
        demo_mode=os.environ.get("RPM_DEMO_MODE", "false").lower() == "true",
        allowed_origins=origins,
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
