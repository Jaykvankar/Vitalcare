"""Evidence for the Security inspector screen: what the crypto did for the latest packets.

Only public or encrypted values are kept (DH public value, nonces, ciphertext and signature prefixes,
digests, sequence numbers). Never vital signs, plaintext or any key. Held in memory for the last few
packets per device; a server restart clears it. The last raw packet per device is kept so an admin can
demonstrate that replaying or tampering with it is rejected.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from .hashing import sha512_hex

KEEP = 5
_lock = threading.Lock()
_evidence: dict[str, deque] = defaultdict(lambda: deque(maxlen=KEEP))
_last_packet: dict[str, dict] = {}


def _hex(b: bytes, n: int = 24) -> str:
    h = b.hex()
    return h if len(h) <= n else f"{h[:n]}…"


def record(*, packet: dict, epk: bytes, server_pub: bytes, nonce: bytes, ct: bytes, sig: bytes, signed: bytes,
           prev_seq: int, skew_s: int, patient_id: int, key_version: int, store_nonce: bytes, store_ct: bytes,
           band: str, vitals_count: int, scored: bool) -> None:
    item = {
        "received_at": int(time.time()),
        "device_id": packet["device_id"],
        "patient_id": patient_id,
        "steps": [
            {"id": "dh", "title": "Diffie–Hellman key agreement", "family": "Diffie–Hellman",
             "algorithm": "Ephemeral DH, RFC 7919 group ffdhe3072 (3072-bit safe prime, g = 2)",
             "values": {"Device public value E = gᵉ mod p": f"{_hex(epk)} ({len(epk) * 8} bits)",
                        "Server public value S fingerprint": sha512_hex(server_pub)[:24] + "…",
                        "Shared secret": "computed on both sides as Sᵉ = Eˢ mod p, never sent"},
             "ok": True},
            {"id": "kdf", "title": "Key derivation", "family": "SHA-512 (HMAC)",
             "algorithm": "HKDF-SHA-512 (salt = SHA-512(E ‖ S), info = protocol ‖ device ‖ seq ‖ time)",
             "values": {"Derived key": "fresh 256-bit AES key for this one reading (not stored)"}, "ok": True},
            {"id": "aead", "title": "Payload encrypted", "family": "AES",
             "algorithm": "AES-256-GCM (96-bit nonce, 128-bit authentication tag)",
             "values": {"Nonce": _hex(nonce, 32), "Ciphertext": f"{_hex(ct[:-16])} ({len(ct) - 16} bytes)",
                        "Authentication tag": _hex(ct[-16:], 32), "Vitals inside": f"{vitals_count} of 6 measured"},
             "ok": True},
            {"id": "digest", "title": "Digest of the whole packet", "family": "SHA-512",
             "algorithm": "SHA-512 over version ‖ device ‖ seq ‖ time ‖ E ‖ nonce ‖ ciphertext",
             "values": {"SHA-512": sha512_hex(signed)[:48] + "…"}, "ok": True},
            {"id": "sig", "title": "Signature verified", "family": "RSA digital signature (sign-the-digest)",
             "algorithm": "RSA-3072-PSS with MGF1-SHA-512, checked with the device's registered public key",
             "values": {"Signature": f"{_hex(sig)} ({len(sig) * 8} bits)", "Result": "valid: sent by this device, unchanged"},
             "ok": True},
            {"id": "replay", "title": "Freshness and replay check", "family": "Protocol",
             "algorithm": "Sequence number must increase (atomic compare-and-set); clock within ±60 s",
             "values": {"Previous sequence": str(prev_seq), "This sequence": str(packet["seq"]),
                        "Clock difference": f"{skew_s} s"}, "ok": True},
            {"id": "store", "title": "Stored under the patient's own key", "family": "AES (envelope encryption)",
             "algorithm": "AES-256-GCM with the patient key; that key is itself wrapped by the master key",
             "values": {"Patient key version": f"v{key_version}", "Storage nonce": _hex(store_nonce, 32),
                        "Stored ciphertext": f"{_hex(store_ct[:-16])} ({len(store_ct) - 16} bytes)",
                        "Bound to (AAD)": f"patient {patient_id} · device · seq · time"}, "ok": True},
            {"id": "ai", "title": "Risk scored", "family": "AI",
             "algorithm": "Clinical rules + NEWS2"
                          + (" + gradient-boosting model" if scored else " (model skipped: not all six vitals)"),
             "values": {"Band": band}, "ok": True},
        ],
    }
    with _lock:
        _evidence[packet["device_id"]].appendleft(item)
        _last_packet[packet["device_id"]] = dict(packet)


def evidence(device_ids: set[str]) -> dict[str, list[dict]]:
    with _lock:
        return {d: list(_evidence[d]) for d in device_ids if d in _evidence}


def last_packet(device_id: str) -> dict | None:
    with _lock:
        p = _last_packet.get(device_id)
        return dict(p) if p else None


def clear() -> None:
    with _lock:
        _evidence.clear()
        _last_packet.clear()
