from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from ..config import DATABASE_URL


_ENGINE: Optional[AsyncEngine] = None


def get_engine() -> AsyncEngine:
    global _ENGINE
    if _ENGINE is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set")
        _ENGINE = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    return _ENGINE


async def get_session() -> AsyncIterator[AsyncSession]:
    engine = get_engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
