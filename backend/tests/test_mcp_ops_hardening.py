import asyncio
import uuid

import pytest
from sqlmodel import select

from backend.src import config
from backend.src.db.models import ApiKey, Conversation, Message, Run
from backend.src.mcp.runtime import call_tool_with_guards
from backend.src.services.auth import hash_api_key


@pytest.mark.asyncio
async def test_mcp_global_semaphore_limits_concurrency(session, monkeypatch):
    monkeypatch.setattr(config, "MCP_MAX_CONCURRENT_CALLS", 1)
    monkeypatch.setattr(config, "MCP_TOOL_TIMEOUT_SECONDS", 5.0)

    started = asyncio.Event()
    release = asyncio.Event()
    state = {"calls": 0, "second_started": False}

    async def fake_dispatch_tool(session, name, arguments, *, run_info):
        state["calls"] += 1
        if state["calls"] == 1:
            started.set()
            await release.wait()
            return {"ok": True}
        state["second_started"] = True
        return {"ok": True}

    monkeypatch.setattr("backend.src.mcp.tools.dispatch_tool", fake_dispatch_tool)

    t1 = asyncio.create_task(call_tool_with_guards(session, "council.ask", {}))
    await started.wait()
    t2 = asyncio.create_task(call_tool_with_guards(session, "council.ask", {}))

    await asyncio.sleep(0)
    assert state["second_started"] is False
    release.set()
    await t1
    await t2
    assert state["second_started"] is True


@pytest.mark.asyncio
async def test_mcp_cancelled_rolls_back_and_marks_run_failed(session, monkeypatch):
    monkeypatch.setattr(config, "MCP_MAX_CONCURRENT_CALLS", 4)
    monkeypatch.setattr(config, "MCP_TOOL_TIMEOUT_SECONDS", 5.0)

    async def fake_dispatch_tool(session, name, arguments, *, run_info):
        convo_id = uuid.uuid4()
        session.add(Conversation(id=convo_id, title="t"))
        await session.flush()

        run = Run(conversation_id=convo_id, tool_name="mcp.test", input_json={"tool_call_id": run_info["tool_call_id"]})
        session.add(run)
        await session.flush()
        run_info["conversation_id"] = str(convo_id)
        run_info["run_id"] = str(run.id)
        await session.commit()

        session.add(Message(conversation_id=convo_id, role="user", content="should_rollback"))
        await session.flush()
        raise asyncio.CancelledError()

    monkeypatch.setattr("backend.src.mcp.tools.dispatch_tool", fake_dispatch_tool)

    out = await call_tool_with_guards(session, "council.pipeline", {})
    assert out["degraded"] is True
    assert out["errors"] == ["cancelled"]

    run_id = uuid.UUID(out["run_id"])
    run = await session.get(Run, run_id)
    assert run is not None
    assert run.status == "failed"
    assert run.ended_at is not None

    msgs = (await session.exec(select(Message).where(Message.conversation_id == run.conversation_id))).all()
    assert msgs == []


@pytest.mark.asyncio
async def test_mcp_timeout_marks_run_failed(session, monkeypatch):
    monkeypatch.setattr(config, "MCP_MAX_CONCURRENT_CALLS", 4)
    monkeypatch.setattr(config, "MCP_TOOL_TIMEOUT_SECONDS", 0.01)

    async def fake_dispatch_tool(session, name, arguments, *, run_info):
        convo_id = uuid.uuid4()
        session.add(Conversation(id=convo_id, title="t"))
        await session.flush()
        run = Run(conversation_id=convo_id, tool_name="mcp.test", input_json={"tool_call_id": run_info["tool_call_id"]})
        session.add(run)
        await session.flush()
        run_info["conversation_id"] = str(convo_id)
        run_info["run_id"] = str(run.id)
        await session.commit()
        await asyncio.sleep(1)
        return {"ok": True}

    monkeypatch.setattr("backend.src.mcp.tools.dispatch_tool", fake_dispatch_tool)

    out = await call_tool_with_guards(session, "council.ask", {})
    assert out["degraded"] is True
    assert out["errors"] == ["timeout"]
    run_id = uuid.UUID(out["run_id"])
    run = await session.get(Run, run_id)
    assert run is not None
    assert run.status == "failed"
    assert run.ended_at is not None


@pytest.mark.asyncio
async def test_mcp_size_limits_return_input_too_large(session, monkeypatch):
    monkeypatch.setenv("ALLOW_NO_AUTH", "true")
    monkeypatch.setattr(config, "MCP_MAX_PROMPT_CHARS", 5)

    out = await call_tool_with_guards(session, "council.ask", {"prompt": "123456", "mode": "balanced"})
    assert out["degraded"] is True
    assert out["errors"] == ["input_too_large"]


@pytest.mark.asyncio
async def test_mcp_council_ask_budget_exceeded_aborts_remaining_calls(session, monkeypatch):
    monkeypatch.setenv("ALLOW_NO_AUTH", "true")
    monkeypatch.setattr(config, "MCP_MAX_PROMPT_CHARS", 20000)

    # Avoid title generation affecting budget/call counts.
    convo_id = uuid.uuid4()
    session.add(Conversation(id=convo_id, title="t"))
    session.add(Message(conversation_id=convo_id, role="user", content="existing"))
    await session.commit()

    monkeypatch.setattr("backend.src.tools.handlers.mode_config", lambda mode: (["m1", "m2"], [], "c1"))

    calls = {"models": []}

    async def fake_query_model(model, messages, **kwargs):
        calls["models"].append(model)
        from backend.src.engine.openrouter import OpenRouterResult

        return OpenRouterResult(
            ok=True,
            model=model,
            call_id=kwargs.get("call_id"),
            attempt=kwargs.get("attempt", 0),
            content="ok",
            reasoning_details=None,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw_response={"usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
            latency_ms=1,
            status_code=200,
            error_text=None,
        )

    monkeypatch.setattr("backend.src.services.council_runner.query_model", fake_query_model)

    out = await call_tool_with_guards(
        session,
        "council.ask",
        {"prompt": "hi", "conversation_id": str(convo_id), "budget": {"max_total_tokens": 1}},
    )
    assert out["degraded"] is True
    assert "budget_exceeded" in out["errors"]
    assert calls["models"] == ["m1"]


@pytest.mark.asyncio
async def test_mcp_ownership_rejects_other_api_key(session, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_NO_AUTH", False)

    key1_plain = "k1"
    key2_plain = "k2"
    key1 = ApiKey(key_hash=hash_api_key(key1_plain), name="k1", is_active=True)
    key2 = ApiKey(key_hash=hash_api_key(key2_plain), name="k2", is_active=True)
    session.add(key1)
    session.add(key2)
    await session.commit()

    convo_id = uuid.uuid4()
    session.add(Conversation(id=convo_id, title="t", owner_key_id=key1.id))
    await session.commit()

    out = await call_tool_with_guards(
        session,
        "council.ask",
        {"prompt": "hi", "conversation_id": str(convo_id), "api_key": key2_plain},
    )
    assert out["degraded"] is True
    assert out["errors"] == ["conversation_not_found"]

    out2 = await call_tool_with_guards(
        session,
        "council.pipeline",
        {"task_description": "hi", "conversation_id": str(convo_id), "api_key": key2_plain},
    )
    assert out2["degraded"] is True
    assert out2["errors"] == ["conversation_not_found"]
