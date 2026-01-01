from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from ...db.models import ApiKey
from ...db.session import get_session
from ...services.auth import get_api_key_for_run
from ...tools import handlers
from ...mcp.types import (
    CouncilAskHttpInput,
    CouncilAskOutput,
    CouncilPipelineHttpInput,
    CouncilPipelineOutput,
)
from ..tools_runtime import call_http_tool_with_guards


router = APIRouter()


def _ask_error_output(errors: list[str], run_info: dict) -> dict:
    return handlers._empty_ask_output(  # type: ignore[attr-defined]
        conversation_id=str(run_info.get("conversation_id") or uuid.uuid4()),
        run_id=str(run_info.get("run_id") or uuid.uuid4()),
        errors=errors,
    )


def _pipeline_error_output(errors: list[str], run_info: dict) -> dict:
    return handlers._empty_pipeline_output(  # type: ignore[attr-defined]
        conversation_id=str(run_info.get("conversation_id") or uuid.uuid4()),
        run_id=str(run_info.get("run_id") or uuid.uuid4()),
        errors=errors,
    )


@router.post("/api/tools/council.ask", response_model=CouncilAskOutput)
async def tool_council_ask(
    request: CouncilAskHttpInput,
    api_key: ApiKey | None = Depends(get_api_key_for_run),
    session: AsyncSession = Depends(get_session),
):
    run_info = {"tool_call_id": str(uuid.uuid4())}
    owner_key_id = api_key.id if api_key else None
    account_root_id = (api_key.account_id or api_key.id) if api_key else None

    async def _handler():
        result = await handlers.council_ask(
            session,
            prompt=request.prompt,
            conversation_id=request.conversation_id,
            mode=request.mode,
            budget=request.budget.model_dump() if request.budget else None,
            owner_key_id=owner_key_id,
            account_root_id=account_root_id,
            has_api_key=bool(api_key),
            tool_call_id=run_info["tool_call_id"],
            tool_name="http.tools.council.ask",
        )
        run_info["conversation_id"] = result.get("conversation_id")
        run_info["run_id"] = result.get("run_id")
        return result

    return await call_http_tool_with_guards(
        session,
        tool_name="council.ask",
        run_info=run_info,
        handler=_handler,
        error_output=_ask_error_output,
    )


@router.post("/api/tools/council.pipeline", response_model=CouncilPipelineOutput)
async def tool_council_pipeline(
    request: CouncilPipelineHttpInput,
    api_key: ApiKey | None = Depends(get_api_key_for_run),
    session: AsyncSession = Depends(get_session),
):
    run_info = {"tool_call_id": str(uuid.uuid4())}
    owner_key_id = api_key.id if api_key else None
    account_root_id = (api_key.account_id or api_key.id) if api_key else None

    async def _handler():
        result = await handlers.council_pipeline(
            session,
            task_description=request.task_description,
            repo_context=request.repo_context.model_dump() if request.repo_context else None,
            conversation_id=request.conversation_id,
            mode=request.mode,
            max_iterations=request.max_iterations,
            budget=request.budget.model_dump() if request.budget else None,
            owner_key_id=owner_key_id,
            account_root_id=account_root_id,
            has_api_key=bool(api_key),
            tool_call_id=run_info["tool_call_id"],
            tool_name="http.tools.council.pipeline",
        )
        run_info["conversation_id"] = result.get("conversation_id")
        run_info["run_id"] = result.get("run_id")
        return result

    return await call_http_tool_with_guards(
        session,
        tool_name="council.pipeline",
        run_info=run_info,
        handler=_handler,
        error_output=_pipeline_error_output,
    )
