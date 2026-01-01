from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from pydantic import ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession

from .. import config
from ..services.runs import RunService
from . import tools
from .types import (
    CouncilAskOutput,
    CouncilPipelineAgentOutputs,
    CouncilPipelineOutput,
    UsageSummary,
)


logger = logging.getLogger(__name__)

_MCP_SEMAPHORE: asyncio.Semaphore | None = None
_MCP_SEMAPHORE_LIMIT: int | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _MCP_SEMAPHORE, _MCP_SEMAPHORE_LIMIT
    limit = max(1, int(config.MCP_MAX_CONCURRENT_CALLS))
    if _MCP_SEMAPHORE is None or _MCP_SEMAPHORE_LIMIT != limit:
        _MCP_SEMAPHORE = asyncio.Semaphore(limit)
        _MCP_SEMAPHORE_LIMIT = limit
    return _MCP_SEMAPHORE


def _empty_usage_summary() -> UsageSummary:
    return UsageSummary(
        total_prompt_tokens=None,
        total_completion_tokens=None,
        total_tokens=None,
        total_cost_estimated=None,
        by_model=[],
    )


def _error_output(tool_name: str, *, conversation_id: str, run_id: str, errors: list[str]) -> dict[str, Any]:
    if tool_name == "council.ask":
        out = CouncilAskOutput(
            final_answer="",
            conversation_id=conversation_id,
            run_id=run_id,
            metadata={"label_to_model": {}, "aggregate_rankings": []},
            usage_summary=_empty_usage_summary(),
            degraded=True,
            errors=errors,
        )
        return out.model_dump()
    if tool_name == "council.pipeline":
        out = CouncilPipelineOutput(
            run_id=run_id,
            conversation_id=conversation_id,
            scope_contract=None,
            agent_outputs=CouncilPipelineAgentOutputs(),
            final_codex_prompt=None,
            gate_verdict="FAIL",
            degraded=True,
            errors=errors,
            usage_summary=_empty_usage_summary(),
        )
        return out.model_dump()
    return {"degraded": True, "errors": errors}


async def _mark_run_failed(session: AsyncSession, run_id: uuid.UUID, *, latency_ms: int | None) -> None:
    run_service = RunService(session)
    await run_service.end_run(run_id, status="failed", latency_ms=latency_ms)


async def call_tool_with_guards(session: AsyncSession, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tool_call_id = str(uuid.uuid4())
    run_info: dict[str, Any] = {"tool_call_id": tool_call_id}

    timeout = float(config.MCP_TOOL_TIMEOUT_SECONDS)
    started = time.monotonic()

    logger.info("mcp_tool_start name=%s tool_call_id=%s", name, tool_call_id)

    async with _get_semaphore():
        try:
            result = await asyncio.wait_for(
                tools.dispatch_tool(session, name, arguments, run_info=run_info),
                timeout=timeout,
            )
            logger.info("mcp_tool_done name=%s tool_call_id=%s", name, tool_call_id)
            return result

        except asyncio.TimeoutError:
            await session.rollback()
            rid = run_info.get("run_id")
            if rid:
                await _mark_run_failed(
                    session,
                    uuid.UUID(str(rid)),
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                await session.commit()
            logger.warning("mcp_tool_timeout name=%s tool_call_id=%s", name, tool_call_id)
            return _error_output(
                name,
                conversation_id=str(run_info.get("conversation_id") or uuid.uuid4()),
                run_id=str(rid or uuid.uuid4()),
                errors=["timeout"],
            )

        except asyncio.CancelledError:
            await session.rollback()
            rid = run_info.get("run_id")
            if rid:
                await _mark_run_failed(
                    session,
                    uuid.UUID(str(rid)),
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                await session.commit()
            logger.warning("mcp_tool_cancelled name=%s tool_call_id=%s", name, tool_call_id)
            return _error_output(
                name,
                conversation_id=str(run_info.get("conversation_id") or uuid.uuid4()),
                run_id=str(rid or uuid.uuid4()),
                errors=["cancelled"],
            )

        except ValidationError as e:
            await session.rollback()
            errs = ["invalid_input"]
            if any("input_too_large" in str(item.get("msg", "")) for item in e.errors()):
                errs = ["input_too_large"]
            logger.info("mcp_tool_validation_error name=%s tool_call_id=%s", name, tool_call_id)
            return _error_output(
                name,
                conversation_id=str(run_info.get("conversation_id") or uuid.uuid4()),
                run_id=str(run_info.get("run_id") or uuid.uuid4()),
                errors=errs,
            )

        except Exception:
            await session.rollback()
            rid = run_info.get("run_id")
            if rid:
                await _mark_run_failed(
                    session,
                    uuid.UUID(str(rid)),
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                await session.commit()
            logger.exception("mcp_tool_internal_error name=%s tool_call_id=%s", name, tool_call_id)
            return _error_output(
                name,
                conversation_id=str(run_info.get("conversation_id") or uuid.uuid4()),
                run_id=str(rid or uuid.uuid4()),
                errors=["internal_error"],
            )
