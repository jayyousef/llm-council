from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from ..config import CHAIRMAN_MODEL, COUNCIL_MODELS
from ..db.models import UsageEvent
from ..engine.openrouter import OpenRouterResult, query_model
from ..engine.schemas import Stage2JudgeOutput
from ..engine.council import calculate_aggregate_rankings
from .cache import CacheService, make_cache_key
from .runs import RunService
from .usage import UsageService
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession


@dataclass(frozen=True)
class CouncilBudget:
    max_total_cost_usd: float | None = None
    max_total_tokens: int | None = None


class CouncilBudgetExceeded(RuntimeError):
    pass


async def _usage_totals(session: AsyncSession, run_id: uuid.UUID) -> tuple[int | None, float | None, bool, bool]:
    events = (await session.exec(select(UsageEvent).where(UsageEvent.run_id == run_id))).all()
    token_values = [e.total_tokens for e in events if e.total_tokens is not None]
    cost_values = [e.cost_estimated for e in events if e.cost_estimated is not None]
    tokens_missing = any(e.total_tokens is None for e in events)
    cost_missing = any(e.cost_estimated is None for e in events)
    total_tokens = sum(token_values) if token_values else None
    total_cost = round(sum(cost_values), 8) if cost_values else None
    return total_tokens, total_cost, tokens_missing, cost_missing


def _truncate_text(value: str | None, max_len: int = 20_000) -> str | None:
    if value is None:
        return None
    if len(value) <= max_len:
        return value
    return value[: max_len - 20] + "\n...[truncated]..."


def _stage1_cache_parts(model: str, user_query: str) -> dict[str, Any]:
    return {"stage": "stage1", "model": model, "user_query": user_query, "council_models": COUNCIL_MODELS}


def _stage2_schema_example() -> dict[str, Any]:
    return {
        "evaluations": [
            {"label": "Response A", "pros": ["..."], "cons": ["..."]},
            {"label": "Response B", "pros": ["..."], "cons": ["..."]},
        ],
        "final_ranking": ["Response A", "Response B"],
        "failure_modes_top1": ["..."],
        "verification_steps": ["..."],
    }


def _build_stage2_prompt(user_query: str, stage1_results: List[Dict[str, Any]]) -> tuple[str, dict[str, str]]:
    labels = [chr(65 + i) for i in range(len(stage1_results))]
    label_to_model = {
        f"Response {label}": result["model"] for label, result in zip(labels, stage1_results)
    }
    responses_text = "\n\n".join(
        [f"Response {label}:\n{result['response']}" for label, result in zip(labels, stage1_results)]
    )
    schema_example = _stage2_schema_example()
    prompt = f"""You are evaluating different responses to the following question:

Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

Return ONLY valid JSON matching this exact schema (no markdown, no extra text):
{json.dumps(schema_example, ensure_ascii=False)}

Rules:
- "evaluations" must include one entry per response label present above.
- "final_ranking" must be a list of the response labels from best to worst.
- "failure_modes_top1" must list likely failure modes of the top-ranked response.
- "verification_steps" must list concrete steps a user can take to verify the top-ranked response.
"""
    return prompt, label_to_model


def _stage2_cache_parts(model: str, user_query: str, stage2_prompt: str) -> dict[str, Any]:
    return {"stage": "stage2", "model": model, "user_query": user_query, "prompt": stage2_prompt}


def _build_stage3_prompt(user_query: str, stage1_results: List[Dict[str, Any]], stage2_results: List[Dict[str, Any]]) -> str:
    stage1_text = "\n\n".join(
        [f"Model: {r['model']}\nResponse: {r['response']}" for r in stage1_results]
    )
    stage2_text = "\n\n".join(
        [f"Model: {r['model']}\nRanking: {r['ranking']}" for r in stage2_results]
    )

    verification_steps: list[str] = []
    for r in stage2_results:
        parsed = r.get("parsed_json") if isinstance(r, dict) else None
        if isinstance(parsed, dict):
            steps = parsed.get("verification_steps")
            if isinstance(steps, list):
                verification_steps.extend([str(s) for s in steps if s])

    verification_text = ""
    if verification_steps:
        deduped: list[str] = []
        seen = set()
        for s in verification_steps:
            if s not in seen:
                seen.add(s)
                deduped.append(s)
        verification_text = "\n\nJudges suggested verification steps:\n" + "\n".join(
            [f"- {s}" for s in deduped[:12]]
        )

    return f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Rankings:
{stage2_text}
{verification_text}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question.

When relevant, include a short "Verification checklist" section with concrete steps the user can take to validate the answer.
"""


class CouncilRunner:
    def __init__(
        self,
        run_service: RunService,
        usage_service: UsageService,
        cache_service: CacheService,
        *,
        council_models: list[str] | None = None,
        judge_models: list[str] | None = None,
        chairman_model: str | None = None,
        session: AsyncSession | None = None,
        budget: CouncilBudget | None = None,
        timeout_seconds: float | None = None,
    ):
        self._runs = run_service
        self._usage = usage_service
        self._cache = cache_service
        self._council_models = list(COUNCIL_MODELS) if council_models is None else list(council_models)
        self._judge_models = list(self._council_models) if judge_models is None else list(judge_models)
        self._chairman_model = CHAIRMAN_MODEL if chairman_model is None else chairman_model
        self._session = session
        self._budget = budget
        self._timeout_seconds = timeout_seconds
        self._budget_lock = asyncio.Lock()

    async def _check_budget(self, run_id: uuid.UUID) -> None:
        if self._budget is None:
            return
        if self._session is None:
            return
        async with self._budget_lock:
            total_tokens, total_cost, tokens_missing, cost_missing = await _usage_totals(self._session, run_id)
            if self._budget.max_total_tokens is not None:
                if tokens_missing or total_tokens is None:
                    raise CouncilBudgetExceeded("token_usage_missing")
                if total_tokens > int(self._budget.max_total_tokens):
                    raise CouncilBudgetExceeded("max_total_tokens")
            if self._budget.max_total_cost_usd is not None:
                if cost_missing or total_cost is None:
                    raise CouncilBudgetExceeded("cost_estimate_missing")
                if float(total_cost) > float(self._budget.max_total_cost_usd):
                    raise CouncilBudgetExceeded("max_total_cost_usd")

    async def start_run(
        self,
        conversation_id: uuid.UUID,
        owner_key_id: uuid.UUID | None,
        *,
        tool_name: str,
        input_json: dict[str, Any],
    ) -> uuid.UUID:
        return await self._runs.create_run(conversation_id, tool_name, input_json, owner_key_id)

    async def finish_run(self, run_id: uuid.UUID, status: str, latency_ms: int | None) -> None:
        await self._runs.end_run(run_id, status=status, latency_ms=latency_ms)

    async def generate_title(self, run_id: uuid.UUID, owner_key_id: uuid.UUID | None, user_query: str) -> str:
        title_prompt = f"""Generate a very short title (3-5 words maximum) that summarizes the following question.
The title should be concise and descriptive. Do not use quotes or punctuation in the title.

Question: {user_query}

Title:"""
        model = "google/gemini-2.5-flash"
        call_id = uuid.uuid4()
        start = time.monotonic()
        result = await query_model(
            model,
            [{"role": "user", "content": title_prompt}],
            timeout_seconds=30.0,
            call_id=call_id,
            attempt=0,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        await self._usage.record_usage_event(
            owner_key_id,
            run_id,
            model,
            result.usage,
            call_id=call_id,
            attempt=0,
            latency_ms=latency_ms,
            error_text=result.error_text,
        )
        await self._check_budget(run_id)
        await self._runs.add_run_step(
            run_id,
            stage_name="title",
            step_type="title",
            agent_role="system",
            model=model,
            attempt=0,
            is_retry=False,
            output_json={"content": _truncate_text(result.content), "ok": result.ok},
            latency_ms=latency_ms,
            error_text=result.error_text,
        )

        if not result.ok or result.content is None:
            return "New Conversation"

        title = (result.content or "New Conversation").strip().strip("\"'")
        if len(title) > 50:
            title = title[:47] + "..."
        return title

    async def stage1(self, run_id: uuid.UUID, owner_key_id: uuid.UUID | None, user_query: str) -> List[Dict[str, Any]]:
        stage1_results: list[dict[str, Any]] = []
        messages = [{"role": "user", "content": user_query}]

        async def _one(model: str) -> tuple[str, OpenRouterResult | None, str | None]:
            cache_key = make_cache_key(_stage1_cache_parts(model, user_query))
            cached = await self._cache.get_json(cache_key)
            if cached and isinstance(cached.get("content"), str):
                content = cached["content"]
                await self._runs.add_run_step(
                    run_id,
                    stage_name="stage1",
                    step_type="stage1",
                    agent_role="council_member",
                    model=model,
                    attempt=0,
                    is_retry=False,
                    output_json={"content": _truncate_text(content), "cache_hit": True},
                    latency_ms=0,
                    error_text=None,
                )
                return model, None, content

            call_id = uuid.uuid4()
            result = await query_model(
                model,
                messages,
                call_id=call_id,
                attempt=0,
                timeout_seconds=self._timeout_seconds,
            )
            await self._usage.record_usage_event(
                owner_key_id,
                run_id,
                model,
                result.usage,
                call_id=call_id,
                attempt=0,
                latency_ms=result.latency_ms,
                error_text=result.error_text,
            )
            await self._check_budget(run_id)
            await self._runs.add_run_step(
                run_id,
                stage_name="stage1",
                step_type="stage1",
                agent_role="council_member",
                model=model,
                attempt=0,
                is_retry=False,
                output_json={"content": _truncate_text(result.content), "cache_hit": False},
                latency_ms=result.latency_ms,
                error_text=result.error_text,
            )
            if result.ok and result.content is not None:
                await self._cache.set_json(cache_key, {"content": result.content})
                return model, result, result.content
            return model, result, None

        if self._budget is not None:
            results = []
            for m in self._council_models:
                results.append(await _one(m))
        else:
            results = await asyncio.gather(*[_one(m) for m in self._council_models])
        for model, _result, content in results:
            if content is not None:
                stage1_results.append({"model": model, "response": content})
        return stage1_results

    async def stage2(
        self,
        run_id: uuid.UUID,
        owner_key_id: uuid.UUID | None,
        user_query: str,
        stage1_results: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], Dict[str, str], List[Dict[str, Any]]]:
        prompt, label_to_model = _build_stage2_prompt(user_query, stage1_results)
        schema_example = _stage2_schema_example()

        async def _judge(model: str) -> dict[str, Any] | None:
            cache_key = make_cache_key(_stage2_cache_parts(model, user_query, prompt))
            cached = await self._cache.get_json(cache_key)
            if cached and isinstance(cached.get("ranking"), str):
                out = dict(cached)
                await self._runs.add_run_step(
                    run_id,
                    stage_name="stage2",
                    step_type="stage2",
                    agent_role="council_member",
                    model=model,
                    attempt=0,
                    is_retry=False,
                    output_json={"cache_hit": True, **out},
                    latency_ms=0,
                    error_text=None,
                )
                # Cached entries are assumed valid only if explicitly marked.
                out.setdefault("valid", bool(out.get("parsed_json")) and not out.get("validation_error"))
                return {"model": model, **out}

            call_id = uuid.uuid4()
            first = await query_model(
                model,
                [{"role": "user", "content": prompt}],
                call_id=call_id,
                attempt=0,
                timeout_seconds=self._timeout_seconds,
            )
            await self._usage.record_usage_event(
                owner_key_id,
                run_id,
                model,
                first.usage,
                call_id=call_id,
                attempt=0,
                latency_ms=first.latency_ms,
                error_text=first.error_text,
            )
            await self._check_budget(run_id)

            raw_text = first.content or ""
            parsed_ranking: list[str] = []
            parsed_json: dict[str, Any] | None = None
            validation_error: str | None = None
            valid = False

            def _try_parse(text: str) -> tuple[list[str], dict[str, Any] | None, str | None]:
                try:
                    obj = json.loads(text)
                    validated = Stage2JudgeOutput.model_validate(obj)
                    return validated.final_ranking, validated.model_dump(), None
                except Exception as e:
                    return [], None, str(e)

            parsed_ranking, parsed_json, validation_error = _try_parse(raw_text)
            valid = validation_error is None and parsed_json is not None and len(parsed_ranking) > 0
            await self._runs.add_run_step(
                run_id,
                stage_name="stage2",
                step_type="stage2",
                agent_role="council_member",
                model=model,
                attempt=0,
                is_retry=False,
                output_json={"raw_text": _truncate_text(raw_text), "parsed_json": parsed_json, "validation_error": validation_error},
                latency_ms=first.latency_ms,
                error_text=first.error_text or (validation_error if validation_error else None),
            )

            if (not first.ok) or first.content is None:
                return None

            if validation_error:
                correction_prompt = f"""Your previous output was invalid.
You MUST output ONLY valid JSON matching this schema:
{json.dumps(schema_example, ensure_ascii=False)}

Here was your previous output:
{raw_text}

Error:
{validation_error}
"""
                retry = await query_model(
                    model,
                    [{"role": "user", "content": correction_prompt}],
                    call_id=call_id,
                    attempt=1,
                    timeout_seconds=self._timeout_seconds,
                )
                await self._usage.record_usage_event(
                    owner_key_id,
                    run_id,
                    model,
                    retry.usage,
                    call_id=call_id,
                    attempt=1,
                    latency_ms=retry.latency_ms,
                    error_text=retry.error_text,
                )
                await self._check_budget(run_id)
                if retry.ok and retry.content is not None:
                    raw_text = retry.content
                    parsed_ranking, parsed_json, validation_error = _try_parse(raw_text)
                    valid = validation_error is None and parsed_json is not None and len(parsed_ranking) > 0
                else:
                    valid = False

                await self._runs.add_run_step(
                    run_id,
                    stage_name="stage2",
                    step_type="stage2",
                    agent_role="council_member",
                    model=model,
                    attempt=1,
                    is_retry=True,
                    output_json={"raw_text": _truncate_text(raw_text), "parsed_json": parsed_json, "validation_error": validation_error},
                    latency_ms=retry.latency_ms,
                    error_text=retry.error_text or (validation_error if validation_error else None),
                )

            out = {
                "ranking": raw_text,
                "parsed_ranking": parsed_ranking,
                "parsed_json": parsed_json,
                "validation_error": validation_error,
                "valid": bool(valid),
            }
            if out["valid"]:
                await self._cache.set_json(cache_key, out)
            return {"model": model, **out}

        if self._budget is not None:
            judges = []
            for m in self._judge_models:
                judges.append(await _judge(m))
        else:
            judges = await asyncio.gather(*[_judge(m) for m in self._judge_models])
        stage2_results = [j for j in judges if j is not None]
        aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
        return stage2_results, label_to_model, aggregate_rankings

    async def stage3(
        self,
        run_id: uuid.UUID,
        owner_key_id: uuid.UUID | None,
        user_query: str,
        stage1_results: List[Dict[str, Any]],
        stage2_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        prompt = _build_stage3_prompt(user_query, stage1_results, stage2_results)
        call_id = uuid.uuid4()
        result = await query_model(
            self._chairman_model,
            [{"role": "user", "content": prompt}],
            call_id=call_id,
            attempt=0,
            timeout_seconds=self._timeout_seconds,
        )
        await self._usage.record_usage_event(
            owner_key_id,
            run_id,
            self._chairman_model,
            result.usage,
            call_id=call_id,
            attempt=0,
            latency_ms=result.latency_ms,
            error_text=result.error_text,
        )
        await self._check_budget(run_id)
        await self._runs.add_run_step(
            run_id,
            stage_name="stage3",
            step_type="stage3",
            agent_role="leader",
            model=self._chairman_model,
            attempt=0,
            is_retry=False,
            output_json={"content": _truncate_text(result.content), "ok": result.ok},
            latency_ms=result.latency_ms,
            error_text=result.error_text,
        )
        if not result.ok or result.content is None:
            return {"model": self._chairman_model, "response": "Error: Unable to generate final synthesis."}
        return {"model": self._chairman_model, "response": result.content or ""}
