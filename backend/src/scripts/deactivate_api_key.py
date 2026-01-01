from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from backend.src.db.models import ApiKey
from backend.src.db.session import get_engine


async def _run(api_key_id: str) -> None:
    engine = get_engine()
    async with AsyncSession(engine) as session:
        key = await session.get(ApiKey, uuid.UUID(api_key_id))
        if key is None:
            raise SystemExit(f"API key not found: {api_key_id}")
        key.is_active = False
        key.deactivated_at = datetime.utcnow()
        session.add(key)
        await session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Deactivate an API key by id.")
    parser.add_argument("api_key_id")
    args = parser.parse_args()
    asyncio.run(_run(args.api_key_id))


if __name__ == "__main__":
    main()

