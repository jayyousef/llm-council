"""Add api_keys.account_id

Revision ID: 0005_api_keys_account_id
Revises: 0004_api_key_deactivated_and_quota_idx
Create Date: 2026-01-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_api_keys_account_id"
down_revision = "0004_api_key_deactivated_and_quota_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("account_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_api_keys_account_id"), "api_keys", ["account_id"], unique=False)
    op.create_foreign_key(
        "fk_api_keys_account_id_api_keys",
        "api_keys",
        "api_keys",
        ["account_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_api_keys_account_id_api_keys", "api_keys", type_="foreignkey")
    op.drop_index(op.f("ix_api_keys_account_id"), table_name="api_keys")
    op.drop_column("api_keys", "account_id")

