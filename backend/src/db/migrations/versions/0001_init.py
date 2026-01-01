"""Initial schema.

Revision ID: 0001_init
Revises: None
Create Date: 2025-12-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("key_hash", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False, server_default="default"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("rate_limit_per_min", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("monthly_token_cap", sa.Integer(), nullable=True),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("title", sa.String(), nullable=False, server_default="New Conversation"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("owner_key_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("api_keys.id"), nullable=True),
    )
    op.create_index("ix_conversations_owner_key_id", "conversations", ["owner_key_id"])

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_created_at", "messages", ["created_at"])
    op.create_index("ix_messages_role", "messages", ["role"])

    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("owner_key_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("api_keys.id"), nullable=True),
    )
    op.create_index("ix_runs_conversation_id", "runs", ["conversation_id"])
    op.create_index("ix_runs_created_at", "runs", ["created_at"])
    op.create_index("ix_runs_owner_key_id", "runs", ["owner_key_id"])
    op.create_index("ix_runs_status", "runs", ["status"])

    op.create_table(
        "run_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("stage_name", sa.String(), nullable=False),
        sa.Column("step_type", sa.String(), nullable=False),
        sa.Column("agent_role", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False, server_default=""),
        sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_run_steps_run_id", "run_steps", ["run_id"])
    op.create_index("ix_run_steps_created_at", "run_steps", ["created_at"])
    op.create_index("ix_run_steps_stage_name", "run_steps", ["stage_name"])
    op.create_index("ix_run_steps_step_type", "run_steps", ["step_type"])
    op.create_index("ix_run_steps_agent_role", "run_steps", ["agent_role"])
    op.create_index("ix_run_steps_model", "run_steps", ["model"])

    op.create_table(
        "usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("owner_key_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("api_keys.id"), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_estimated", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("raw_usage_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("usage_missing", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_usage_events_owner_key_id", "usage_events", ["owner_key_id"])
    op.create_index("ix_usage_events_run_id", "usage_events", ["run_id"])
    op.create_index("ix_usage_events_model", "usage_events", ["model"])
    op.create_index("ix_usage_events_created_at", "usage_events", ["created_at"])
    op.create_index("ix_usage_events_usage_missing", "usage_events", ["usage_missing"])

    op.create_table(
        "cache_entries",
        sa.Column("key", sa.Text(), primary_key=True, nullable=False),
        sa.Column("value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_cache_entries_created_at", "cache_entries", ["created_at"])
    op.create_index("ix_cache_entries_expires_at", "cache_entries", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_cache_entries_expires_at", table_name="cache_entries")
    op.drop_index("ix_cache_entries_created_at", table_name="cache_entries")
    op.drop_table("cache_entries")

    op.drop_index("ix_usage_events_usage_missing", table_name="usage_events")
    op.drop_index("ix_usage_events_created_at", table_name="usage_events")
    op.drop_index("ix_usage_events_model", table_name="usage_events")
    op.drop_index("ix_usage_events_run_id", table_name="usage_events")
    op.drop_index("ix_usage_events_owner_key_id", table_name="usage_events")
    op.drop_table("usage_events")

    op.drop_index("ix_run_steps_model", table_name="run_steps")
    op.drop_index("ix_run_steps_agent_role", table_name="run_steps")
    op.drop_index("ix_run_steps_step_type", table_name="run_steps")
    op.drop_index("ix_run_steps_stage_name", table_name="run_steps")
    op.drop_index("ix_run_steps_created_at", table_name="run_steps")
    op.drop_index("ix_run_steps_run_id", table_name="run_steps")
    op.drop_table("run_steps")

    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_index("ix_runs_owner_key_id", table_name="runs")
    op.drop_index("ix_runs_created_at", table_name="runs")
    op.drop_index("ix_runs_conversation_id", table_name="runs")
    op.drop_table("runs")

    op.drop_index("ix_messages_role", table_name="messages")
    op.drop_index("ix_messages_created_at", table_name="messages")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")

    op.drop_index("ix_conversations_owner_key_id", table_name="conversations")
    op.drop_table("conversations")

    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")

