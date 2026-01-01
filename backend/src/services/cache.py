from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..config import COUNCIL_CACHE_ENABLED, COUNCIL_CACHE_TTL_SECONDS_INT
from ..db.models import CacheEntry


def make_cache_key(parts: dict[str, Any]) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"council:{digest}"


class CacheService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_json(self, key: str) -> Optional[dict[str, Any]]:
        if not COUNCIL_CACHE_ENABLED:
            return None

        entry = (await self._session.exec(select(CacheEntry).where(CacheEntry.key == key))).first()
        if entry is None:
            return None

        if entry.expires_at and entry.expires_at <= datetime.utcnow():
            await self._session.delete(entry)
            await self._session.flush()
            return None

        return entry.value_json

    async def set_json(self, key: str, value_json: dict[str, Any], ttl_seconds: int | None = None) -> None:
        if not COUNCIL_CACHE_ENABLED:
            return

        ttl = ttl_seconds if ttl_seconds is not None else COUNCIL_CACHE_TTL_SECONDS_INT
        expires_at = datetime.utcnow() + timedelta(seconds=ttl) if ttl else None

        existing = (await self._session.exec(select(CacheEntry).where(CacheEntry.key == key))).first()
        if existing is None:
            entry = CacheEntry(
                key=key,
                value_json=value_json,
                created_at=datetime.utcnow(),
                expires_at=expires_at,
            )
            self._session.add(entry)
        else:
            existing.value_json = value_json
            existing.created_at = datetime.utcnow()
            existing.expires_at = expires_at
            self._session.add(existing)
        await self._session.flush()
