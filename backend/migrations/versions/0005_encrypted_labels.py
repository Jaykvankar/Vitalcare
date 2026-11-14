"""Keep band, AI score and reason codes encrypted at rest (security/labels.py).

Schema: patients.last_status_enc, alerts.reason_tag (blind index) and alerts.details_enc are added; the old clear
columns become nullable; the unique "one open alert" index moves from reason_code to reason_tag.
Data: every existing clear label is moved into ciphertext under that patient's key, and the clear column is set to
NULL. Patients whose key was destroyed (erased) simply lose the clear labels.

Revision ID: 0005_encrypted_labels
Revises: 0004_partial_readings
Create Date: 2026-11-14
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0005_encrypted_labels"
down_revision = "0004_partial_readings"
branch_labels = None
depends_on = None


def _columns(table: str) -> dict[str, dict]:
    return {c["name"]: c for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _schema() -> None:
    if "last_status_enc" not in _columns("patients"):
        with op.batch_alter_table("patients") as batch:
            batch.add_column(sa.Column("last_status_enc", sa.LargeBinary(), nullable=True))
    cols = _columns("readings")
    if not cols["band"]["nullable"] or not cols["reason_codes"]["nullable"]:
        with op.batch_alter_table("readings") as batch:
            batch.alter_column("band", existing_type=sa.String(16), nullable=True)
            batch.alter_column("reason_codes", existing_type=sa.String(256), nullable=True)
    if not _columns("reading_rollups")["worst_band"]["nullable"]:
        with op.batch_alter_table("reading_rollups") as batch:
            batch.alter_column("worst_band", existing_type=sa.String(16), nullable=True)
    cols = _columns("alerts")
    if "reason_tag" not in cols or not cols["reason_code"]["nullable"] or not cols["severity"]["nullable"]:
        with op.batch_alter_table("alerts") as batch:
            if "reason_tag" not in cols:
                batch.add_column(sa.Column("reason_tag", sa.String(128), nullable=True))
                batch.add_column(sa.Column("details_enc", sa.LargeBinary(), nullable=True))
            batch.alter_column("reason_code", existing_type=sa.String(32), nullable=True)
            batch.alter_column("severity", existing_type=sa.String(16), nullable=True)
    if "uq_alert_open" in _indexes("alerts"):
        op.drop_index("uq_alert_open", table_name="alerts")
    if "uq_alert_open_tag" not in _indexes("alerts"):
        op.create_index("uq_alert_open_tag", "alerts", ["patient_id", "reason_tag"], unique=True,
                        sqlite_where=sa.text("status = 'open'"), postgresql_where=sa.text("status = 'open'"))


def _encrypt_existing() -> None:
    from app.security import aead, crypto, labels
    from app.security.hashing import canonical

    conn = op.get_bind()
    patients = conn.execute(sa.text(
        "SELECT id, wrapped_dek, key_version, erased_at, last_band, last_score FROM patients")).all()
    for pid, wrapped, version, erased_at, last_band, last_score in patients:
        dek = None
        if erased_at is None and wrapped:
            try:
                dek = crypto.unwrap_dek(wrapped, pid, version)
            except aead.DecryptionError:
                dek = None

        for rid, device_id, seq, ts, nonce, ct, band, risk, codes in conn.execute(sa.text(
                "SELECT id, device_id, seq, ts, nonce, ciphertext, band, risk_score, reason_codes FROM readings "
                "WHERE patient_id = :p AND band IS NOT NULL"), {"p": pid}).all():
            if dek is not None:
                aad = crypto.reading_aad(pid, device_id, seq, ts)
                payload = json.loads(aead.decrypt(dek, nonce, ct, aad))
                payload.update({"band": band, "risk": risk, "reasons": [c for c in (codes or "").split(",") if c]})
                nonce, ct = aead.encrypt(dek, json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(), aad)
            conn.execute(sa.text("UPDATE readings SET nonce = :n, ciphertext = :c, band = NULL, risk_score = NULL, "
                                 "reason_codes = NULL WHERE id = :id"), {"n": nonce, "c": ct, "id": rid})

        for rid, bucket_ts, blob, worst in conn.execute(sa.text(
                "SELECT id, bucket_ts, blob, worst_band FROM reading_rollups WHERE patient_id = :p "
                "AND worst_band IS NOT NULL"), {"p": pid}).all():
            if dek is not None:
                aad = canonical("rollup", pid, bucket_ts)
                data = json.loads(aead.open_blob(dek, blob, aad))
                data["band"] = worst
                blob = aead.seal_blob(dek, json.dumps(data, separators=(",", ":")).encode(), aad)
            conn.execute(sa.text("UPDATE reading_rollups SET blob = :b, worst_band = NULL WHERE id = :id"),
                         {"b": blob, "id": rid})

        if last_band is not None or last_score is not None:
            status = (crypto.encrypt_json(dek, {"band": last_band, "risk": last_score}, patient_id=pid,
                                          field="last_status") if dek is not None and last_band is not None else None)
            conn.execute(sa.text("UPDATE patients SET last_status_enc = :s, last_band = NULL, last_score = NULL "
                                 "WHERE id = :id"), {"s": status, "id": pid})

        for aid, code, severity in conn.execute(sa.text(
                "SELECT id, reason_code, severity FROM alerts WHERE patient_id = :p AND reason_code IS NOT NULL"),
                {"p": pid}).all():
            tag = details = None
            if dek is not None:
                tag = labels.alert_tag(dek, pid, code)
                details = labels.encrypt_alert(dek, pid, tag, code, severity)
            conn.execute(sa.text("UPDATE alerts SET reason_tag = :t, details_enc = :d, reason_code = NULL, "
                                 "severity = NULL WHERE id = :id"), {"t": tag, "d": details, "id": aid})


def upgrade() -> None:
    _schema()
    _encrypt_existing()


def downgrade() -> None:
    raise NotImplementedError("Labels are encrypted now; restore a backup to go back before 0005.")
