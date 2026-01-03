from __future__ import annotations

import hmac
import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
import logging
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..config import ALLOW_NO_AUTH, API_KEY_PEPPER, ENV
from ..db.models import ApiKey
from ..db.session import get_session
from .quota import is_quota_exceeded

logger = logging.getLogger(__name__)


def hash_api_key(plaintext_key: str) -> str:
    if not API_KEY_PEPPER and not ALLOW_NO_AUTH:
        logger.error("Missing API_KEY_PEPPER while ALLOW_NO_AUTH is false (server misconfigured)")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="api_key_pepper_missing")
    secret = (API_KEY_PEPPER or "").encode("utf-8")
    msg = plaintext_key.encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def generate_api_key() -> str:
    # Prefix makes it obvious in logs without revealing the secret.
    return f"lc_{secrets.token_urlsafe(32)}"


@dataclass
class _InMemRateLimitState:
    """NOTE: This limiter is per-process only (not shared across replicas)."""

    window_start: float
    count: int


_INMEM_RATE_LIMIT: dict[uuid.UUID, _InMemRateLimitState] = {}
_INMEM_RATE_LIMIT_WARNED = False


def _enforce_rate_limit(owner_key_id: uuid.UUID, limit_per_min: int) -> None:
    if limit_per_min <= 0:
        return

    now = time.time()
    state = _INMEM_RATE_LIMIT.get(owner_key_id)
    if state is None or now - state.window_start >= 60.0:
        _INMEM_RATE_LIMIT[owner_key_id] = _InMemRateLimitState(window_start=now, count=1)
        return

    state.count += 1
    if state.count > limit_per_min:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )


async def get_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    session: AsyncSession = Depends(get_session),
) -> Optional[ApiKey]:
    if not x_api_key:
        if ALLOW_NO_AUTH:
            return None
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-Key")

    key_hash = hash_api_key(x_api_key)
    api_key = (await session.exec(select(ApiKey).where(ApiKey.key_hash == key_hash))).first()
    if api_key is None or not api_key.is_active or api_key.deactivated_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    global _INMEM_RATE_LIMIT_WARNED
    if ENV == "production" and not _INMEM_RATE_LIMIT_WARNED and api_key.rate_limit_per_min > 0:
        logger.warning(
            "In-memory rate limit enabled; not distributed. Use a shared limiter (DB/Redis) for multi-replica deploys."
        )
        _INMEM_RATE_LIMIT_WARNED = True

    _enforce_rate_limit(api_key.id, api_key.rate_limit_per_min)
    api_key.last_used_at = datetime.utcnow()
    session.add(api_key)
    await session.flush()
    return api_key


async def get_api_key_for_run(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    session: AsyncSession = Depends(get_session),
) -> Optional[ApiKey]:
    """
    API key dependency for endpoints that start billable runs.
    Enforces monthly_token_cap as a hard stop.
    """
    api_key = await get_api_key(x_api_key=x_api_key, session=session)
    if api_key is None:
        return None
    if await is_quota_exceeded(
        session,
        owner_key_id=api_key.id,
        monthly_token_cap=api_key.monthly_token_cap,
        estimated_minimum_next_run_tokens=1,
    ):
        raise HTTPException(status_code=402, detail="quota_exceeded")
    return api_key
