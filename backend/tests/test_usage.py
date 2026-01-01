import uuid

import pytest

from backend.src.db.models import Conversation
from backend.src.services.runs import RunService
from backend.src.services.usage import UsageService


@pytest.mark.asyncio
async def test_usage_event_cost_estimation(session, monkeypatch):
    import backend.src.config as config

    monkeypatch.setattr(
        config,
        "MODEL_PRICING",
        {"test/model": {"prompt_per_1m": 1.0, "completion_per_1m": 2.0}},
        raising=False,
    )

    convo_id = uuid.uuid4()
    session.add(Conversation(id=convo_id, title="t"))
    await session.commit()

    run_id = await RunService(session).create_run(convo_id, "council.ask", {"content": "q"}, owner_key_id=None)

    usage = UsageService(session)
    event_id = await usage.record_usage_event(
        owner_key_id=None,
        run_id=run_id,
        model="test/model",
        usage={"prompt_tokens": 1000, "completion_tokens": 2000, "total_tokens": 3000},
        call_id=uuid.uuid4(),
        attempt=0,
        latency_ms=123,
    )
    assert event_id
