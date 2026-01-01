"""Add runs.ended_at

Revision ID: 0003_run_ended_at
Revises: 0002_attempt_tracking
Create Date: 2026-01-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_run_ended_at"
down_revision = "0002_attempt_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("ended_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_runs_ended_at"), "runs", ["ended_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_runs_ended_at"), table_name="runs")
    op.drop_column("runs", "ended_at")

