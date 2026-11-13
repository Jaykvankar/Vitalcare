"""Add users.demo_account (accounts created by the demo seed).

Revision ID: 0003_demo_account
Revises: 0002_device_type
Create Date: 2026-11-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_demo_account"
down_revision = "0002_device_type"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # The baseline is a model snapshot, so newer databases already have the column.
    if not _has_column("users", "demo_account"):
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("demo_account", sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    if _has_column("users", "demo_account"):
        with op.batch_alter_table("users") as batch:
            batch.drop_column("demo_account")
