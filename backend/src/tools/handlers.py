from __future__ import annotations

import time
import uuid
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from .. import config
from ..db.models import UsageEvent
from ..engine.pipeline.runner import BudgetExceeded, PipelineRunner
from ..engine.pipeline import schemas as pipeline_schemas
from ..services.cache import CacheService
from ..services.council_runner import CouncilBudget, CouncilBudgetExceeded, CouncilRunner
from ..services.postgres_store import PostgresConversationStore
from ..services.runs import RunService
from ..services.usage import UsageService
from ..mcp.types import (
    CouncilAskOutput,
    CouncilPipelineAgentOutputs,
    CouncilPipelineOutput,
    UsageByModel,
    UsageSummary,
    is_uuid_string,
)


def mode_config(mode: str) -> tuple[list[str], list[str], str]:
    balanced_models = config.MCP_MODELS_BALANCED or list(config.COUNCIL_MODELS)
    balanced_judges = config.MCP_JUDGES_BALANCED or list(balanced_models)
    balanced_chair = config.MCP_CHAIR_BALANCED or config.CHAIRMAN_MODEL

    if mode == "fast":
        return (
            config.MCP_MODELS_FAST or list(balanced_models),
            config.MCP_JUDGES_FAST or list(balanced_judges),
            config.MCP_CHAIR_FAST or balanced_chair,
        )
    if mode == "deep":
        return (
            config.MCP_MODELS_DEEP or list(balanced_models),
            config.MCP_JUDGES_DEEP or list(balanced_judges),
            config.MCP_CHAIR_DEEP or balanced_chair,
        )
    return list(balanced_models), list(balanced_judges), balanced_chair


async def usage_summary(session: AsyncSession, run_id: uuid.UUID) -> UsageSummary:
    events = (await session.exec(select(UsageEvent).where(UsageEvent.run_id == run_id))).all()

    totals_prompt = [e.prompt_tokens for e in events if e.prompt_tokens is not None]
    totals_completion = [e.completion_tokens for e in events if e.completion_tokens is not None]
    totals_total = [e.total_tokens for e in events if e.total_tokens is not None]
    totals_cost = [e.cost_estimated for e in events if e.cost_estimated is not None]

    by_model: dict[str, list[UsageEvent]] = {}
    for e in events:
        by_model.setdefault(e.model, []).append(e)

    breakdown: list[UsageByModel] = []
    for model, rows in sorted(by_model.items(), key=lambda x: x[0]):
        prompt = [r.prompt_tokens for r in rows if r.prompt_tokens is not None]
        completion = [r.completion_tokens for r in rows if r.completion_tokens is not None]
        total = [r.total_tokens for r in rows if r.total_tokens is not None]
        cost = [r.cost_estimated for r in rows if r.cost_estimated is not None]
        breakdown.append(
            UsageByModel(
                model=model,
                attempts=len(rows),
                prompt_tokens=sum(prompt) if prompt else None,
                completion_tokens=sum(completion) if completion else None,
                total_tokens=sum(total) if total else None,
                cost_estimated=round(sum(cost), 8) if cost else None,
            )
        )

    return UsageSummary(
        total_prompt_tokens=sum(totals_prompt) if totals_prompt else None,
        total_completion_tokens=sum(totals_completion) if totals_completion else None,
        total_tokens=sum(totals_total) if totals_total else None,
        total_cost_estimated=round(sum(totals_cost), 8) if totals_cost else None,
        by_model=breakdown,
    )


def _empty_ask_output(*, conversation_id: str, run_id: str, errors: list[str]) -> dict[str, Any]:
    return CouncilAskOutput(
        final_answer="",
        conversation_id=conversation_id,
        run_id=run_id,
        metadata={"label_to_model": {}, "aggregate_rankings": []},
        usage_summary=UsageSummary(
            total_prompt_tokens=None,
            total_completion_tokens=None,
            total_tokens=None,
            total_cost_estimated=None,
            by_model=[],
        ),
        degraded=True,
        errors=errors,
    ).model_dump()


def _empty_pipeline_output(*, conversation_id: str, run_id: str, errors: list[str]) -> dict[str, Any]:
    return CouncilPipelineOutput(
        run_id=run_id,
        conversation_id=conversation_id,
        scope_contract=None,
        agent_outputs=CouncilPipelineAgentOutputs(),
        final_codex_prompt=None,
        gate_verdict="FAIL",
        degraded=True,
        errors=errors,
        usage_summary=UsageSummary(
            total_prompt_tokens=None,
            total_completion_tokens=None,
            total_tokens=None,
            total_cost_estimated=None,
            by_model=[],
        ),
    ).model_dump()


async def council_ask(
    session: AsyncSession,
    *,
    prompt: str,
    conversation_id: str | None,
    mode: str,
    budget: dict[str, Any] | None,
    owner_key_id: uuid.UUID | None,
    account_root_id: uuid.UUID | None,
    has_api_key: bool,
    tool_call_id: str,
    tool_name: str,
) -> dict[str, Any]:
    errors: list[str] = []
    degraded = False

    store = PostgresConversationStore(
        session=session,
        owner_key_id=owner_key_id,
        account_root_id=account_root_id,
    )

    # Conversation selection / ownership enforcement
    cid: str
    convo: dict[str, Any] | None
    if conversation_id:
        if not is_uuid_string(conversation_id):
            return _empty_ask_output(conversation_id=str(uuid.uuid4()), run_id=str(uuid.uuid4()), errors=["conversation_not_found"])
        cid = conversation_id
        convo = await store.get_conversation(cid)
        if convo is None:
            return _empty_ask_output(conversation_id=cid, run_id=str(uuid.uuid4()), errors=["conversation_not_found"])
    else:
        cid = str(uuid.uuid4())
        await store.create_conversation(cid)
        convo = await store.get_conversation(cid)
        if convo is None:
            return _empty_ask_output(conversation_id=cid, run_id=str(uuid.uuid4()), errors=["internal_error"])

    is_first_message = len(convo["messages"]) == 0
    council_models, judge_models, chair_model = mode_config(mode)

    run_service = RunService(session)
    usage_service = UsageService(session)
    cache_service = CacheService(session)
    runner = CouncilRunner(
        run_service,
        usage_service,
        cache_service,
        council_models=council_models,
        judge_models=judge_models,
        chairman_model=chair_model,
        session=session,
        budget=CouncilBudget(
            max_total_cost_usd=(budget or {}).get("max_total_cost_usd"),
            max_total_tokens=(budget or {}).get("max_total_tokens"),
        )
        if budget
        else None,
        timeout_seconds=config.openrouter_timeout_for_mode(mode),
    )

    started = time.monotonic()
    run_uuid = await runner.start_run(
        uuid.UUID(cid),
        owner_key_id,
        tool_name=tool_name,
        input_json={
            "prompt": prompt,
            "conversation_id": cid if conversation_id else None,
            "mode": mode,
            "budget": budget,
            "has_api_key": has_api_key,
            "tool_call_id": tool_call_id,
            "price_book_version": config.PRICE_BOOK_VERSION,
        },
    )

    # Ensure run exists for timeout/cancel cleanup.
    await session.commit()

    try:
        await store.add_user_message(cid, prompt)

        if is_first_message:
            title = await runner.generate_title(run_uuid, owner_key_id, prompt)
            await store.update_conversation_title(cid, title)

        stage1_results = await runner.stage1(run_uuid, owner_key_id, prompt)
        stage1_models_failed = sorted(set(council_models) - {r["model"] for r in stage1_results})
        for m in stage1_models_failed:
            degraded = True
            errors.append(f"stage1_model_failed:{m}")

        if not stage1_results:
            degraded = True
            errors.append("internal_error")
            stage2_results = []
            stage3_result = {"model": "error", "response": "All models failed to respond. Please try again."}
            metadata = {"label_to_model": {}, "aggregate_rankings": []}
        else:
            stage2_results, label_to_model, aggregate_rankings = await runner.stage2(
                run_uuid, owner_key_id, prompt, stage1_results
            )
            for r in stage2_results:
                if r.get("valid") is False:
                    degraded = True
                    errors.append(f"stage2_invalid_json:{r.get('model')}")

            stage3_result = await runner.stage3(run_uuid, owner_key_id, prompt, stage1_results, stage2_results)
            if str(stage3_result.get("response", "")).startswith("Error:"):
                degraded = True
                errors.append("chairman_failed")

            metadata = {"label_to_model": label_to_model, "aggregate_rankings": aggregate_rankings}

        await store.add_assistant_message(cid, stage1_results, stage2_results, stage3_result)

        status = "succeeded" if not errors else "failed"
        await runner.finish_run(run_uuid, status=status, latency_ms=int((time.monotonic() - started) * 1000))

        summary = await usage_summary(session, run_uuid)
        out = CouncilAskOutput(
            final_answer=str(stage3_result.get("response", "") or ""),
            conversation_id=cid,
            run_id=str(run_uuid),
            metadata=metadata,
            usage_summary=summary,
            degraded=degraded,
            errors=errors,
        )
        return out.model_dump()

    except CouncilBudgetExceeded:
        degraded = True
        errors.append("budget_exceeded")
        await runner.finish_run(run_uuid, status="failed", latency_ms=int((time.monotonic() - started) * 1000))
        summary = await usage_summary(session, run_uuid)
        out = CouncilAskOutput(
            final_answer="",
            conversation_id=cid,
            run_id=str(run_uuid),
            metadata={"label_to_model": {}, "aggregate_rankings": []},
            usage_summary=summary,
            degraded=True,
            errors=errors,
        )
        return out.model_dump()

    except Exception:
        degraded = True
        errors.append("internal_error")
        await runner.finish_run(run_uuid, status="failed", latency_ms=int((time.monotonic() - started) * 1000))
        summary = await usage_summary(session, run_uuid)
        out = CouncilAskOutput(
            final_answer="",
            conversation_id=cid,
            run_id=str(run_uuid),
            metadata={"label_to_model": {}, "aggregate_rankings": []},
            usage_summary=summary,
            degraded=True,
            errors=errors,
        )
        return out.model_dump()


async def council_pipeline(
    session: AsyncSession,
    *,
    task_description: str,
    repo_context: dict[str, Any] | None,
    conversation_id: str | None,
    mode: str,
    max_iterations: int,
    budget: dict[str, Any] | None,
    owner_key_id: uuid.UUID | None,
    account_root_id: uuid.UUID | None,
    has_api_key: bool,
    tool_call_id: str,
    tool_name: str,
) -> dict[str, Any]:
    errors: list[str] = []
    degraded = False

    store = PostgresConversationStore(
        session=session,
        owner_key_id=owner_key_id,
        account_root_id=account_root_id,
    )

    cid: str
    convo: dict[str, Any] | None
    if conversation_id:
        if not is_uuid_string(conversation_id):
            return _empty_pipeline_output(conversation_id=str(uuid.uuid4()), run_id=str(uuid.uuid4()), errors=["conversation_not_found"])
        cid = conversation_id
        convo = await store.get_conversation(cid)
        if convo is None:
            return _empty_pipeline_output(conversation_id=cid, run_id=str(uuid.uuid4()), errors=["conversation_not_found"])
    else:
        cid = str(uuid.uuid4())
        await store.create_conversation(cid)
        convo = await store.get_conversation(cid)
        if convo is None:
            return _empty_pipeline_output(conversation_id=cid, run_id=str(uuid.uuid4()), errors=["internal_error"])

    run_service = RunService(session)
    usage_service = UsageService(session)

    pipeline_budget = (
        pipeline_schemas.PipelineBudget(
            max_total_cost_usd=(budget or {}).get("max_total_cost_usd"),
            max_total_tokens=(budget or {}).get("max_total_tokens"),
        )
        if budget
        else None
    )

    started = time.monotonic()
    run_uuid = await run_service.create_run(
        uuid.UUID(cid),
        tool_name=tool_name,
        input_json={
            "task_description": task_description[: config.MCP_MAX_TASK_CHARS],
            "conversation_id": cid if conversation_id else None,
            "mode": mode,
            "max_iterations": max_iterations,
            "budget": budget,
            "has_repo_context": bool(repo_context and repo_context.get("files")),
            "repo_file_paths": [str(f.get("path")) for f in (repo_context.get("files") or []) if isinstance(f, dict)][:50]
            if repo_context
            else [],
            "has_api_key": has_api_key,
            "tool_call_id": tool_call_id,
            "price_book_version": config.PRICE_BOOK_VERSION,
        },
        owner_key_id=owner_key_id,
    )

    await session.commit()

    runner = PipelineRunner(
        session,
        run_service,
        usage_service,
        mode=mode,
        owner_key_id=owner_key_id,
        run_id=run_uuid,
        max_iterations=max_iterations,
        budget=pipeline_budget,
        timeout_seconds=config.openrouter_timeout_for_mode(mode),
    )

    try:
        await store.add_user_message(cid, task_description)

        result = await runner.run(task_description=task_description, repo_context=repo_context)
        if result.degraded:
            degraded = True
        errors.extend(result.errors)

        status = "succeeded" if result.gate_verdict == "PASS" else "failed"
        await run_service.end_run(run_uuid, status=status, latency_ms=int((time.monotonic() - started) * 1000))

        summary = await usage_summary(session, run_uuid)

        if result.gate_verdict == "PASS" and result.final_codex_prompt:
            summary_msg = "PIPELINE PASS\n\n" + result.final_codex_prompt
        else:
            must_fix = []
            if result.gate and getattr(result.gate, "must_fix", None):
                must_fix = [f"- {m.file}: {m.issue}" for m in result.gate.must_fix[:20]]
            summary_msg = "PIPELINE FAIL"
            if must_fix:
                summary_msg += "\n\nMust-fix:\n" + "\n".join(must_fix)

        await store.add_assistant_message(cid, [], [], {"response": summary_msg})

        out = CouncilPipelineOutput(
            run_id=str(run_uuid),
            conversation_id=cid,
            scope_contract=result.scope_contract,
            agent_outputs=CouncilPipelineAgentOutputs(
                leader=result.scope_contract,
                reviewer=result.reviewer,
                security=result.security,
                test_writer=result.test_writer,
                implementer=result.implementer,
                gate=result.gate,
            ),
            final_codex_prompt=result.final_codex_prompt,
            gate_verdict="PASS" if result.gate_verdict == "PASS" else "FAIL",
            degraded=degraded or bool(errors),
            errors=errors,
            usage_summary=summary,
        )
        return out.model_dump()

    except BudgetExceeded:
        degraded = True
        errors.append("budget_exceeded")
        await run_service.end_run(run_uuid, status="failed", latency_ms=int((time.monotonic() - started) * 1000))
        summary = await usage_summary(session, run_uuid)
        return CouncilPipelineOutput(
            run_id=str(run_uuid),
            conversation_id=cid,
            scope_contract=None,
            agent_outputs=CouncilPipelineAgentOutputs(),
            final_codex_prompt=None,
            gate_verdict="FAIL",
            degraded=True,
            errors=errors,
            usage_summary=summary,
        ).model_dump()

    except Exception:
        degraded = True
        errors.append("internal_error")
        await run_service.end_run(run_uuid, status="failed", latency_ms=int((time.monotonic() - started) * 1000))
        summary = await usage_summary(session, run_uuid)
        return CouncilPipelineOutput(
            run_id=str(run_uuid),
            conversation_id=cid,
            scope_contract=None,
            agent_outputs=CouncilPipelineAgentOutputs(),
            final_codex_prompt=None,
            gate_verdict="FAIL",
            degraded=True,
            errors=errors,
            usage_summary=summary,
        ).model_dump()
