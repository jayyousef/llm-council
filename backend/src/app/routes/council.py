import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from ..schemas.conversations import SendMessageRequest
from ... import config
from ...db.session import get_session
from ...services.conversation_store import ConversationStore
from ...services.store_factory import get_default_store
from ...services.auth import get_api_key_for_run
from ...db.models import ApiKey
from ...services.cache import CacheService
from ...services.council_runner import CouncilRunner
from ...services.runs import RunService
from ...services.usage import UsageService


router = APIRouter()


@router.post("/api/conversations/{conversation_id}/message")
async def send_message(
    conversation_id: str,
    request: SendMessageRequest,
    api_key: ApiKey | None = Depends(get_api_key_for_run),
    session: AsyncSession = Depends(get_session),
    store: ConversationStore = Depends(get_default_store),
):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    conversation = await store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    runner = CouncilRunner(
        RunService(session),
        UsageService(session),
        CacheService(session),
        session=session,
        timeout_seconds=config.openrouter_timeout_for_mode("balanced"),
    )
    owner_key_id = api_key.id if api_key else None

    import time
    import uuid

    started = time.monotonic()
    run_id = await runner.start_run(
        uuid.UUID(conversation_id),
        owner_key_id,
        tool_name="council.ask",
        input_json={"content": request.content, "mode": "balanced", "price_book_version": config.PRICE_BOOK_VERSION},
    )

    try:
        await store.add_user_message(conversation_id, request.content)

        if is_first_message:
            title = await runner.generate_title(run_id, owner_key_id, request.content)
            await store.update_conversation_title(conversation_id, title)

        stage1_results = await runner.stage1(run_id, owner_key_id, request.content)
        if not stage1_results:
            stage2_results = []
            stage3_result = {"model": "error", "response": "All models failed to respond. Please try again."}
            metadata = {}
            await runner.finish_run(run_id, status="failed", latency_ms=int((time.monotonic() - started) * 1000))
        else:
            stage2_results, label_to_model, aggregate_rankings = await runner.stage2(
                run_id, owner_key_id, request.content, stage1_results
            )
            stage3_result = await runner.stage3(run_id, owner_key_id, request.content, stage1_results, stage2_results)
            metadata = {"label_to_model": label_to_model, "aggregate_rankings": aggregate_rankings}

            status = "succeeded"
            if stage3_result.get("model") != config.CHAIRMAN_MODEL or str(stage3_result.get("response", "")).startswith("Error:"):
                status = "failed"
            await runner.finish_run(run_id, status=status, latency_ms=int((time.monotonic() - started) * 1000))

        await store.add_assistant_message(conversation_id, stage1_results, stage2_results, stage3_result)
        return {"stage1": stage1_results, "stage2": stage2_results, "stage3": stage3_result, "metadata": metadata}

    except Exception:
        await runner.finish_run(run_id, status="failed", latency_ms=int((time.monotonic() - started) * 1000))
        raise


@router.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(
    conversation_id: str,
    request: SendMessageRequest,
    api_key: ApiKey | None = Depends(get_api_key_for_run),
    session: AsyncSession = Depends(get_session),
    store: ConversationStore = Depends(get_default_store),
):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = await store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    runner = CouncilRunner(
        RunService(session),
        UsageService(session),
        CacheService(session),
        session=session,
        timeout_seconds=config.openrouter_timeout_for_mode("balanced"),
    )
    owner_key_id = api_key.id if api_key else None

    import time
    import uuid

    started = time.monotonic()
    run_id = await runner.start_run(
        uuid.UUID(conversation_id),
        owner_key_id,
        tool_name="council.ask",
        input_json={"content": request.content, "mode": "balanced", "price_book_version": config.PRICE_BOOK_VERSION},
    )

    async def event_generator():
        try:
            # Add user message
            await store.add_user_message(conversation_id, request.content)

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(
                    runner.generate_title(run_id, owner_key_id, request.content)
                )

            # Stage 1: Collect responses
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await runner.stage1(run_id, owner_key_id, request.content)
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            # Stage 2: Collect rankings
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_results, label_to_model, aggregate_rankings = await runner.stage2(
                run_id, owner_key_id, request.content, stage1_results
            )
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}})}\n\n"

            # Stage 3: Synthesize final answer
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_result = await runner.stage3(run_id, owner_key_id, request.content, stage1_results, stage2_results)
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                await store.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Save complete assistant message
            await store.add_assistant_message(conversation_id, stage1_results, stage2_results, stage3_result)

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

            status = "succeeded"
            if stage3_result.get("model") != config.CHAIRMAN_MODEL or str(stage3_result.get("response", "")).startswith("Error:"):
                status = "failed"
            await runner.finish_run(run_id, status=status, latency_ms=int((time.monotonic() - started) * 1000))

        except Exception as e:
            await runner.finish_run(run_id, status="failed", latency_ms=int((time.monotonic() - started) * 1000))
            # Send error event
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
