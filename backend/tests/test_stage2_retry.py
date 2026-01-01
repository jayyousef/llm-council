import uuid

import pytest

from sqlmodel import select

from backend.src.db.models import Conversation, UsageEvent
from backend.src.services.cache import CacheService
from backend.src.services.council_runner import CouncilRunner
from backend.src.services.runs import RunService
from backend.src.services.usage import UsageService


@pytest.mark.asyncio
async def test_stage2_json_validation_retries_once(session, monkeypatch):
    # Reduce council to a single model for deterministic test.
    import backend.src.services.council_runner as runner_mod

    monkeypatch.setattr(runner_mod, "COUNCIL_MODELS", ["test/judge"], raising=False)
    monkeypatch.setattr(runner_mod, "CHAIRMAN_MODEL", "test/chair", raising=False)

    calls = {"n": 0}

    from backend.src.engine.openrouter import OpenRouterResult

    async def fake_query_model(model, messages, **kwargs):
        calls["n"] += 1
        call_id = kwargs.get("call_id")
        attempt = kwargs.get("attempt", 0)
        if calls["n"] == 1:
            # Invalid: missing required fields and not parseable to schema.
            content = '{"final_ranking":["Response A"]}'
        else:
            content = (
                '{"evaluations":[{"label":"Response A","pros":["ok"],"cons":["bad"]}],'
                '"final_ranking":["Response A"],'
                '"failure_modes_top1":["fm"],'
                '"verification_steps":["vs"]}'
            )
        return OpenRouterResult(
            ok=True,
            model=model,
            call_id=call_id,
            attempt=attempt,
            content=content,
            reasoning_details=None,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw_response={"usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
            latency_ms=1,
            status_code=200,
            error_text=None,
        )

    monkeypatch.setattr(runner_mod, "query_model", fake_query_model, raising=True)

    convo_id = uuid.uuid4()
    session.add(Conversation(id=convo_id, title="t"))
    await session.commit()

    runner = CouncilRunner(RunService(session), UsageService(session), CacheService(session))
    run_id = await runner.start_run(convo_id, owner_key_id=None, tool_name="council.ask", input_json={"content": "q"})

    stage1_results = [{"model": "m1", "response": "answer"}]
    stage2_results, label_to_model, aggregate = await runner.stage2(run_id, None, "q", stage1_results)

    assert calls["n"] == 2
    assert len(stage2_results) == 1
    assert stage2_results[0]["parsed_ranking"] == ["Response A"]
    assert stage2_results[0]["valid"] is True
    assert "Response A" in label_to_model
    assert isinstance(aggregate, list)

    events = (await session.exec(select(UsageEvent).order_by(UsageEvent.created_at.asc()))).all()
    assert len(events) == 2
    assert events[0].call_id == events[1].call_id
    assert [events[0].attempt, events[1].attempt] == [0, 1]


@pytest.mark.asyncio
async def test_stage2_invalid_after_retry_is_excluded(session, monkeypatch):
    import backend.src.services.council_runner as runner_mod

    monkeypatch.setattr(runner_mod, "COUNCIL_MODELS", ["test/judge"], raising=False)

    calls = {"n": 0}
    from backend.src.engine.openrouter import OpenRouterResult

    async def fake_query_model(model, messages, **kwargs):
        calls["n"] += 1
        call_id = kwargs.get("call_id")
        attempt = kwargs.get("attempt", 0)
        # Always invalid, but includes a "Response A" string that regex fallback would have parsed.
        content = "FINAL RANKING:\\n1. Response A"
        return OpenRouterResult(
            ok=True,
            model=model,
            call_id=call_id,
            attempt=attempt,
            content=content,
            reasoning_details=None,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw_response={"usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
            latency_ms=1,
            status_code=200,
            error_text=None,
        )

    monkeypatch.setattr(runner_mod, "query_model", fake_query_model, raising=True)

    convo_id = uuid.uuid4()
    session.add(Conversation(id=convo_id, title="t"))
    await session.commit()

    runner = CouncilRunner(RunService(session), UsageService(session), CacheService(session))
    run_id = await runner.start_run(convo_id, owner_key_id=None, tool_name="council.ask", input_json={"content": "q"})

    stage1_results = [{"model": "m1", "response": "answer"}]
    stage2_results, label_to_model, aggregate = await runner.stage2(run_id, None, "q", stage1_results)

    assert calls["n"] == 2
    assert len(stage2_results) == 1
    assert stage2_results[0]["parsed_ranking"] == []
    assert stage2_results[0]["parsed_json"] is None
    assert stage2_results[0]["valid"] is False
    assert stage2_results[0]["validation_error"]
    assert aggregate == []
