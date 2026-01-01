from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Severity = Literal["high", "med", "low"]


class PipelineBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_total_cost_usd: float | None = None
    max_total_tokens: int | None = None


class TestsPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool
    reasons: list[str] = Field(default_factory=list)


AgentToInvoke = Literal["reviewer", "security", "test_writer", "implementer", "gate"]


class ScopeContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_summary: str
    in_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    agents_to_invoke: list[AgentToInvoke] = Field(default_factory=list)
    tests_policy: TestsPolicy
    constraints: list[str] = Field(default_factory=list)
    max_iterations: int = 2
    budget: PipelineBudget | None = None


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    file: str
    issue: str
    why: str
    suggested_fix: str


class ReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["PASS", "FAIL"]
    issues: list[ReviewIssue] = Field(default_factory=list)
    missed_requirements: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    tests_recommended: list[str] = Field(default_factory=list)


ThreatArea = Literal["auth", "db", "logging", "network", "deps", "supply_chain"]


class SecurityThreat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    area: ThreatArea
    description: str
    mitigation: str


class SecurityOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["PASS", "FAIL"]
    threats: list[SecurityThreat] = Field(default_factory=list)
    required_security_controls: list[str] = Field(default_factory=list)
    tests_required: list[str] = Field(default_factory=list)


TestType = Literal["unit", "integration"]


class TestToAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: TestType
    target: str
    files: list[str] = Field(default_factory=list)
    cases: list[str] = Field(default_factory=list)


class TestPlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tests_to_add: list[TestToAdd] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CodexPromptOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_codex_prompt: str
    patch_scope: list[str] = Field(default_factory=list)
    do_not_change: list[str] = Field(default_factory=list)
    run_commands: list[str] = Field(default_factory=list)
    rollback_plan: list[str] = Field(default_factory=list)


class MustFixItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    file: str
    issue: str
    suggested_fix: str


class AcceptanceCriterionMet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion: str
    met: bool


class GateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["PASS", "FAIL"]
    must_fix: list[MustFixItem] = Field(default_factory=list)
    acceptance_criteria_met: list[AcceptanceCriterionMet] = Field(default_factory=list)
    tests_required: bool

