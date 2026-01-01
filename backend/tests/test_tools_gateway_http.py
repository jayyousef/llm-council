import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from backend.src.app.main import app
from backend.src.db.models import ApiKey, Conversation, Run, UsageEvent
from backend.src.services import auth as auth_module
from backend.src.services.auth import hash_api_key
from backend.src.mcp.types import CouncilAskOutput, CouncilPipelineOutput


def _client():
    return TestClient(app)


def _auth_header(plaintext: str) -> dict[str, str]:
    return {"X-API-Key": plaintext}


@pytest.mark.asyncio
async def test_tools_gateway_auth_required(session, monkeypatch):
    monkeypatch.setattr(auth_module, "ALLOW_NO_AUTH", False)
    monkeypatch.setattr(auth_module, "API_KEY_PEPPER", "test-pepper")
    with _client() as c:
        r = c.post("/api/tools/council.ask", json={"prompt": "hi"})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_tools_gateway_deactivated_key_rejected(session, monkeypatch):
    monkeypatch.setattr(auth_module, "ALLOW_NO_AUTH", False)
    monkeypatch.setattr(auth_module, "API_KEY_PEPPER", "test-pepper")
    plaintext = "lc_deactivated_1234567890"
    session.add(
        ApiKey(
            key_hash=hash_api_key(plaintext),
            name="d",
            is_active=False,
            deactivated_at=datetime.utcnow(),
        )
    )
    await session.commit()
    with _client() as c:
        r = c.post("/api/tools/council.ask", headers=_auth_header(plaintext), json={"prompt": "hi"})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_tools_gateway_quota_exceeded_no_run(session, monkeypatch):
    monkeypatch.setattr(auth_module, "ALLOW_NO_AUTH", False)
    monkeypatch.setattr(auth_module, "API_KEY_PEPPER", "test-pepper")
    plaintext = "lc_quota_http_1234567890"
    api_key = ApiKey(key_hash=hash_api_key(plaintext), name="q", is_active=True, monthly_token_cap=1)
    session.add(api_key)
    await session.commit()

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

    with _client() as c:
        r = c.post("/api/tools/council.ask", headers=_auth_header(plaintext), json={"prompt": "hi"})
        assert r.status_code == 402
        assert r.json()["detail"] == "quota_exceeded"

    runs = (await session.exec(select(Run))).all()
    assert runs == []


@pytest.mark.asyncio
async def test_tools_gateway_ownership_enforced(session, monkeypatch):
    monkeypatch.setattr(auth_module, "ALLOW_NO_AUTH", False)
    monkeypatch.setattr(auth_module, "API_KEY_PEPPER", "test-pepper")

    key_a_plain = "lc_a_1234567890abcdef"
    key_b_plain = "lc_b_1234567890abcdef"
    key_a = ApiKey(key_hash=hash_api_key(key_a_plain), name="a", is_active=True)
    key_b = ApiKey(key_hash=hash_api_key(key_b_plain), name="b", is_active=True)
    session.add(key_a)
    session.add(key_b)
    await session.commit()

    convo_id = uuid.uuid4()
    session.add(Conversation(id=convo_id, title="t", owner_key_id=key_a.id))
    await session.commit()

    with _client() as c:
        r = c.post(
            "/api/tools/council.ask",
            headers=_auth_header(key_b_plain),
            json={"prompt": "hi", "conversation_id": str(convo_id), "mode": "balanced"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["degraded"] is True
        assert body["errors"] == ["conversation_not_found"]


@pytest.mark.asyncio
async def test_tools_gateway_success_shapes_match_mcp(session, monkeypatch):
    monkeypatch.setattr(auth_module, "ALLOW_NO_AUTH", False)
    monkeypatch.setattr(auth_module, "API_KEY_PEPPER", "test-pepper")
    plaintext = "lc_ok_http_1234567890"
    session.add(ApiKey(key_hash=hash_api_key(plaintext), name="ok", is_active=True))
    await session.commit()

    monkeypatch.setattr("backend.src.tools.handlers.mode_config", lambda mode: (["m1"], ["j1"], "c1"))

    from backend.src.engine.openrouter import OpenRouterResult

    async def fake_query_model(model, messages, **kwargs):
        content = "ok"
        if model == "j1":
            content = (
                '{"evaluations":[{"label":"Response A","pros":["ok"],"cons":["bad"]}],'
                '"final_ranking":["Response A"],'
                '"failure_modes_top1":["fm"],'
                '"verification_steps":["vs"]}'
            )
        return OpenRouterResult(
            ok=True,
            model=model,
            call_id=kwargs.get("call_id"),
            attempt=kwargs.get("attempt", 0),
            content=content,
            reasoning_details=None,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw_response={"usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
            latency_ms=1,
            status_code=200,
            error_text=None,
        )

    monkeypatch.setattr("backend.src.services.council_runner.query_model", fake_query_model)

    with _client() as c:
        r = c.post("/api/tools/council.ask", headers=_auth_header(plaintext), json={"prompt": "hi", "mode": "balanced"})
        assert r.status_code == 200
        CouncilAskOutput.model_validate(r.json())

        r2 = c.post(
            "/api/tools/council.pipeline",
            headers=_auth_header(plaintext),
            json={"task_description": "do", "mode": "balanced", "max_iterations": 1},
        )
        assert r2.status_code == 200
        CouncilPipelineOutput.model_validate(r2.json())


@pytest.mark.asyncio
async def test_tools_gateway_does_not_accept_api_key_in_body(session, monkeypatch):
    monkeypatch.setattr(auth_module, "ALLOW_NO_AUTH", False)
    monkeypatch.setattr(auth_module, "API_KEY_PEPPER", "test-pepper")
    plaintext = "lc_body_key_1234567890"
    session.add(ApiKey(key_hash=hash_api_key(plaintext), name="ok", is_active=True))
    await session.commit()
    with _client() as c:
        r = c.post(
            "/api/tools/council.ask",
            headers=_auth_header(plaintext),
            json={"prompt": "hi", "api_key": "should_not_be_allowed"},
        )
        assert r.status_code == 422

