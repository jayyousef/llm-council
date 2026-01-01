"""Expand alembic_version.version_num length

Revision ID: 0004_expand_alembic_ver
Revises: 0003_run_ended_at
Create Date: 2026-01-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_expand_alembic_ver"
down_revision = "0003_run_ended_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")
        return

    # Other DBs (e.g., SQLite) don't enforce VARCHAR length in the same way; keep this a no-op.


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(32)")
        return

    # See upgrade(): keep this a no-op for non-Postgres backends.

