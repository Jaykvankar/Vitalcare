"""Tamper-evident audit ledger (our own protocol).

Hash chain:   h_i = SHA-512( canonical(h_{i-1}, ts, actor, action, target, detail) )
Checkpoints:  every N rows the head hash h_i is signed with the server ECDSA P-384 key.

Why both: anyone with database write access could rewrite rows *and* recompute every hash.
They cannot forge the ECDSA signature, so a recomputed chain no longer matches the
signed checkpoints. The DB also has triggers that reject UPDATE/DELETE on audit_log.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select

from ..config import get_settings
from ..db import SessionLocal
from ..models import AuditCheckpoint, AuditLog
from . import server_keys, signatures
from .hashing import canonical, sha512_hex

GENESIS = "0" * 128
_lock = threading.Lock()
_recent: dict[tuple, float] = {}
DEDUPE_SECONDS = 60
# Read actions repeat every few seconds while a page polls; log them once per minute per viewer.
DEDUPED_ACTIONS = {"decrypt_readings", "decrypt_profile"}


def row_hash(prev_hash: str, ts: str, actor_id, actor: str, action: str, target: str, detail: str) -> str:  # noqa: ANN001
    return sha512_hex(canonical(prev_hash, ts, "" if actor_id is None else actor_id, actor, action, target, detail))


def checkpoint_message(last_id: int, head_hash: str) -> bytes:
    return canonical("RPM-audit-checkpoint-v1", last_id, head_hash)


def append(action: str, *, actor_id: int | None = None, actor: str = "system",
           target: str = "", detail: str = "") -> None:
    if action in DEDUPED_ACTIONS:
        key = (actor_id, action, target)
        now = time.monotonic()
        if now - _recent.get(key, -1e9) < DEDUPE_SECONDS:
            return
        _recent[key] = now

    with _lock:
        db = SessionLocal()
        try:
            last = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
            prev = last.hash if last else GENESIS
            ts = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            h = row_hash(prev, ts, actor_id, actor, action, target, detail)
            entry = AuditLog(ts=ts, actor_id=actor_id, actor=actor, action=action,
                             target=target, detail=detail, prev_hash=prev, hash=h)
            db.add(entry)
            db.commit()
            last_cp = db.execute(
                select(AuditCheckpoint).order_by(AuditCheckpoint.id.desc()).limit(1)
            ).scalar_one_or_none()
            since = entry.id - (last_cp.last_audit_id if last_cp else 0)
            if since >= get_settings().audit_checkpoint_every:
                _checkpoint(db, entry.id, h)
        finally:
            db.close()


def _checkpoint(db, last_id: int, head_hash: str) -> None:  # noqa: ANN001
    keys = server_keys.load_or_create()
    sig = signatures.ecdsa_sign(keys.ecdsa_private, checkpoint_message(last_id, head_hash))
    db.add(AuditCheckpoint(last_audit_id=last_id, head_hash=head_hash, signature=sig))
    db.commit()


def checkpoint_now() -> None:
    """Sign the current head (called at shutdown and from the admin page)."""
    with _lock:
        db = SessionLocal()
        try:
            last = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
            if last is None:
                return
            last_cp = db.execute(
                select(AuditCheckpoint).order_by(AuditCheckpoint.id.desc()).limit(1)
            ).scalar_one_or_none()
            if last_cp and last_cp.last_audit_id == last.id:
                return
            _checkpoint(db, last.id, last.hash)
        finally:
            db.close()


def verify(db=None) -> dict:  # noqa: ANN001
    """Recompute the whole chain and check every checkpoint signature."""
    own = db is None
    db = db or SessionLocal()
    try:
        problems: list[str] = []
        prev = GENESIS
        hashes: dict[int, str] = {}
        rows = 0
        for row in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
            rows += 1
            if row.prev_hash != prev:
                problems.append(f"row {row.id}: prev_hash does not match previous row (row removed or reordered)")
            expected = row_hash(row.prev_hash, row.ts, row.actor_id, row.actor, row.action, row.target, row.detail)
            if expected != row.hash:
                problems.append(f"row {row.id}: content does not match its hash (row edited)")
            hashes[row.id] = row.hash
            prev = row.hash

        pub = server_keys.load_or_create().ecdsa_public
        cps = list(db.execute(select(AuditCheckpoint).order_by(AuditCheckpoint.id)).scalars())
        for cp in cps:
            if not signatures.ecdsa_verify(pub, checkpoint_message(cp.last_audit_id, cp.head_hash), cp.signature):
                problems.append(f"checkpoint {cp.id}: ECDSA signature invalid")
            elif hashes.get(cp.last_audit_id) != cp.head_hash:
                problems.append(
                    f"checkpoint {cp.id}: signed head for row {cp.last_audit_id} no longer matches the chain "
                    "(history rewritten)"
                )
        anchored_to = cps[-1].last_audit_id if cps else 0
        return {
            "ok": not problems,
            "rows": rows,
            "checkpoints": len(cps),
            "anchored_through_row": anchored_to,
            "unanchored_rows": max(0, max(hashes) - anchored_to) if hashes else 0,
            "problems": problems[:50],
        }
    finally:
        if own:
            db.close()
