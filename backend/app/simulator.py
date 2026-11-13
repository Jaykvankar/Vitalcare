"""Device simulator.

Each simulated device owns an RSA-3072 private key. The keys live in a separate keystore file
(simulator_keys/keystore.json), encrypted with AES-256-GCM under a key derived from
RPM_SIM_PASSPHRASE via PBKDF2-HMAC-SHA-512. The server database only ever sees public keys,
so a valid signature really proves the packet came from the key holder.

Devices join through the pairing protocol (security/pairing.py) and send readings through the real
HTTPS ingest API, sealed (DH + AES-GCM) and signed (RSA-PSS). A device's data source is either the
synthetic generator or a replay of a real recording (MIMIC-III demo or BIDMC, see ml/realdata.py).
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
from .ml import realdata
from .ml.synth import EPISODES, PatientStream
from .security import aead, pairing, sealing, signatures
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
        self.devices = json.loads(aead.open_blob(self._key, b64d(doc["blob"]), canonical("sim-keystore", doc["salt"])))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        salt_b64 = b64e(self._salt)
        blob = aead.seal_blob(self._key, json.dumps(self.devices).encode(), canonical("sim-keystore", salt_b64))
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"kdf": "pbkdf2-hmac-sha512", "iterations": KDF_ITERATIONS,
                                   "salt": salt_b64, "blob": b64e(blob)}))
        tmp.replace(self.path)

    def add(self, device_id: str, patient_id: int, private_pem: bytes, source: str) -> None:
        with self._lock:
            self.devices[device_id] = {"patient_id": patient_id, "private_pem": private_pem.decode(), "source": source}
            self._save()

    def set_source(self, device_id: str, source: str, offset: int = 0) -> None:
        with self._lock:
            self.devices[device_id]["source"] = source
            self.devices[device_id]["offset"] = offset  # where a real-data replay continues from
            self._save()

    def private_key(self, device_id: str):
        return signatures.load_private_pem(self.devices[device_id]["private_pem"].encode())


# ---------------------------------------------------------------- packets

def build_packet(device_id: str, private_key, server_pub_raw: bytes, vitals: dict,
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


def pairing_request(pairing_id: str, code: str) -> tuple[bytes, dict]:
    """What a device does at pairing time: make its own key pair, prove knowledge of the code."""
    key = signatures.rsa_generate()
    pub = signatures.public_pem(key)
    body = {"pairing_id": pairing_id, "public_key_pem": pub, "proof": b64e(pairing.proof(code, pairing_id, pub))}
    return signatures.private_pem(key), body


def stream_for(device_id: str, source: str = "synthetic", start: int = 0) -> PatientStream | realdata.ReplayStream:
    real = realdata.stream_for_source(source, start) if source != "synthetic" else None
    if real is not None:
        return real
    # Seeded by device id so a patient's synthetic baseline is stable across restarts.
    return PatientStream(random.Random(device_id), episode_rate=0.0008, activity_rate=0.003)


# ---------------------------------------------------------------- live runner

class SimulatorRunner:
    """Background thread that posts readings for enabled devices every `interval` seconds."""

    def __init__(self, interval: float = 5.0) -> None:
        self.interval = interval
        self.enabled: dict[int, bool] = {}          # patient_id -> on/off
        self.streams: dict[str, PatientStream | realdata.ReplayStream] = {}
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

    def source_for_patient(self, patient_id: int) -> str | None:
        for info in self.keystore.devices.values():
            if info["patient_id"] == patient_id:
                return info.get("source", "synthetic")
        return None

    def set_source(self, patient_id: int, source: str) -> bool:
        found = False
        for dev_id, info in list(self.keystore.devices.items()):
            if info["patient_id"] == patient_id:
                self.keystore.set_source(dev_id, source)
                self.streams.pop(dev_id, None)
                found = True
        return found

    def trigger(self, patient_id: int, kind: str) -> bool:
        if kind not in EPISODES:
            raise ValueError("unknown episode type")
        found = False
        for dev_id, info in self.keystore.devices.items():
            if info["patient_id"] == patient_id and info.get("source", "synthetic") == "synthetic":
                self.streams.setdefault(dev_id, stream_for(dev_id)).start(kind, scale=0.5)
                found = True
        return found

    def pair_over_http(self, pairing_id: str, code: str, source: str) -> str:
        """Act as a brand-new device: pair through the public /api/devices/pair endpoint."""
        s = get_settings()
        private_pem, body = pairing_request(pairing_id, code)
        with httpx.Client(base_url=s.self_url, verify=s.tls_verify, timeout=20) as client:
            r = client.post("/api/devices/pair", json=body)
        if r.status_code != 200:
            raise RuntimeError(r.json().get("detail", r.text))
        device_id = r.json()["device_id"]
        from .db import SessionLocal
        from .models import Device

        db = SessionLocal()
        try:
            device = db.get(Device, device_id)
            if device is None:
                raise RuntimeError("pairing succeeded but the device is missing")
            patient_id = device.patient_id
        finally:
            db.close()
        self.keystore.add(device_id, patient_id, private_pem, source)
        return device_id

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
                        stream = self.streams.get(dev_id)
                        if stream is None:
                            source, offset = info.get("source", "synthetic"), info.get("offset", 0)
                            stream = self.streams[dev_id] = stream_for(dev_id, source, offset)
                        vitals, _, _ = stream.step()
                        pkt = build_packet(dev_id, self.keystore.private_key(dev_id), server_pub, vitals,
                                           ts=int(time.time()), seq=self._next_seq(dev_id))
                        r = client.post("/api/ingest", json=pkt)
                        if r.status_code == 200:
                            self.last_result[pid] = "ok"
                        else:
                            self.last_result[pid] = f"{r.status_code}: {r.json().get('detail', '')}"[:120]
                except Exception as exc:  # noqa: BLE001  (keep the demo thread alive)
                    log.warning("simulator error: %s", exc)
                    self._server_pub = None


runner = SimulatorRunner()
