import os

# Ensure config reads these during import in tests.
os.environ.setdefault("ALLOW_NO_AUTH", "true")
os.environ.setdefault("API_KEY_PEPPER", "test-pepper")
os.environ.setdefault("COUNCIL_CACHE_ENABLED", "true")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest_asyncio.fixture
async def engine(monkeypatch):
    test_engine = create_async_engine(os.environ["DATABASE_URL"])

    import backend.src.db.session as session_module

    session_module._ENGINE = test_engine

    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield test_engine
    finally:
        await test_engine.dispose()
        session_module._ENGINE = None


@pytest_asyncio.fixture
async def session(engine):
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s
