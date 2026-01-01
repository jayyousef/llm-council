import uuid

import pytest

from backend.src.services.postgres_store import PostgresConversationStore


@pytest.mark.asyncio
async def test_db_persistence_flow(session):
    store = PostgresConversationStore(session=session, owner_key_id=None)
    conversation_id = str(uuid.uuid4())

    convo = await store.create_conversation(conversation_id)
    assert convo["id"] == conversation_id

    await store.add_user_message(conversation_id, "hello")
    await store.add_assistant_message(conversation_id, [], [], {"model": "x", "response": "world"})

    convos = await store.list_conversations()
    assert len(convos) == 1
    assert convos[0]["message_count"] == 2

    loaded = await store.get_conversation(conversation_id)
    assert loaded is not None
    assert [m["role"] for m in loaded["messages"]] == ["user", "assistant"]
    assert loaded["messages"][1]["content"] == "world"

