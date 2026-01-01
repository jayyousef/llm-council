from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from .. import config as app_config
from ..db.models import UsageEvent
from ..utils.redact import redact_secrets


def _estimate_cost(model: str, prompt_tokens: int | None, completion_tokens: int | None) -> Optional[float]:
    pricing = app_config.MODEL_PRICING.get(model)
    if not pricing:
        return None
    prompt_per_1m = float(pricing.get("prompt_per_1m", 0.0))
    completion_per_1m = float(pricing.get("completion_per_1m", 0.0))
    if prompt_tokens is None and completion_tokens is None:
        return None
    cost = 0.0
    if prompt_tokens is not None:
        cost += (prompt_tokens / 1_000_000.0) * prompt_per_1m
    if completion_tokens is not None:
        cost += (completion_tokens / 1_000_000.0) * completion_per_1m
    return round(cost, 8)


class UsageService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def record_usage_event(
        self,
        owner_key_id: uuid.UUID | None,
        run_id: uuid.UUID,
        model: str,
        usage: Optional[dict[str, Any]],
        *,
        call_id: uuid.UUID,
        attempt: int,
        latency_ms: int | None,
        error_text: str | None = None,
    ) -> uuid.UUID:
        prompt_tokens = None
        completion_tokens = None
        total_tokens = None
        usage_missing = False

        if usage and isinstance(usage, dict):
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
        else:
            usage_missing = True

        if error_text:
            usage_missing = True

        cost_estimated = _estimate_cost(model, prompt_tokens, completion_tokens)
        raw_usage_json: dict[str, Any] | None = dict(usage) if (usage and isinstance(usage, dict)) else None
        if error_text:
            raw_usage_json = {
                "error": redact_secrets(error_text),
                "attempt": attempt,
                "call_id": str(call_id),
                "usage": usage,
            }
        if raw_usage_json is not None and "price_book_version" not in raw_usage_json:
            raw_usage_json["price_book_version"] = app_config.PRICE_BOOK_VERSION

        event = UsageEvent(
            owner_key_id=owner_key_id,
            run_id=run_id,
            model=model,
            call_id=call_id,
            attempt=attempt,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_estimated=cost_estimated,
            created_at=datetime.utcnow(),
            latency_ms=latency_ms,
            raw_usage_json=raw_usage_json,
            usage_missing=usage_missing,
        )
        self._session.add(event)
        await self._session.flush()
        return event.id
