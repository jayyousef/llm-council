from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.src.db.models import ApiKey
from backend.src.db.session import get_engine
from backend.src.services.auth import generate_api_key, hash_api_key


async def _run(name: str, rate_limit_per_min: int, monthly_token_cap: int | None) -> None:
    plaintext = generate_api_key()
    key_hash = hash_api_key(plaintext)

    engine = get_engine()
    async with AsyncSession(engine) as session:
        existing = (await session.exec(select(ApiKey).where(ApiKey.key_hash == key_hash))).first()
        if existing:
            raise RuntimeError("Generated key hash collision; retry")

        api_key = ApiKey(
            key_hash=key_hash,
            name=name,
            is_active=True,
            rate_limit_per_min=rate_limit_per_min,
            created_at=datetime.utcnow(),
            monthly_token_cap=monthly_token_cap,
        )
        session.add(api_key)
        await session.commit()

    # Print the plaintext key ONCE. Never store or log it elsewhere.
    print(plaintext)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an API key (prints plaintext once).")
    parser.add_argument("--name", default="default")
    parser.add_argument("--rate-limit-per-min", type=int, default=60)
    parser.add_argument("--monthly-token-cap", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(_run(args.name, args.rate_limit_per_min, args.monthly_token_cap))


if __name__ == "__main__":
    main()

