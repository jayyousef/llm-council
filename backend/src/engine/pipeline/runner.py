from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Type

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..openrouter import OpenRouterResult, query_model
from ...db.models import UsageEvent
from ...services.runs import RunService
from ...services.usage import UsageService
from . import model_router, prompts, schemas


class BudgetExceeded(RuntimeError):
    pass


def _truncate(text: str, max_len: int = 20_000) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 20] + "\n...[truncated]..."


def _truncate_json(value: Any, *, max_str_len: int = 20_000) -> Any:
    if isinstance(value, str):
        return _truncate(value, max_str_len)
    if isinstance(value, list):
        return [_truncate_json(v, max_str_len=max_str_len) for v in value]
    if isinstance(value, dict):
        return {str(k): _truncate_json(v, max_str_len=max_str_len) for k, v in value.items()}
    return value


def _normalize_path(value: str) -> str:
    v = value.strip().replace("\\", "/")
    while v.startswith("./"):
        v = v[2:]
    while "//" in v:
        v = v.replace("//", "/")
    return v


def _looks_like_file_path(value: str) -> bool:
    v = value.strip()
    if "://" in v:
        return False
    if "/" in v:
        return True
    for suffix in (".py", ".ts", ".tsx", ".md", ".yml", ".yaml", ".json"):
        if v.endswith(suffix):
            return True
    return False


async def _usage_totals(session: AsyncSession, run_id: uuid.UUID) -> tuple[int | None, float | None, bool, bool]:
    events = (await session.exec(select(UsageEvent).where(UsageEvent.run_id == run_id))).all()
    token_values = [e.total_tokens for e in events if e.total_tokens is not None]
    cost_values = [e.cost_estimated for e in events if e.cost_estimated is not None]
    tokens_missing = any(e.total_tokens is None for e in events)
    cost_missing = any(e.cost_estimated is None for e in events)
    total_tokens = sum(token_values) if token_values else None
    total_cost = round(sum(cost_values), 8) if cost_values else None
    return total_tokens, total_cost, tokens_missing, cost_missing


@dataclass
class PipelineResult:
    scope_contract: schemas.ScopeContract | None
    leader_output: dict[str, Any] | None
    reviewer: schemas.ReviewOutput | None
    security: schemas.SecurityOutput | None
    test_writer: schemas.TestPlanOutput | None
    implementer: schemas.CodexPromptOutput | None
    gate: schemas.GateOutput | None
    gate_verdict: str
    final_codex_prompt: str | None
    degraded: bool
    errors: list[str]


class PipelineRunner:
    def __init__(
        self,
        session: AsyncSession,
        run_service: RunService,
        usage_service: UsageService,
        *,
        mode: str,
        owner_key_id: uuid.UUID | None,
        run_id: uuid.UUID,
        max_iterations: int,
        budget: schemas.PipelineBudget | None,
        timeout_seconds: float | None = None,
    ):
        self._session = session
        self._runs = run_service
        self._usage = usage_service
        self._mode = mode
        self._owner_key_id = owner_key_id
        self._run_id = run_id
        self._max_iterations = max_iterations
        self._budget = budget
        self._models = model_router.resolve_pipeline_models(mode)
        self._db_lock = asyncio.Lock()
        self._timeout_seconds = timeout_seconds

    async def _check_budget(self) -> None:
        if not self._budget:
            return
        total_tokens, total_cost, tokens_missing, cost_missing = await _usage_totals(self._session, self._run_id)

        if self._budget.max_total_tokens is not None:
            if tokens_missing or total_tokens is None:
                raise BudgetExceeded("token_usage_missing")
            if total_tokens > int(self._budget.max_total_tokens):
                raise BudgetExceeded("max_total_tokens")

        if self._budget.max_total_cost_usd is not None:
            if cost_missing or total_cost is None:
                raise BudgetExceeded("cost_estimate_missing")
            if float(total_cost) > float(self._budget.max_total_cost_usd):
                raise BudgetExceeded("max_total_cost_usd")

    async def _call_json_role(
        self,
        *,
        role: str,
        model: str,
        prompt: str,
        schema: Type[Any],
        schema_example: dict[str, Any],
    ) -> tuple[Any | None, str, str | None, bool]:
        """
        Calls a model expecting strict JSON, retries once on JSON/validation failure.
        Returns: (parsed_or_none, final_raw_text, validation_error, ok_response)
        """
        call_id = uuid.uuid4()

        def _try_parse(text: str) -> tuple[Any | None, str | None]:
            try:
                obj = json.loads(text)
                validated = schema.model_validate(obj)  # type: ignore[attr-defined]
                return validated, None
            except Exception as e:
                return None, str(e)

        attempt_prompt = prompt
        last_text = ""
        last_err: str | None = None
        ok_response = False
        for attempt in (0, 1):
            start = time.monotonic()
            result: OpenRouterResult = await query_model(
                model,
                [{"role": "user", "content": attempt_prompt}],
                call_id=call_id,
                attempt=attempt,
                timeout_seconds=self._timeout_seconds,
            )
            latency_ms = int((time.monotonic() - start) * 1000)

            raw_text = (result.content or "").strip()
            last_text = raw_text
            parsed, parse_err = _try_parse(raw_text)
            last_err = parse_err
            ok_response = bool(result.ok and result.content is not None)

            async with self._db_lock:
                await self._usage.record_usage_event(
                    self._owner_key_id,
                    self._run_id,
                    model,
                    result.usage,
                    call_id=call_id,
                    attempt=attempt,
                    latency_ms=result.latency_ms if result.latency_ms is not None else latency_ms,
                    error_text=result.error_text,
                )

                output_json: dict[str, Any]
                if parsed is not None and parse_err is None:
                    output_json = {"parsed_json": _truncate_json(parsed.model_dump())}
                else:
                    output_json = {"raw_text": _truncate(raw_text), "validation_error": parse_err}

                await self._runs.add_run_step(
                    self._run_id,
                    stage_name="pipeline",
                    step_type="pipeline_step",
                    agent_role=role,
                    model=model,
                    attempt=attempt,
                    is_retry=attempt > 0,
                    output_json=output_json,
                    latency_ms=result.latency_ms if result.latency_ms is not None else latency_ms,
                    error_text=result.error_text or parse_err,
                )

                await self._check_budget()

            if parsed is not None and parse_err is None:
                return parsed, raw_text, None, ok_response

            if attempt == 0:
                attempt_prompt = f"""Your previous output was invalid.
You MUST output ONLY valid JSON matching this example schema exactly:
{json.dumps(schema_example, ensure_ascii=False)}

Here was your previous output:
{_truncate(raw_text, 8000)}

Error:
{parse_err}
"""
                continue

        return None, last_text, last_err, ok_response

    async def run(self, *, task_description: str, repo_context: dict[str, Any] | None) -> PipelineResult:
        errors: list[str] = []
        degraded = False

        # Leader: scope contract
        leader_prompt, leader_example = prompts.leader_scope_prompt(
            task_description=task_description,
            repo_context=repo_context,
            max_iterations=self._max_iterations,
            budget=self._budget,
        )
        scope, _raw, err, _ok = await self._call_json_role(
            role="leader",
            model=self._models.leader,
            prompt=leader_prompt,
            schema=schemas.ScopeContract,
            schema_example=leader_example,
        )
        if scope is None:
            degraded = True
            errors.append("invalid_json:leader")
            return PipelineResult(
                scope_contract=None,
                leader_output=None,
                reviewer=None,
                security=None,
                test_writer=None,
                implementer=None,
                gate=None,
                gate_verdict="FAIL",
                final_codex_prompt=None,
                degraded=True,
                errors=errors,
            )

        scope_contract: schemas.ScopeContract = scope

        agents = set(scope_contract.agents_to_invoke or [])
        agents.update({"implementer", "gate"})  # always

        reviewer: schemas.ReviewOutput | None = None
        security: schemas.SecurityOutput | None = None
        test_plan: schemas.TestPlanOutput | None = None
        implementer: schemas.CodexPromptOutput | None = None
        gate: schemas.GateOutput | None = None

        # Reviewer
        async def _run_reviewer() -> schemas.ReviewOutput | None:
            p, ex = prompts.reviewer_prompt(task_description=task_description, scope=scope_contract, repo_context=repo_context)
            obj, _t, _e, _ok = await self._call_json_role(
                role="reviewer", model=self._models.reviewer, prompt=p, schema=schemas.ReviewOutput, schema_example=ex
            )
            return obj

        async def _run_security() -> schemas.SecurityOutput | None:
            p, ex = prompts.security_prompt(task_description=task_description, scope=scope_contract, repo_context=repo_context)
            obj, _t, _e, _ok = await self._call_json_role(
                role="security", model=self._models.security, prompt=p, schema=schemas.SecurityOutput, schema_example=ex
            )
            return obj

        if "reviewer" in agents and "security" in agents and self._budget is None:
            reviewer_obj, security_obj = await asyncio.gather(_run_reviewer(), _run_security())
            reviewer = reviewer_obj
            security = security_obj
            if reviewer is None:
                degraded = True
                errors.append("invalid_json:reviewer")
            if security is None:
                degraded = True
                errors.append("invalid_json:security")
        else:
            if "reviewer" in agents:
                reviewer = await _run_reviewer()
                if reviewer is None:
                    degraded = True
                    errors.append("invalid_json:reviewer")
            if "security" in agents:
                security = await _run_security()
                if security is None:
                    degraded = True
                    errors.append("invalid_json:security")

        tests_needed = bool(scope_contract.tests_policy.required)
        if reviewer and reviewer.tests_recommended:
            tests_needed = True
        if security and security.tests_required:
            tests_needed = True

        if tests_needed and "test_writer" in agents:
            p, ex = prompts.test_writer_prompt(
                task_description=task_description,
                scope=scope_contract,
                reviewer=reviewer,
                security=security,
                repo_context=repo_context,
            )
            test_obj, _t, e, _ok = await self._call_json_role(
                role="test_writer", model=self._models.test_writer, prompt=p, schema=schemas.TestPlanOutput, schema_example=ex
            )
            test_plan = test_obj
            if test_plan is None:
                degraded = True
                errors.append("invalid_json:test_writer")

        # Implementer
        p, ex = prompts.implementer_prompt(
            task_description=task_description,
            scope=scope_contract,
            reviewer=reviewer,
            security=security,
            test_plan=test_plan,
            repo_context=repo_context,
        )
        impl_obj, _t, e, _ok = await self._call_json_role(
            role="implementer", model=self._models.implementer, prompt=p, schema=schemas.CodexPromptOutput, schema_example=ex
        )
        implementer = impl_obj
        if implementer is None:
            degraded = True
            errors.append("invalid_json:implementer")
            return PipelineResult(
                scope_contract=scope_contract,
                leader_output=scope_contract.model_dump(),
                reviewer=reviewer,
                security=security,
                test_writer=test_plan,
                implementer=None,
                gate=None,
                gate_verdict="FAIL",
                final_codex_prompt=None,
                degraded=True,
                errors=errors,
            )

        def _enforce_scope_paths(sc: schemas.ScopeContract, impl: schemas.CodexPromptOutput) -> list[str]:
            allowed = [s for s in sc.in_scope if isinstance(s, str) and _looks_like_file_path(s)]
            if not allowed:
                return []
            allowed_set = set(_normalize_path(a) for a in allowed if isinstance(a, str) and a.strip())
            patch = [_normalize_path(p) for p in (impl.patch_scope or []) if isinstance(p, str) and p.strip()]
            if not patch:
                return ["(patch_scope_missing)"]
            return [p for p in patch if p not in allowed_set]

        violations = _enforce_scope_paths(scope_contract, implementer)
        if violations:
            degraded = True
            errors.append("scope_violation")
            gate = schemas.GateOutput(
                verdict="FAIL",
                must_fix=[
                    schemas.MustFixItem(
                        severity="high",
                        file=v,
                        issue=(
                            "patch_scope is empty"
                            if v == "(patch_scope_missing)"
                            else "patch_scope includes file outside in_scope"
                        ),
                        suggested_fix=(
                            "Populate patch_scope with the files that will be changed."
                            if v == "(patch_scope_missing)"
                            else "Remove from patch_scope or add to in_scope if truly required."
                        ),
                    )
                    for v in violations
                ],
                acceptance_criteria_met=[schemas.AcceptanceCriterionMet(criterion=c, met=False) for c in scope_contract.acceptance_criteria],
                tests_required=bool(scope_contract.tests_policy.required),
            )
            async with self._db_lock:
                await self._runs.add_run_step(
                    self._run_id,
                    stage_name="pipeline",
                    step_type="pipeline_step",
                    agent_role="gate",
                    model="deterministic",
                    attempt=0,
                    is_retry=False,
                    output_json={"parsed_json": _truncate_json(gate.model_dump())},
                    latency_ms=0,
                    error_text="scope_violation",
                )
            return PipelineResult(
                scope_contract=scope_contract,
                leader_output=scope_contract.model_dump(),
                reviewer=reviewer,
                security=security,
                test_writer=test_plan,
                implementer=implementer,
                gate=gate,
                gate_verdict="FAIL",
                final_codex_prompt=None,
                degraded=True,
                errors=errors,
            )

        # Iteration loop: initial gate, then revise+gate up to max_iterations.
        for iteration in range(self._max_iterations):
            g_prompt, g_ex = prompts.gate_prompt(
                task_description=task_description,
                scope=scope_contract,
                reviewer=reviewer,
                security=security,
                test_plan=test_plan,
                implementer=implementer,
            )
            gate_obj, _t, e, _ok = await self._call_json_role(
                role="gate", model=self._models.gate, prompt=g_prompt, schema=schemas.GateOutput, schema_example=g_ex
            )
            gate = gate_obj
            if gate is None:
                degraded = True
                errors.append("invalid_json:gate")
                return PipelineResult(
                    scope_contract=scope_contract,
                    leader_output=scope_contract.model_dump(),
                    reviewer=reviewer,
                    security=security,
                    test_writer=test_plan,
                    implementer=implementer,
                    gate=None,
                    gate_verdict="FAIL",
                    final_codex_prompt=None,
                    degraded=True,
                    errors=errors,
                )

            if gate.verdict == "PASS":
                return PipelineResult(
                    scope_contract=scope_contract,
                    leader_output=scope_contract.model_dump(),
                    reviewer=reviewer,
                    security=security,
                    test_writer=test_plan,
                    implementer=implementer,
                    gate=gate,
                    gate_verdict="PASS",
                    final_codex_prompt=implementer.final_codex_prompt,
                    degraded=degraded,
                    errors=errors,
                )

            if iteration >= self._max_iterations - 1:
                break

            # Revision: constrain to must_fix only.
            p, ex = prompts.implementer_revision_prompt(
                task_description=task_description,
                scope=scope_contract,
                previous_prompt=implementer,
                must_fix=gate.must_fix,
            )
            revised_obj, _t, e, _ok = await self._call_json_role(
                role="implementer",
                model=self._models.leader,
                prompt=p,
                schema=schemas.CodexPromptOutput,
                schema_example=ex,
            )
            if revised_obj is None:
                degraded = True
                errors.append("invalid_json:implementer")
                break
            implementer = revised_obj

            violations = _enforce_scope_paths(scope_contract, implementer)
            if violations:
                degraded = True
                errors.append("scope_violation")
                gate = schemas.GateOutput(
                    verdict="FAIL",
                    must_fix=[
                        schemas.MustFixItem(
                            severity="high",
                            file=v,
                            issue=(
                                "patch_scope is empty"
                                if v == "(patch_scope_missing)"
                                else "patch_scope includes file outside in_scope"
                            ),
                            suggested_fix=(
                                "Populate patch_scope with the files that will be changed."
                                if v == "(patch_scope_missing)"
                                else "Remove from patch_scope or add to in_scope if truly required."
                            ),
                        )
                        for v in violations
                    ],
                    acceptance_criteria_met=[schemas.AcceptanceCriterionMet(criterion=c, met=False) for c in scope_contract.acceptance_criteria],
                    tests_required=bool(scope_contract.tests_policy.required),
                )
                async with self._db_lock:
                    await self._runs.add_run_step(
                        self._run_id,
                        stage_name="pipeline",
                        step_type="pipeline_step",
                        agent_role="gate",
                        model="deterministic",
                        attempt=0,
                        is_retry=False,
                        output_json={"parsed_json": _truncate_json(gate.model_dump())},
                        latency_ms=0,
                        error_text="scope_violation",
                    )
                break

        return PipelineResult(
            scope_contract=scope_contract,
            leader_output=scope_contract.model_dump(),
            reviewer=reviewer,
            security=security,
            test_writer=test_plan,
            implementer=implementer,
            gate=gate,
            gate_verdict="FAIL",
            final_codex_prompt=None,
            degraded=True if errors else degraded,
            errors=errors,
        )
