import uuid

import pytest
from sqlmodel import select

from backend.src.db.models import Conversation, Message, UsageEvent
from backend.src.db.models import Run
from backend.src.engine.openrouter import OpenRouterResult
from backend.src.mcp.tools import handle_council_ask


@pytest.mark.asyncio
async def test_mcp_creates_conversation_and_run(session, monkeypatch):
    # Make auth permissive for test.
    monkeypatch.setenv("ALLOW_NO_AUTH", "true")

    # Ensure mode routing doesn't rely on env.
    monkeypatch.setattr("backend.src.tools.handlers.mode_config", lambda mode: (["m1"], ["j1"], "c1"))

    calls = {"n": 0}

    async def fake_query_model(model, messages, **kwargs):
        calls["n"] += 1
        return OpenRouterResult(
            ok=True,
            model=model,
            call_id=kwargs.get("call_id"),
            attempt=kwargs.get("attempt", 0),
            content=(
                '{"evaluations":[{"label":"Response A","pros":["ok"],"cons":["bad"]}],'
                '"final_ranking":["Response A"],'
                '"failure_modes_top1":["fm"],'
                '"verification_steps":["vs"]}'
                if model == "j1"
                else "ok"
            ),
            reasoning_details=None,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw_response={"usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
            latency_ms=1,
            status_code=200,
            error_text=None,
        )

    monkeypatch.setattr("backend.src.services.council_runner.query_model", fake_query_model)

    out = await handle_council_ask(
        session,
        {"prompt": "hi", "mode": "balanced"},
    )
    assert out["conversation_id"]
    assert out["run_id"]
    assert out["final_answer"]
    assert out["errors"] == []
    assert out["degraded"] is False
    assert "usage_summary" in out

    convo = (await session.exec(select(Conversation))).first()
    assert convo is not None

    run = (await session.exec(select(Run))).first()
    assert run is not None
    assert "price_book_version" in (run.input_json or {})


@pytest.mark.asyncio
async def test_mcp_rejects_wrong_conversation_owner(session, monkeypatch):
    monkeypatch.setenv("ALLOW_NO_AUTH", "true")

    convo_id = uuid.uuid4()
    session.add(Conversation(id=convo_id, title="t", owner_key_id=uuid.uuid4()))
    await session.commit()

    out = await handle_council_ask(session, {"prompt": "hi", "conversation_id": str(convo_id)})
    assert out["errors"] == ["conversation_not_found"]
    assert out["degraded"] is True


@pytest.mark.asyncio
async def test_mcp_usage_summary_matches_events(session, monkeypatch):
    monkeypatch.setenv("ALLOW_NO_AUTH", "true")
    monkeypatch.setattr("backend.src.tools.handlers.mode_config", lambda mode: (["m1"], [], "c1"))

    async def fake_query_model(model, messages, **kwargs):
        return OpenRouterResult(
            ok=True,
            model=model,
            call_id=kwargs.get("call_id"),
            attempt=kwargs.get("attempt", 0),
            content="ok",
            reasoning_details=None,
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            raw_response={"usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}},
            latency_ms=1,
            status_code=200,
            error_text=None,
        )

    monkeypatch.setattr("backend.src.services.council_runner.query_model", fake_query_model)

    convo_id = uuid.uuid4()
    session.add(Conversation(id=convo_id, title="t"))
    session.add(Message(conversation_id=convo_id, role="user", content="existing"))
    await session.commit()

    out = await handle_council_ask(session, {"prompt": "hi", "conversation_id": str(convo_id)})
    run_id = uuid.UUID(out["run_id"])

    events = (await session.exec(select(UsageEvent).where(UsageEvent.run_id == run_id))).all()
    assert len(events) >= 1
    # stage1 (m1) + stage3 (c1); title is skipped because conversation already has messages.
    assert out["usage_summary"]["total_tokens"] == 60
