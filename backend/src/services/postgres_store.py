from __future__ import annotations

from datetime import datetime
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..db.models import ApiKey, Conversation, Message
from .conversation_store import ConversationStore


class PostgresConversationStore:
    def __init__(
        self,
        session: AsyncSession,
        owner_key_id: uuid.UUID | None,
        *,
        account_root_id: uuid.UUID | None = None,
    ):
        self._session = session
        self._owner_key_id = owner_key_id
        self._account_root_id = account_root_id

    def _conversation_scope_clause(self):
        if self._owner_key_id is None:
            return Conversation.owner_key_id.is_(None)
        root = self._account_root_id or self._owner_key_id
        account_key_ids = select(ApiKey.id).where((ApiKey.id == root) | (ApiKey.account_id == root))
        return Conversation.owner_key_id.in_(account_key_ids)

    async def list_conversations(self) -> List[Dict[str, Any]]:
        stmt = (
            select(
                Conversation.id,
                Conversation.created_at,
                Conversation.title,
                func.count(Message.id).label("message_count"),
            )
            .where(self._conversation_scope_clause())
            .join(Message, Message.conversation_id == Conversation.id, isouter=True)
            .group_by(Conversation.id)
            .order_by(Conversation.created_at.desc())
        )
        rows = (await self._session.exec(stmt)).all()
        return [
            {
                "id": str(row.id),
                "created_at": row.created_at.isoformat(),
                "title": row.title,
                "message_count": int(row.message_count or 0),
            }
            for row in rows
        ]

    async def create_conversation(self, conversation_id: str) -> Dict[str, Any]:
        conversation_uuid = uuid.UUID(conversation_id)
        now = datetime.utcnow()
        conversation = Conversation(
            id=conversation_uuid,
            title="New Conversation",
            created_at=now,
            updated_at=now,
            owner_key_id=self._owner_key_id,
        )
        self._session.add(conversation)
        await self._session.flush()

        return {
            "id": str(conversation_uuid),
            "created_at": now.isoformat(),
            "title": "New Conversation",
            "messages": [],
        }

    async def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        conversation_uuid = uuid.UUID(conversation_id)
        convo = (
            await self._session.exec(
                select(Conversation)
                .where(Conversation.id == conversation_uuid)
                .where(self._conversation_scope_clause())
            )
        ).first()
        if convo is None:
            return None

        msgs = (
            await self._session.exec(
                select(Message)
                .where(Message.conversation_id == conversation_uuid)
                .order_by(Message.created_at.asc())
            )
        ).all()

        return {
            "id": str(convo.id),
            "created_at": convo.created_at.isoformat(),
            "title": convo.title,
            "messages": [{"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()} for m in msgs],
        }

    async def add_user_message(self, conversation_id: str, content: str) -> None:
        conversation_uuid = uuid.UUID(conversation_id)
        convo = (
            await self._session.exec(
                select(Conversation)
                .where(Conversation.id == conversation_uuid)
                .where(self._conversation_scope_clause())
            )
        ).first()
        if convo is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        msg = Message(
            conversation_id=conversation_uuid,
            role="user",
            content=content,
            created_at=datetime.utcnow(),
        )
        convo.updated_at = datetime.utcnow()
        self._session.add(msg)
        self._session.add(convo)
        await self._session.flush()

    async def add_assistant_message(
        self,
        conversation_id: str,
        stage1: List[Dict[str, Any]],
        stage2: List[Dict[str, Any]],
        stage3: Dict[str, Any],
    ) -> None:
        # IMPORTANT DATA MODEL CHOICE (Phase B):
        # Store ONLY the final assistant answer as the assistant message content (stage3.response).
        conversation_uuid = uuid.UUID(conversation_id)
        convo = (
            await self._session.exec(
                select(Conversation)
                .where(Conversation.id == conversation_uuid)
                .where(self._conversation_scope_clause())
            )
        ).first()
        if convo is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        content = ""
        if isinstance(stage3, dict):
            content = str(stage3.get("response", "") or "")

        msg = Message(
            conversation_id=conversation_uuid,
            role="assistant",
            content=content,
            created_at=datetime.utcnow(),
        )
        convo.updated_at = datetime.utcnow()
        self._session.add(msg)
        self._session.add(convo)
        await self._session.flush()

    async def update_conversation_title(self, conversation_id: str, title: str) -> None:
        conversation_uuid = uuid.UUID(conversation_id)
        convo = (
            await self._session.exec(
                select(Conversation)
                .where(Conversation.id == conversation_uuid)
                .where(self._conversation_scope_clause())
            )
        ).first()
        if convo is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        convo.title = title
        convo.updated_at = datetime.utcnow()
        self._session.add(convo)
        await self._session.flush()


def _as_store(obj: PostgresConversationStore) -> ConversationStore:
    return obj
