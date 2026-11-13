"""Device simulator.

Each simulated device owns an RSA-3072 private key. The keys live in a separate keystore file
(simulator_keys/keystore.json), encrypted with AES-256-GCM under a key derived from
RPM_SIM_PASSPHRASE via PBKDF2-HMAC-SHA-512. The server database only ever sees public keys,
so a valid signature really proves the packet came from the key holder.

Readings go through the real HTTPS ingest API, sealed (DH + AES-GCM) and signed (RSA-PSS).
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import secrets
import threading
import time

import httpx

from .config import get_settings
from .ml.synth import EPISODES, PatientStream
from .security import aead, sealing, signatures
from .security.hashing import b64d, b64e, canonical

log = logging.getLogger("rpm.simulator")
KDF_ITERATIONS = 210_000


# ---------------------------------------------------------------- keystore

class Keystore:
    def __init__(self) -> None:
        s = get_settings()
        self.path = s.sim_keystore_path
        if not s.sim_passphrase:
            raise RuntimeError("RPM_SIM_PASSPHRASE is not set")
        self._pass = s.sim_passphrase.encode()
        self._lock = threading.Lock()
        self._key: bytes | None = None
        self._salt: bytes | None = None
        self.devices: dict[str, dict] = {}
        self._load()

    def _derive(self, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha512", self._pass, salt, KDF_ITERATIONS, dklen=32)

    def _load(self) -> None:
        if not self.path.exists():
            self._salt = secrets.token_bytes(16)
            self._key = self._derive(self._salt)
            return
        doc = json.loads(self.path.read_text())
        self._salt = b64d(doc["salt"])
        self._key = self._derive(self._salt)
        blob = aead.open_blob(self._key, b64d(doc["blob"]), canonical("sim-keystore", doc["salt"]))
        self.devices = json.loads(blob)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        salt_b64 = b64e(self._salt)
        blob = aead.seal_blob(self._key, json.dumps(self.devices).encode(), canonical("sim-keystore", salt_b64))
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"kdf": "pbkdf2-hmac-sha512", "iterations": KDF_ITERATIONS,
                                   "salt": salt_b64, "blob": b64e(blob)}))
        tmp.replace(self.path)

    def create_device(self, device_id: str, patient_id: int) -> str:
        """Generate the device key pair 'on the device'; return only the public key PEM."""
        key = signatures.rsa_generate()
        with self._lock:
            self.devices[device_id] = {
                "patient_id": patient_id,
                "private_pem": signatures.private_pem(key).decode(),
            }
            self._save()
        return signatures.public_pem(key)

    def private_key(self, device_id: str):  # noqa: ANN201
        return signatures.load_private_pem(self.devices[device_id]["private_pem"].encode())


# ---------------------------------------------------------------- packets

def build_packet(device_id: str, private_key, server_pub_raw: bytes, vitals: dict,  # noqa: ANN001
                 *, ts: int, seq: int) -> dict:
    from .readings.ingest import PROTOCOL_VERSION, signed_message

    plaintext = json.dumps(vitals, separators=(",", ":")).encode()
    sealed = sealing.seal(server_pub_raw, plaintext, device_id=device_id, seq=seq, ts=ts)
    sig = signatures.rsa_sign_digest(
        private_key, signed_message(device_id, seq, ts, sealed.epk, sealed.nonce, sealed.ciphertext)
    )
    return {"v": PROTOCOL_VERSION, "device_id": device_id, "seq": seq, "ts": ts,
            "epk": b64e(sealed.epk), "nonce": b64e(sealed.nonce), "ct": b64e(sealed.ciphertext),
            "sig": b64e(sig)}


def stream_for(device_id: str) -> PatientStream:
    # Seeded by device id so a patient's baseline is stable across restarts.
    return PatientStream(random.Random(device_id), episode_rate=0.0008, activity_rate=0.003)


# ---------------------------------------------------------------- live runner

class SimulatorRunner:
    """Background thread that posts readings for enabled devices every `interval` seconds."""

    def __init__(self, interval: float = 5.0) -> None:
        self.interval = interval
        self.enabled: dict[int, bool] = {}          # patient_id -> on/off
        self.streams: dict[str, PatientStream] = {}
        self.last_result: dict[int, str] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._keystore: Keystore | None = None
        self._server_pub: bytes | None = None
        self._last_seq: dict[str, int] = {}
        self.lock = threading.Lock()

    @property
    def keystore(self) -> Keystore:
        if self._keystore is None:
            self._keystore = Keystore()
        return self._keystore

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="rpm-simulator", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def set_enabled(self, patient_id: int, on: bool) -> None:
        with self.lock:
            self.enabled[patient_id] = on

    def trigger(self, patient_id: int, kind: str) -> bool:
        if kind not in EPISODES:
            raise ValueError("unknown episode type")
        found = False
        for dev_id, info in self.keystore.devices.items():
            if info["patient_id"] == patient_id:
                self.streams.setdefault(dev_id, stream_for(dev_id)).start(kind, scale=0.5)
                found = True
        return found

    def _pinned_server_key(self, client: httpx.Client) -> bytes:
        if self._server_pub is None:
            r = client.get("/api/ingest/server-key")
            r.raise_for_status()
            self._server_pub = b64d(r.json()["dh_public"])
        return self._server_pub

    def _next_seq(self, device_id: str) -> int:
        seq = max(int(time.time() * 1000), self._last_seq.get(device_id, 0) + 1)
        self._last_seq[device_id] = seq
        return seq

    def _run(self) -> None:
        s = get_settings()
        with httpx.Client(base_url=s.self_url, verify=s.tls_verify, timeout=10) as client:
            while not self._stop.wait(self.interval):
                with self.lock:
                    active = {pid for pid, on in self.enabled.items() if on}
                if not active:
                    continue
                try:
                    server_pub = self._pinned_server_key(client)
                    for dev_id, info in list(self.keystore.devices.items()):
                        pid = info["patient_id"]
                        if pid not in active:
                            continue
                        stream = self.streams.setdefault(dev_id, stream_for(dev_id))
                        vitals, _, _ = stream.step()
                        pkt = build_packet(dev_id, self.keystore.private_key(dev_id), server_pub, vitals,
                                           ts=int(time.time()), seq=self._next_seq(dev_id))
                        r = client.post("/api/ingest", json=pkt)
                        self.last_result[pid] = "ok" if r.status_code == 200 else f"{r.status_code}: {r.text[:120]}"
                except Exception as exc:  # noqa: BLE001  (keep the demo thread alive)
                    log.warning("simulator error: %s", exc)
                    self._server_pub = None


runner = SimulatorRunner()
