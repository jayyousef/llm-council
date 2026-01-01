from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..db.models import UsageEvent


def _month_bounds_utc(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    return start.replace(tzinfo=None), next_month.replace(tzinfo=None)


async def monthly_tokens_used(session: AsyncSession, owner_key_id: uuid.UUID) -> int:
    start, end = _month_bounds_utc()
    tokens_expr = func.coalesce(
        UsageEvent.total_tokens,
        func.coalesce(UsageEvent.prompt_tokens, 0) + func.coalesce(UsageEvent.completion_tokens, 0),
    )
    stmt = (
        select(func.coalesce(func.sum(tokens_expr), 0))
        .where(UsageEvent.owner_key_id == owner_key_id)
        .where(UsageEvent.created_at >= start)
        .where(UsageEvent.created_at < end)
    )
    total = (await session.exec(stmt)).one()
    return int(total or 0)


async def is_quota_exceeded(
    session: AsyncSession,
    *,
    owner_key_id: uuid.UUID,
    monthly_token_cap: Optional[int],
    estimated_minimum_next_run_tokens: int = 1,
) -> bool:
    if monthly_token_cap is None or monthly_token_cap <= 0:
        return False
    used = await monthly_tokens_used(session, owner_key_id)
    return used + max(0, int(estimated_minimum_next_run_tokens)) > int(monthly_token_cap)

