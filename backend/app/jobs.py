"""Periodic maintenance, run in a background thread once a minute.

- Escalation: critical alerts still open after ESCALATE_MINUTES are marked escalated and audited.
- Cleanup: expired/revoked sessions, used/expired pairing codes and old rate-limit windows.
- Retention: readings and rollups older than RPM_RETENTION_DAYS are deleted (data minimisation).

Every step is idempotent, so running it in several server processes is safe.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select, update

from .config import get_settings
from .db import SessionLocal
from .models import Alert, PairingCode, RateLimit, Reading, ReadingRollup, Session_
from .security import audit

log = logging.getLogger("rpm.jobs")
ESCALATE_MINUTES = 15


def escalate_alerts(now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(minutes=ESCALATE_MINUTES)
    db = SessionLocal()
    try:
        due = db.execute(select(Alert.id, Alert.patient_id, Alert.reason_code).where(
            Alert.status == "open", Alert.severity == "critical", Alert.escalated_at.is_(None),
            Alert.first_seen <= cutoff)).all()
        n = 0
        for alert_id, patient_id, code in due:
            res = db.execute(update(Alert).where(Alert.id == alert_id, Alert.escalated_at.is_(None))
                             .values(escalated_at=now))
            db.commit()
            if res.rowcount == 1:  # only the process that won the update writes the audit row
                n += 1
                audit.append("alert_escalated", actor="system", target=f"patient:{patient_id}",
                             detail=f"alert={alert_id} code={code} unacknowledged>{ESCALATE_MINUTES}min")
        return n
    finally:
        db.close()


def cleanup(now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    day_ago = now - timedelta(days=1)
    db = SessionLocal()
    try:
        s = db.execute(delete(Session_).where(or_(Session_.revoked.is_(True), Session_.created_at < day_ago))).rowcount
        p = db.execute(delete(PairingCode).where(PairingCode.expires_at < day_ago)).rowcount
        r = db.execute(delete(RateLimit).where(RateLimit.window_start < int(now.timestamp()) - 3600)).rowcount
        db.commit()
        return {"sessions": s, "pairing_codes": p, "rate_limits": r}
    finally:
        db.close()


def apply_retention(now: datetime | None = None) -> int:
    days = get_settings().retention_days
    if days <= 0:
        return 0
    cutoff = int((now or datetime.now(UTC)).timestamp()) - days * 86400
    db = SessionLocal()
    try:
        n = db.execute(delete(Reading).where(Reading.ts < cutoff)).rowcount
        db.execute(delete(ReadingRollup).where(ReadingRollup.bucket_ts < cutoff))
        db.commit()
    finally:
        db.close()
    if n:
        audit.append("retention_purge", actor="system", detail=f"readings={n} older_than_days={days}")
    return n


class JobRunner:
    def __init__(self, interval: float = 60.0) -> None:
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="rpm-jobs", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        last_cleanup = 0.0
        while not self._stop.wait(self.interval):
            try:
                escalate_alerts()
                if time.monotonic() - last_cleanup > 600:
                    cleanup()
                    apply_retention()
                    last_cleanup = time.monotonic()
            except Exception:
                log.exception("maintenance job failed")


jobs = JobRunner()
