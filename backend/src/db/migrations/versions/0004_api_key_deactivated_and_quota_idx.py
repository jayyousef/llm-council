"""Add api_keys.deactivated_at and quota index

Revision ID: 0004_api_key_deactivated_and_quota_idx
Revises: 0003_run_ended_at
Create Date: 2026-01-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_api_key_deactivated_and_quota_idx"
down_revision = "0003_run_ended_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("deactivated_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_api_keys_deactivated_at"), "api_keys", ["deactivated_at"], unique=False)

    op.create_index(
        "ix_usage_events_owner_key_id_created_at",
        "usage_events",
        ["owner_key_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_usage_events_owner_key_id_created_at", table_name="usage_events")
    op.drop_index(op.f("ix_api_keys_deactivated_at"), table_name="api_keys")
    op.drop_column("api_keys", "deactivated_at")

