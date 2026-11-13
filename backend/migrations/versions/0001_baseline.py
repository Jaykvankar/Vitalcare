"""Baseline schema (users, patients, devices, readings, rollups, alerts, audit ledger, imports).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-13
"""
from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The baseline is the full model snapshot; later revisions use explicit op.* changes.
    from app.db import Base
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    raise RuntimeError("The baseline cannot be downgraded; restore from a backup instead.")
