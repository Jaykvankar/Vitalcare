"""Allow readings without an AI score (partial readings from real sensors).

Revision ID: 0004_partial_readings
Revises: 0003_demo_account
Create Date: 2026-11-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_partial_readings"
down_revision = "0003_demo_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("readings") as batch:
        batch.alter_column("risk_score", existing_type=sa.Float(), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE readings SET risk_score = 0 WHERE risk_score IS NULL")
    with op.batch_alter_table("readings") as batch:
        batch.alter_column("risk_score", existing_type=sa.Float(), nullable=False)
