from __future__ import annotations

from datetime import datetime
import uuid
from typing import Any, Optional

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON as SAJSON
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.utcnow()


JsonType = SAJSON().with_variant(JSONB, "postgresql")


class ApiKey(SQLModel, table=True):
    __tablename__ = "api_keys"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # When set, this key belongs to the "account" rooted at account_id (a key id).
    # When unset, the key is its own account root.
    account_id: Optional[uuid.UUID] = Field(default=None, foreign_key="api_keys.id", index=True)
    key_hash: str = Field(index=True, unique=True)
    name: str = Field(default="default")
    is_active: bool = Field(default=True)
    rate_limit_per_min: int = Field(default=60)
    created_at: datetime = Field(default_factory=utcnow)
    deactivated_at: Optional[datetime] = Field(default=None)
    last_used_at: Optional[datetime] = Field(default=None)
    monthly_token_cap: Optional[int] = Field(default=None)


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: uuid.UUID = Field(primary_key=True)
    title: str = Field(default="New Conversation")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    owner_key_id: Optional[uuid.UUID] = Field(default=None, foreign_key="api_keys.id", index=True)


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    conversation_id: uuid.UUID = Field(foreign_key="conversations.id", index=True)
    role: str = Field(index=True)  # 'user'|'assistant'
    content: str
    created_at: datetime = Field(default_factory=utcnow, index=True)


class Run(SQLModel, table=True):
    __tablename__ = "runs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    conversation_id: uuid.UUID = Field(foreign_key="conversations.id", index=True)
    tool_name: str
    input_json: dict[str, Any] = Field(sa_column=Column(JsonType), default_factory=dict)
    status: str = Field(default="running", index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    ended_at: Optional[datetime] = Field(default=None, index=True)
    latency_ms: Optional[int] = Field(default=None)
    owner_key_id: Optional[uuid.UUID] = Field(default=None, foreign_key="api_keys.id", index=True)


class RunStep(SQLModel, table=True):
    __tablename__ = "run_steps"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="runs.id", index=True)
    stage_name: str = Field(index=True)
    step_type: str = Field(index=True)
    agent_role: str = Field(index=True)
    model: str = Field(default="", index=True)
    attempt: int = Field(default=0, index=True)
    is_retry: bool = Field(default=False, index=True)
    output_json: dict[str, Any] = Field(sa_column=Column(JsonType), default_factory=dict)
    latency_ms: Optional[int] = Field(default=None)
    error_text: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow, index=True)


class UsageEvent(SQLModel, table=True):
    __tablename__ = "usage_events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_key_id: Optional[uuid.UUID] = Field(default=None, foreign_key="api_keys.id", index=True)
    run_id: uuid.UUID = Field(foreign_key="runs.id", index=True)
    model: str = Field(index=True)
    call_id: uuid.UUID = Field(default_factory=uuid.uuid4, index=True)
    attempt: int = Field(default=0, index=True)
    prompt_tokens: Optional[int] = Field(default=None)
    completion_tokens: Optional[int] = Field(default=None)
    total_tokens: Optional[int] = Field(default=None)
    cost_estimated: Optional[float] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    latency_ms: Optional[int] = Field(default=None)
    raw_usage_json: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JsonType))
    usage_missing: bool = Field(default=False, index=True)


class CacheEntry(SQLModel, table=True):
    __tablename__ = "cache_entries"

    key: str = Field(primary_key=True)
    value_json: dict[str, Any] = Field(sa_column=Column(JsonType), default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    expires_at: Optional[datetime] = Field(default=None, index=True)
