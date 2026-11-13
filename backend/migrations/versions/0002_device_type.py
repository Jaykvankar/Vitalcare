"""Add device_type to devices and pairing_codes (catalog id shown in the app).

Revision ID: 0002_device_type
Revises: 0001_baseline
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_device_type"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

TABLES = ("devices", "pairing_codes")


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # The baseline is a snapshot of the models, so a database created after this change already has the
    # columns. Only add them where they are missing (databases created before this revision).
    for table in TABLES:
        if not _has_column(table, "device_type"):
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column("device_type", sa.String(32), nullable=True))


def downgrade() -> None:
    for table in TABLES:
        if _has_column(table, "device_type"):
            with op.batch_alter_table(table) as batch:
                batch.drop_column("device_type")
