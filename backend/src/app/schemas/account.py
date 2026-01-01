from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


class ApiKeyMetadata(BaseModel):
    id: str
    name: str
    created_at: str
    last_used_at: Optional[str] = None
    is_active: bool
    deactivated_at: Optional[str] = None
    rate_limit_per_min: int
    monthly_token_cap: Optional[int] = None


class CreateApiKeyRequest(BaseModel):
    name: Optional[str] = None
    rate_limit_per_min: Optional[int] = None
    monthly_token_cap: Optional[int] = None


class CreateApiKeyResponse(BaseModel):
    api_key_id: str
    plaintext_key: str
    api_key: ApiKeyMetadata


class RotateApiKeyResponse(BaseModel):
    old_key_id: str
    new_key_id: str
    plaintext_key: str
    new_key: ApiKeyMetadata


class UsageByModelEntry(BaseModel):
    model: str
    attempts: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_estimated: float


class UsageSummaryResponse(BaseModel):
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_cost_estimated: float
    by_model: List[UsageByModelEntry]


class LimitsResponse(BaseModel):
    monthly_token_cap: Optional[int] = None
    month_start: str
    tokens_used_this_month: int
    tokens_remaining: Optional[int] = None
    quota_exceeded: bool

