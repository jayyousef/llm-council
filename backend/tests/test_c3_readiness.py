import uuid
from datetime import datetime

import pytest
from sqlmodel import select

from backend.src import config
from backend.src.db.models import ApiKey, Run, UsageEvent
from backend.src.mcp.runtime import call_tool_with_guards
from backend.src.services import auth as auth_module
from backend.src.services.auth import get_api_key
from backend.src.services.usage import UsageService
from backend.src.utils.redact import redact_secrets


@pytest.mark.asyncio
async def test_api_key_deactivation_rejects(session, monkeypatch):
    monkeypatch.setattr(auth_module, "ALLOW_NO_AUTH", False)
    monkeypatch.setattr(auth_module, "API_KEY_PEPPER", "test-pepper")

    plaintext = "lc_test_key_1234567890"
    key = ApiKey(
        key_hash=auth_module.hash_api_key(plaintext),
        name="k",
        is_active=False,
        deactivated_at=datetime.utcnow(),
    )
    session.add(key)
    await session.commit()

    with pytest.raises(Exception) as e:
        await get_api_key(x_api_key=plaintext, session=session)  # type: ignore[arg-type]
    assert "Invalid API key" in str(e.value) or "401" in str(e.value)


@pytest.mark.asyncio
async def test_mcp_quota_exceeded_rejects_without_creating_run(session, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_NO_AUTH", False)
    monkeypatch.setattr(auth_module, "ALLOW_NO_AUTH", False)
    monkeypatch.setattr(auth_module, "API_KEY_PEPPER", "test-pepper")

    plaintext = "lc_quota_key_1234567890"
    api_key = ApiKey(
        key_hash=auth_module.hash_api_key(plaintext),
        name="quota",
        is_active=True,
        monthly_token_cap=1,
    )
    session.add(api_key)
    await session.commit()

    # Used tokens this month already at cap.
    session.add(
        UsageEvent(
            owner_key_id=api_key.id,
            run_id=uuid.uuid4(),
            model="m",
            total_tokens=1,
            created_at=datetime.utcnow(),
        )
    )
    await session.commit()

    out = await call_tool_with_guards(
        session,
        "council.ask",
        {"prompt": "hi", "mode": "balanced", "api_key": plaintext},
    )
    assert out["degraded"] is True
    assert out["errors"] == ["quota_exceeded"]

    out2 = await call_tool_with_guards(
        session,
        "council.pipeline",
        {"task_description": "do", "mode": "balanced", "api_key": plaintext},
    )
    assert out2["degraded"] is True
    assert out2["errors"] == ["quota_exceeded"]

    runs = (await session.exec(select(Run))).all()
    assert runs == []


def test_redact_secrets_patterns():
    text = "Bearer abcdefghijklmnop sk-or-v1-abcdef123456 lc_abcdef1234567890 -----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"
    redacted = redact_secrets(text)
    assert "Bearer [REDACTED]" in redacted
    assert "sk-or-v1-" not in redacted
    assert "lc_" not in redacted
    assert "-----BEGIN [REDACTED]-----" in redacted
    assert "-----END [REDACTED]-----" in redacted
    assert "\nabc\n" not in redacted


@pytest.mark.asyncio
async def test_price_book_version_stored_in_usage_raw_json(session, monkeypatch):
    monkeypatch.setattr(config, "PRICE_BOOK_VERSION", "v_test")
    service = UsageService(session)
    run_id = uuid.uuid4()
    await service.record_usage_event(
        owner_key_id=None,
        run_id=run_id,
        model="m",
        usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        call_id=uuid.uuid4(),
        attempt=0,
        latency_ms=1,
        error_text=None,
    )
    await session.commit()

    row = (await session.exec(select(UsageEvent).where(UsageEvent.run_id == run_id))).first()
    assert row is not None
    assert isinstance(row.raw_usage_json, dict)
    assert row.raw_usage_json.get("price_book_version") == "v_test"


@pytest.mark.asyncio
async def test_mode_timeout_selection_passed_to_council_runner(session, monkeypatch):
    from backend.src.db.models import Conversation
    from backend.src.services.cache import CacheService
    from backend.src.services.council_runner import CouncilRunner
    from backend.src.services.runs import RunService

    convo_id = uuid.uuid4()
    session.add(Conversation(id=convo_id, title="t"))
    await session.commit()

    observed = {"timeout": None}

    async def fake_query_model(model, messages, **kwargs):
        observed["timeout"] = kwargs.get("timeout_seconds")
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

    run_service = RunService(session)
    run_id = await run_service.create_run(convo_id, "test", {"mode": "fast"}, None)

    runner = CouncilRunner(
        run_service,
        UsageService(session),
        CacheService(session),
        council_models=["m1"],
        judge_models=[],
        chairman_model="m1",
        session=session,
        timeout_seconds=12.3,
    )
    await runner.stage1(run_id, None, "hi")
    assert observed["timeout"] == 12.3
