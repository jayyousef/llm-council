from typing import List
import uuid

from fastapi import APIRouter, Depends, HTTPException

from ..schemas.conversations import (
    Conversation,
    ConversationMetadata,
    CreateConversationRequest,
)
from ...services.conversation_store import ConversationStore
from ...services.store_factory import get_default_store
from ...services.auth import get_api_key
from ...db.models import ApiKey


router = APIRouter()


@router.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations(
    api_key: ApiKey | None = Depends(get_api_key),
    store: ConversationStore = Depends(get_default_store),
):
    """List all conversations (metadata only)."""
    return await store.list_conversations()


@router.post("/api/conversations", response_model=Conversation)
async def create_conversation(
    request: CreateConversationRequest,
    api_key: ApiKey | None = Depends(get_api_key),
    store: ConversationStore = Depends(get_default_store),
):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    return await store.create_conversation(conversation_id)


@router.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(
    conversation_id: str,
    api_key: ApiKey | None = Depends(get_api_key),
    store: ConversationStore = Depends(get_default_store),
):
    """Get a specific conversation with all its messages."""
    conversation = await store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation
