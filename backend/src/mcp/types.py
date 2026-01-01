from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from .. import config

from ..engine.pipeline import schemas as pipeline_schemas


Mode = Literal["fast", "balanced", "deep"]


class CouncilAskInput(BaseModel):
    prompt: str = Field(min_length=1)
    conversation_id: Optional[str] = None
    mode: Mode = "balanced"
    budget: Optional["BudgetInput"] = None
    api_key: Optional[str] = None

    @field_validator("prompt")
    @classmethod
    def _prompt_size_limit(cls, v: str) -> str:
        if len(v) > config.MCP_MAX_PROMPT_CHARS:
            raise ValueError("input_too_large")
        return v


class UsageByModel(BaseModel):
    model: str
    attempts: int
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost_estimated: float | None


class UsageSummary(BaseModel):
    total_prompt_tokens: int | None
    total_completion_tokens: int | None
    total_tokens: int | None
    total_cost_estimated: float | None
    by_model: list[UsageByModel]


class CouncilAskOutput(BaseModel):
    final_answer: str
    conversation_id: str
    run_id: str
    metadata: dict[str, Any]
    usage_summary: UsageSummary
    degraded: bool
    errors: list[str]


class RepoContextFile(BaseModel):
    path: str = Field(min_length=1)
    content: Optional[str] = None
    summary: Optional[str] = None

    @field_validator("path")
    @classmethod
    def _path_limit(cls, v: str) -> str:
        if len(v) > config.MCP_MAX_PATH_CHARS:
            raise ValueError("input_too_large")
        return v


class RepoContext(BaseModel):
    files: list[RepoContextFile] = Field(default_factory=list)

    @model_validator(mode="after")
    def _repo_limits(self):
        if len(self.files) > config.MCP_MAX_REPO_FILES:
            raise ValueError("input_too_large")
        total = 0
        for f in self.files:
            if f.content:
                total += len(f.content)
            if f.summary:
                total += len(f.summary)
            if total > config.MCP_MAX_REPO_TOTAL_CHARS:
                raise ValueError("input_too_large")
        return self


class BudgetInput(BaseModel):
    max_total_cost_usd: float | None = None
    max_total_tokens: int | None = None


class CouncilPipelineInput(BaseModel):
    task_description: str = Field(min_length=1)
    repo_context: Optional[RepoContext] = None
    conversation_id: Optional[str] = None
    mode: Mode = "balanced"
    max_iterations: int = 2
    budget: Optional[BudgetInput] = None
    api_key: Optional[str] = None

    @field_validator("task_description")
    @classmethod
    def _task_size_limit(cls, v: str) -> str:
        if len(v) > config.MCP_MAX_TASK_CHARS:
            raise ValueError("input_too_large")
        return v

    @field_validator("max_iterations")
    @classmethod
    def _clamp_max_iterations(cls, v: int) -> int:
        # Default is 2, hard max is 4 (bounded loops).
        if v < 1:
            return 1
        if v > 4:
            return 4
        return v


class CouncilPipelineAgentOutputs(BaseModel):
    leader: pipeline_schemas.ScopeContract | None = None
    reviewer: pipeline_schemas.ReviewOutput | None = None
    security: pipeline_schemas.SecurityOutput | None = None
    test_writer: pipeline_schemas.TestPlanOutput | None = None
    implementer: pipeline_schemas.CodexPromptOutput | None = None
    gate: pipeline_schemas.GateOutput | None = None


GateVerdict = Literal["PASS", "FAIL"]


class CouncilPipelineOutput(BaseModel):
    run_id: str
    conversation_id: str
    scope_contract: pipeline_schemas.ScopeContract | None
    agent_outputs: CouncilPipelineAgentOutputs
    final_codex_prompt: str | None
    gate_verdict: GateVerdict
    degraded: bool
    errors: list[str]
    usage_summary: UsageSummary


class CouncilAskHttpInput(BaseModel):
    prompt: str = Field(min_length=1)
    conversation_id: Optional[str] = None
    mode: Mode = "balanced"
    budget: Optional[BudgetInput] = None

    model_config = {"extra": "forbid"}

    @field_validator("prompt")
    @classmethod
    def _prompt_size_limit(cls, v: str) -> str:
        if len(v) > config.MCP_MAX_PROMPT_CHARS:
            raise ValueError("input_too_large")
        return v


class CouncilPipelineHttpInput(BaseModel):
    task_description: str = Field(min_length=1)
    repo_context: Optional[RepoContext] = None
    conversation_id: Optional[str] = None
    mode: Mode = "balanced"
    max_iterations: int = 2
    budget: Optional[BudgetInput] = None

    model_config = {"extra": "forbid"}

    @field_validator("task_description")
    @classmethod
    def _task_size_limit(cls, v: str) -> str:
        if len(v) > config.MCP_MAX_TASK_CHARS:
            raise ValueError("input_too_large")
        return v

    @field_validator("max_iterations")
    @classmethod
    def _clamp_max_iterations(cls, v: int) -> int:
        if v < 1:
            return 1
        if v > 4:
            return 4
        return v


def is_uuid_string(value: str) -> bool:
    try:
        UUID(value)
        return True
    except Exception:
        return False


CouncilAskInput.model_rebuild()
