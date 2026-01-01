from __future__ import annotations

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from ..config import DATABASE_URL
from ..db.models import ApiKey
from ..db.session import get_session
from .auth import get_api_key
from .conversation_store import ConversationStore
from .json_store import get_default_store as get_json_store
from .postgres_store import PostgresConversationStore


async def get_default_store(
    session: AsyncSession = Depends(get_session),
    api_key: ApiKey | None = Depends(get_api_key),
) -> ConversationStore:
    if DATABASE_URL:
        owner_key_id = api_key.id if api_key else None
        account_root_id = (api_key.account_id or api_key.id) if api_key else None
        return PostgresConversationStore(
            session=session,
            owner_key_id=owner_key_id,
            account_root_id=account_root_id,
        )
    return get_json_store()
