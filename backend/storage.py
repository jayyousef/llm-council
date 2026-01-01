"""Compatibility wrapper for the prototype JSON storage module.

Phase A moves JSON storage behind `backend.src.services.json_store`.
This module preserves the old function-based API used by the prototype.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.src.services.json_store import get_default_store


async def create_conversation(conversation_id: str) -> Dict[str, Any]:
    return await get_default_store().create_conversation(conversation_id)


async def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    return await get_default_store().get_conversation(conversation_id)


async def list_conversations() -> List[Dict[str, Any]]:
    return await get_default_store().list_conversations()


async def add_user_message(conversation_id: str, content: str) -> None:
    await get_default_store().add_user_message(conversation_id, content)


async def add_assistant_message(
    conversation_id: str,
    stage1: List[Dict[str, Any]],
    stage2: List[Dict[str, Any]],
    stage3: Dict[str, Any],
) -> None:
    await get_default_store().add_assistant_message(conversation_id, stage1, stage2, stage3)


async def update_conversation_title(conversation_id: str, title: str) -> None:
    await get_default_store().update_conversation_title(conversation_id, title)
