"""Attempt tracking fields for usage_events and run_steps.

Revision ID: 0002_attempt_tracking
Revises: 0001_init
Create Date: 2025-12-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_attempt_tracking"
down_revision = "0001_init"
branch_labels = None
depends_on = None


ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.add_column(
        "usage_events",
        sa.Column(
            "call_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=ZERO_UUID,
        ),
    )
    op.add_column(
        "usage_events",
        sa.Column(
            "attempt",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "usage_events",
        sa.Column("latency_ms", sa.Integer(), nullable=True),
    )
    op.create_index("ix_usage_events_call_id", "usage_events", ["call_id"])
    op.create_index("ix_usage_events_attempt", "usage_events", ["attempt"])

    op.add_column(
        "run_steps",
        sa.Column(
            "attempt",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "run_steps",
        sa.Column(
            "is_retry",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index("ix_run_steps_attempt", "run_steps", ["attempt"])
    op.create_index("ix_run_steps_is_retry", "run_steps", ["is_retry"])


def downgrade() -> None:
    op.drop_index("ix_run_steps_is_retry", table_name="run_steps")
    op.drop_index("ix_run_steps_attempt", table_name="run_steps")
    op.drop_column("run_steps", "is_retry")
    op.drop_column("run_steps", "attempt")

    op.drop_index("ix_usage_events_attempt", table_name="usage_events")
    op.drop_index("ix_usage_events_call_id", table_name="usage_events")
    op.drop_column("usage_events", "latency_ms")
    op.drop_column("usage_events", "attempt")
    op.drop_column("usage_events", "call_id")

