from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.src.db.models import ApiKey
from backend.src.db.session import get_engine
from backend.src.services.auth import generate_api_key, hash_api_key


async def _run(
    *,
    name: str,
    rate_limit_per_min: int,
    monthly_token_cap: int | None,
    deactivate_id: str | None,
    deactivate_hash: str | None,
) -> None:
    plaintext = generate_api_key()
    key_hash = hash_api_key(plaintext)

    engine = get_engine()
    async with AsyncSession(engine) as session:
        existing = (await session.exec(select(ApiKey).where(ApiKey.key_hash == key_hash))).first()
        if existing:
            raise RuntimeError("Generated key hash collision; retry")

        account_root_id: uuid.UUID | None = None
        if deactivate_id:
            key = await session.get(ApiKey, uuid.UUID(deactivate_id))
            if key is None:
                raise SystemExit(f"API key not found: {deactivate_id}")
            account_root_id = key.account_id or key.id
            key.is_active = False
            key.deactivated_at = datetime.utcnow()
            session.add(key)

        if deactivate_hash:
            key = (await session.exec(select(ApiKey).where(ApiKey.key_hash == deactivate_hash))).first()
            if key is None:
                raise SystemExit("API key hash not found")
            account_root_id = key.account_id or key.id
            key.is_active = False
            key.deactivated_at = datetime.utcnow()
            session.add(key)

        api_key = ApiKey(
            key_hash=key_hash,
            account_id=account_root_id,
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
    parser = argparse.ArgumentParser(
        description="Rotate an API key: create a new key and optionally deactivate an existing one."
    )
    parser.add_argument("--name", default="default")
    parser.add_argument("--rate-limit-per-min", type=int, default=60)
    parser.add_argument("--monthly-token-cap", type=int, default=None)
    parser.add_argument("--deactivate-id", default=None)
    parser.add_argument("--deactivate-hash", default=None)
    args = parser.parse_args()

    if args.deactivate_id and args.deactivate_hash:
        raise SystemExit("Use only one of --deactivate-id or --deactivate-hash")

    asyncio.run(
        _run(
            name=args.name,
            rate_limit_per_min=args.rate_limit_per_min,
            monthly_token_cap=args.monthly_token_cap,
            deactivate_id=args.deactivate_id,
            deactivate_hash=args.deactivate_hash,
        )
    )


if __name__ == "__main__":
    main()
