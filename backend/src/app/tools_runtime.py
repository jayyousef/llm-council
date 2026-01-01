from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from sqlmodel.ext.asyncio.session import AsyncSession

from .. import config
from ..services.runs import RunService

logger = logging.getLogger(__name__)

_HTTP_TOOLS_SEMAPHORE: asyncio.Semaphore | None = None
_HTTP_TOOLS_LIMIT: int | None = None


def _get_http_semaphore() -> asyncio.Semaphore:
    global _HTTP_TOOLS_SEMAPHORE, _HTTP_TOOLS_LIMIT
    limit = max(1, int(config.HTTP_MAX_CONCURRENT_TOOL_CALLS))
    if _HTTP_TOOLS_SEMAPHORE is None or _HTTP_TOOLS_LIMIT != limit:
        _HTTP_TOOLS_SEMAPHORE = asyncio.Semaphore(limit)
        _HTTP_TOOLS_LIMIT = limit
    return _HTTP_TOOLS_SEMAPHORE


async def _mark_run_failed(session: AsyncSession, run_id: uuid.UUID, *, latency_ms: int | None) -> None:
    await RunService(session).end_run(run_id, status="failed", latency_ms=latency_ms)


async def call_http_tool_with_guards(
    session: AsyncSession,
    *,
    tool_name: str,
    run_info: dict[str, Any],
    handler: Callable[[], Awaitable[dict[str, Any]]],
    error_output: Callable[[list[str], dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    timeout = float(config.HTTP_TOOL_TIMEOUT_SECONDS)
    started = time.monotonic()

    async with _get_http_semaphore():
        try:
            return await asyncio.wait_for(handler(), timeout=timeout)

        except asyncio.TimeoutError:
            await session.rollback()
            rid = run_info.get("run_id")
            if rid:
                await _mark_run_failed(session, uuid.UUID(str(rid)), latency_ms=int((time.monotonic() - started) * 1000))
                await session.commit()
            logger.warning("http_tool_timeout tool=%s tool_call_id=%s", tool_name, run_info.get("tool_call_id"))
            return error_output(["timeout"], run_info)

        except asyncio.CancelledError:
            await session.rollback()
            rid = run_info.get("run_id")
            if rid:
                await _mark_run_failed(session, uuid.UUID(str(rid)), latency_ms=int((time.monotonic() - started) * 1000))
                await session.commit()
            logger.warning("http_tool_cancelled tool=%s tool_call_id=%s", tool_name, run_info.get("tool_call_id"))
            return error_output(["cancelled"], run_info)

        except Exception:
            await session.rollback()
            rid = run_info.get("run_id")
            if rid:
                await _mark_run_failed(session, uuid.UUID(str(rid)), latency_ms=int((time.monotonic() - started) * 1000))
                await session.commit()
            logger.exception("http_tool_error tool=%s tool_call_id=%s", tool_name, run_info.get("tool_call_id"))
            return error_output(["error"], run_info)

