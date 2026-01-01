from __future__ import annotations

import os
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from .. import config
from ..db.models import ApiKey
from ..services.auth import hash_api_key
from ..services.quota import is_quota_exceeded


async def resolve_mcp_api_key(
    session: AsyncSession,
    *,
    api_key_input: Optional[str],
) -> tuple[ApiKey | None, list[str]]:
    """
    Resolve an ApiKey for MCP calls.

    IMPORTANT: Never log plaintext keys.
    """
    plaintext = api_key_input or os.getenv("MCP_API_KEY")
    if not plaintext:
        if config.ALLOW_NO_AUTH:
            return None, []
        return None, ["auth_required"]

    try:
        key_hash = hash_api_key(plaintext)
    except Exception:
        if config.ALLOW_NO_AUTH:
            return None, []
        return None, ["auth_required"]
    api_key = (await session.exec(select(ApiKey).where(ApiKey.key_hash == key_hash))).first()
    if api_key is None or not api_key.is_active or api_key.deactivated_at is not None:
        if config.ALLOW_NO_AUTH:
            return None, []
        return None, ["auth_required"]

    if await is_quota_exceeded(
        session,
        owner_key_id=api_key.id,
        monthly_token_cap=api_key.monthly_token_cap,
        estimated_minimum_next_run_tokens=1,
    ):
        return None, ["quota_exceeded"]

    return api_key, []
