import uuid

import pytest

from backend.src.engine import openrouter


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }


class _Client:
    def __init__(self):
        self.called = 0

    async def post(self, *args, **kwargs):
        self.called += 1
        return _Resp()


@pytest.mark.asyncio
async def test_query_model_uses_injected_client():
    client = _Client()
    openrouter.set_client(client)  # type: ignore[arg-type]
    try:
        openrouter._AUTH_INVALID_UNTIL = 0.0
        res = await openrouter.query_model(
            "test/model",
            [{"role": "user", "content": "hi"}],
            call_id=uuid.uuid4(),
            attempt=0,
        )
        assert res.ok is True
        assert res.content == "ok"
        assert client.called == 1
    finally:
        openrouter.set_client(None)
        openrouter._AUTH_INVALID_UNTIL = 0.0


class _Resp401:
    status_code = 401
    text = "unauthorized"

    def json(self):
        return {}


class _Client401:
    def __init__(self):
        self.called = 0

    async def post(self, *args, **kwargs):
        self.called += 1
        return _Resp401()


@pytest.mark.asyncio
async def test_openrouter_auth_cooldown_short_circuits():
    client = _Client401()
    openrouter.set_client(client)  # type: ignore[arg-type]
    try:
        openrouter._AUTH_INVALID_UNTIL = 0.0
        r1 = await openrouter.query_model(
            "test/model",
            [{"role": "user", "content": "hi"}],
            call_id=uuid.uuid4(),
            attempt=0,
        )
        assert r1.ok is False
        assert r1.status_code == 401
        assert client.called == 1

        r2 = await openrouter.query_model(
            "test/model",
            [{"role": "user", "content": "hi"}],
            call_id=uuid.uuid4(),
            attempt=0,
        )
        assert r2.ok is False
        assert r2.error_text == "OpenRouter credentials invalid (cooldown)"
        assert client.called == 1
    finally:
        openrouter.set_client(None)
        openrouter._AUTH_INVALID_UNTIL = 0.0
