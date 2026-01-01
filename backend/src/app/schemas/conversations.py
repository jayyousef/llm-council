from typing import Any, Dict, List

from pydantic import BaseModel


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""

    content: str


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""

    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""

    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]
