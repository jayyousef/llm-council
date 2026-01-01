"""JSON-file based ConversationStore implementation (prototype storage)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import DATA_DIR
from .conversation_store import ConversationStore


class JsonConversationStore:
    def ensure_data_dir(self) -> None:
        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

    def get_conversation_path(self, conversation_id: str) -> str:
        return os.path.join(DATA_DIR, f"{conversation_id}.json")

    async def create_conversation(self, conversation_id: str) -> Dict[str, Any]:
        self.ensure_data_dir()

        conversation = {
            "id": conversation_id,
            "created_at": datetime.utcnow().isoformat(),
            "title": "New Conversation",
            "messages": [],
        }

        path = self.get_conversation_path(conversation_id)
        with open(path, "w") as f:
            json.dump(conversation, f, indent=2)

        return conversation

    async def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        path = self.get_conversation_path(conversation_id)
        if not os.path.exists(path):
            return None

        with open(path, "r") as f:
            return json.load(f)

    async def save_conversation(self, conversation: Dict[str, Any]) -> None:
        self.ensure_data_dir()
        path = self.get_conversation_path(conversation["id"])
        with open(path, "w") as f:
            json.dump(conversation, f, indent=2)

    async def list_conversations(self) -> List[Dict[str, Any]]:
        self.ensure_data_dir()

        conversations = []
        for filename in os.listdir(DATA_DIR):
            if filename.endswith(".json"):
                path = os.path.join(DATA_DIR, filename)
                with open(path, "r") as f:
                    data = json.load(f)
                    conversations.append(
                        {
                            "id": data["id"],
                            "created_at": data["created_at"],
                            "title": data.get("title", "New Conversation"),
                            "message_count": len(data["messages"]),
                        }
                    )

        conversations.sort(key=lambda x: x["created_at"], reverse=True)
        return conversations

    async def add_user_message(self, conversation_id: str, content: str) -> None:
        conversation = await self.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        conversation["messages"].append({"role": "user", "content": content})
        await self.save_conversation(conversation)

    async def add_assistant_message(
        self,
        conversation_id: str,
        stage1: List[Dict[str, Any]],
        stage2: List[Dict[str, Any]],
        stage3: Dict[str, Any],
    ) -> None:
        conversation = await self.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        conversation["messages"].append({"role": "assistant", "stage1": stage1, "stage2": stage2, "stage3": stage3})
        await self.save_conversation(conversation)

    async def update_conversation_title(self, conversation_id: str, title: str) -> None:
        conversation = await self.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        conversation["title"] = title
        await self.save_conversation(conversation)


_DEFAULT_STORE: ConversationStore = JsonConversationStore()


def get_default_store() -> ConversationStore:
    return _DEFAULT_STORE
