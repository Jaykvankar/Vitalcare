"""Server long-term keys, stored encrypted under the master key.

* DH static key (ffdhe3072): devices seal readings to its public value.
* ECDSA P-384 key: signs audit-log checkpoints.

File: <data_dir>/server_keys.json  ->  {"version": v, "dh": b64(AES-GCM blob), "ecdsa": b64(...)}
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import dh, ec

from ..config import get_settings
from . import sealing, signatures
from .crypto import decrypt_with_master, encrypt_with_master
from .hashing import b64d, b64e


@dataclass
class ServerKeys:
    dh_private: dh.DHPrivateKey
    ecdsa_private: ec.EllipticCurvePrivateKey

    @property
    def dh_public_raw(self) -> bytes:
        return sealing.public_bytes(self.dh_private.public_key())

    @property
    def ecdsa_public(self) -> ec.EllipticCurvePublicKey:
        return self.ecdsa_private.public_key()


_lock = threading.Lock()
_cached: ServerKeys | None = None


def _path():
    return get_settings().data_dir / "server_keys.json"


def save(keys: ServerKeys, version: int | None = None) -> None:
    dh_blob, v = encrypt_with_master(sealing.private_to_pem(keys.dh_private), "server-dh", version)
    ec_blob, _ = encrypt_with_master(signatures.private_pem(keys.ecdsa_private), "server-ecdsa", v)
    _path().write_text(json.dumps({"version": v, "dh": b64e(dh_blob), "ecdsa": b64e(ec_blob)}, indent=2))


def load_or_create() -> ServerKeys:
    global _cached
    with _lock:
        if _cached is not None:
            return _cached
        path = _path()
        if path.exists():
            doc = json.loads(path.read_text())
            v = int(doc["version"])
            dh_priv = sealing.private_from_pem(decrypt_with_master(b64d(doc["dh"]), "server-dh", v))
            ec_priv = signatures.load_private_pem(decrypt_with_master(b64d(doc["ecdsa"]), "server-ecdsa", v))
            _cached = ServerKeys(dh_priv, ec_priv)
        else:
            _cached = ServerKeys(sealing.generate_private_key(), signatures.ecdsa_generate())
            save(_cached)
        return _cached


def reset_cache() -> None:
    global _cached
    _cached = None
