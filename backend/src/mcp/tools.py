from __future__ import annotations

import os
import asyncio
import logging
import time
import uuid
from typing import Any

from mcp import types as mcp_types
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from .. import config
from ..db.models import Conversation, UsageEvent
from ..engine.openrouter import set_client
from ..engine.pipeline.runner import BudgetExceeded, PipelineRunner
from ..engine.pipeline import schemas as pipeline_schemas
from ..services.cache import CacheService
from ..services.council_runner import CouncilRunner, CouncilBudget, CouncilBudgetExceeded
from ..services.postgres_store import PostgresConversationStore
from ..services.runs import RunService
from ..services.usage import UsageService
from ..tools import handlers as shared_handlers
from .auth import resolve_mcp_api_key
from .types import (
    CouncilAskInput,
    CouncilAskOutput,
    CouncilPipelineAgentOutputs,
    CouncilPipelineInput,
    CouncilPipelineOutput,
    UsageByModel,
    UsageSummary,
    is_uuid_string,
)

logger = logging.getLogger(__name__)


def _mode_config(mode: str) -> tuple[list[str], list[str], str]:
    # Defaults:
    # - balanced: existing COUNCIL_MODELS + CHAIRMAN_MODEL
    # - fast/deep: fall back to balanced unless env overrides provided
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


async def _usage_summary(session: AsyncSession, run_id: uuid.UUID) -> UsageSummary:
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

async def dispatch_tool(
    session: AsyncSession,
    name: str,
    arguments: dict[str, Any],
    *,
    run_info: dict[str, Any],
) -> dict[str, Any]:
    # run_info is used by runtime guards to finalize a run even on timeout/cancellation.
    if name == "council.ask":
        return await handle_council_ask(session, arguments, run_info=run_info)
    if name == "council.pipeline":
        return await handle_council_pipeline(session, arguments, run_info=run_info)
    return {"degraded": True, "errors": ["unknown_tool"]}


async def handle_council_ask(session: AsyncSession, arguments: dict[str, Any], *, run_info: dict[str, Any] | None = None) -> dict[str, Any]:
    data = CouncilAskInput.model_validate(arguments)
    run_info = run_info or {}
    tool_call_id = str(run_info.get("tool_call_id") or uuid.uuid4())

    errors: list[str] = []
    degraded = False

    api_key, auth_errors = await resolve_mcp_api_key(session, api_key_input=data.api_key)
    if auth_errors:
        degraded = True
        errors.extend(auth_errors)
        conversation_id = data.conversation_id if (data.conversation_id and is_uuid_string(data.conversation_id)) else str(uuid.uuid4())
        out = CouncilAskOutput(
            final_answer="",
            conversation_id=conversation_id,
            run_id=str(uuid.uuid4()),
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
        )
        return out.model_dump()

    owner_key_id = api_key.id if api_key else None
    account_root_id = (api_key.account_id or api_key.id) if api_key else None

    result = await shared_handlers.council_ask(
        session,
        prompt=data.prompt,
        conversation_id=data.conversation_id,
        mode=data.mode,
        budget=data.budget.model_dump() if data.budget else None,
        owner_key_id=owner_key_id,
        account_root_id=account_root_id,
        has_api_key=bool(data.api_key or os.getenv("MCP_API_KEY")),
        tool_call_id=tool_call_id,
        tool_name="mcp.council.ask",
    )
    run_info["conversation_id"] = result.get("conversation_id")
    run_info["run_id"] = result.get("run_id")
    return result


async def handle_council_pipeline(session: AsyncSession, arguments: dict[str, Any], *, run_info: dict[str, Any] | None = None) -> dict[str, Any]:
    data = CouncilPipelineInput.model_validate(arguments)
    run_info = run_info or {}
    tool_call_id = str(run_info.get("tool_call_id") or uuid.uuid4())

    errors: list[str] = []
    degraded = False

    api_key, auth_errors = await resolve_mcp_api_key(session, api_key_input=data.api_key)
    if auth_errors:
        degraded = True
        errors.extend(auth_errors)
        conversation_id = data.conversation_id if (data.conversation_id and is_uuid_string(data.conversation_id)) else str(uuid.uuid4())
        out = CouncilPipelineOutput(
            run_id=str(uuid.uuid4()),
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
        )
        return out.model_dump()

    owner_key_id = api_key.id if api_key else None
    account_root_id = (api_key.account_id or api_key.id) if api_key else None
    result = await shared_handlers.council_pipeline(
        session,
        task_description=data.task_description,
        repo_context=data.repo_context.model_dump() if data.repo_context else None,
        conversation_id=data.conversation_id,
        mode=data.mode,
        max_iterations=data.max_iterations,
        budget=data.budget.model_dump() if data.budget else None,
        owner_key_id=owner_key_id,
        account_root_id=account_root_id,
        has_api_key=bool(data.api_key or os.getenv("MCP_API_KEY")),
        tool_call_id=tool_call_id,
        tool_name="mcp.council.pipeline",
    )
    run_info["conversation_id"] = result.get("conversation_id")
    run_info["run_id"] = result.get("run_id")
    return result


def list_tools() -> list[mcp_types.Tool]:
    return [
        mcp_types.Tool(
            name="council.ask",
            title="Ask the LLM Council",
            description="Run the 3-stage council process and return the final answer (strict JSON).",
            inputSchema=CouncilAskInput.model_json_schema(),
            outputSchema=CouncilAskOutput.model_json_schema(),
        ),
        mcp_types.Tool(
            name="council.pipeline",
            title="Run the Software Factory Pipeline",
            description="Run a bounded, strict-JSON agent pipeline and return a Codex prompt (strict JSON).",
            inputSchema=CouncilPipelineInput.model_json_schema(),
            outputSchema=CouncilPipelineOutput.model_json_schema(),
        ),
    ]
