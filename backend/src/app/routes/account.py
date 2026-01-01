from __future__ import annotations

from datetime import date, datetime, timedelta
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..schemas.account import (
    ApiKeyMetadata,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
    RotateApiKeyResponse,
    UsageByModelEntry,
    UsageSummaryResponse,
    LimitsResponse,
)
from ...db.models import ApiKey, UsageEvent
from ...db.session import get_session
from ...services.auth import generate_api_key, get_api_key, hash_api_key
from ...services.quota import monthly_tokens_used, _month_bounds_utc


router = APIRouter()


def _account_root_id(api_key: ApiKey) -> uuid.UUID:
    return api_key.account_id or api_key.id


def _api_key_metadata(row: ApiKey) -> ApiKeyMetadata:
    return ApiKeyMetadata(
        id=str(row.id),
        name=row.name,
        created_at=row.created_at.isoformat(),
        last_used_at=row.last_used_at.isoformat() if row.last_used_at else None,
        is_active=bool(row.is_active) and row.deactivated_at is None,
        deactivated_at=row.deactivated_at.isoformat() if row.deactivated_at else None,
        rate_limit_per_min=int(row.rate_limit_per_min or 0),
        monthly_token_cap=row.monthly_token_cap,
    )


@router.get("/api/account/api-keys", response_model=list[ApiKeyMetadata])
async def list_api_keys(
    api_key: ApiKey | None = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    if api_key is None:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    root = _account_root_id(api_key)
    stmt = select(ApiKey).where((ApiKey.id == root) | (ApiKey.account_id == root)).order_by(ApiKey.created_at.desc())
    keys = (await session.exec(stmt)).all()
    return [_api_key_metadata(k) for k in keys]


@router.post("/api/account/api-keys", response_model=CreateApiKeyResponse)
async def create_api_key_endpoint(
    request: CreateApiKeyRequest,
    api_key: ApiKey | None = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    if api_key is None:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    root = _account_root_id(api_key)

    plaintext = None
    key_hash = None
    for _ in range(3):
        plaintext = generate_api_key()
        key_hash = hash_api_key(plaintext)
        existing = (await session.exec(select(ApiKey).where(ApiKey.key_hash == key_hash))).first()
        if not existing:
            break
    else:
        raise HTTPException(status_code=500, detail="api_key_generation_failed")

    created = ApiKey(
        key_hash=key_hash,  # type: ignore[arg-type]
        account_id=root,
        name=request.name or "default",
        is_active=True,
        rate_limit_per_min=int(request.rate_limit_per_min or 60),
        created_at=datetime.utcnow(),
        monthly_token_cap=request.monthly_token_cap,
    )
    session.add(created)
    await session.commit()

    return CreateApiKeyResponse(
        api_key_id=str(created.id),
        plaintext_key=plaintext or "",
        api_key=_api_key_metadata(created),
    )


@router.post("/api/account/api-keys/{api_key_id}/deactivate", response_model=ApiKeyMetadata)
async def deactivate_api_key(
    api_key_id: str,
    api_key: ApiKey | None = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    if api_key is None:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    root = _account_root_id(api_key)
    target = await session.get(ApiKey, uuid.UUID(api_key_id))
    if target is None:
        raise HTTPException(status_code=404, detail="api_key_not_found")
    if not (target.id == root or target.account_id == root):
        raise HTTPException(status_code=404, detail="api_key_not_found")

    target.is_active = False
    target.deactivated_at = datetime.utcnow()
    session.add(target)
    await session.commit()
    return _api_key_metadata(target)


@router.post("/api/account/api-keys/{api_key_id}/rotate", response_model=RotateApiKeyResponse)
async def rotate_api_key_endpoint(
    api_key_id: str,
    api_key: ApiKey | None = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    if api_key is None:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    root = _account_root_id(api_key)
    old = await session.get(ApiKey, uuid.UUID(api_key_id))
    if old is None:
        raise HTTPException(status_code=404, detail="api_key_not_found")
    if not (old.id == root or old.account_id == root):
        raise HTTPException(status_code=404, detail="api_key_not_found")

    plaintext = None
    key_hash = None
    for _ in range(3):
        plaintext = generate_api_key()
        key_hash = hash_api_key(plaintext)
        existing = (await session.exec(select(ApiKey).where(ApiKey.key_hash == key_hash))).first()
        if not existing:
            break
    else:
        raise HTTPException(status_code=500, detail="api_key_generation_failed")

    new_key = ApiKey(
        key_hash=key_hash,  # type: ignore[arg-type]
        account_id=root,
        name=old.name,
        is_active=True,
        rate_limit_per_min=int(old.rate_limit_per_min or 60),
        created_at=datetime.utcnow(),
        monthly_token_cap=old.monthly_token_cap,
    )
    old.is_active = False
    old.deactivated_at = datetime.utcnow()
    session.add(old)
    session.add(new_key)
    await session.commit()

    return RotateApiKeyResponse(
        old_key_id=str(old.id),
        new_key_id=str(new_key.id),
        plaintext_key=plaintext or "",
        new_key=_api_key_metadata(new_key),
    )


@router.get("/api/account/usage", response_model=UsageSummaryResponse)
async def usage_summary(
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    api_key: ApiKey | None = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    if api_key is None:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="invalid_date_range")

    start = datetime.combine(from_date, datetime.min.time())
    end = datetime.combine(to_date + timedelta(days=1), datetime.min.time())

    tokens_total_expr = func.coalesce(
        UsageEvent.total_tokens,
        func.coalesce(UsageEvent.prompt_tokens, 0) + func.coalesce(UsageEvent.completion_tokens, 0),
    )

    total_stmt = (
        select(
            func.coalesce(func.sum(func.coalesce(UsageEvent.prompt_tokens, 0)), 0),
            func.coalesce(func.sum(func.coalesce(UsageEvent.completion_tokens, 0)), 0),
            func.coalesce(func.sum(tokens_total_expr), 0),
            func.coalesce(func.sum(func.coalesce(UsageEvent.cost_estimated, 0.0)), 0.0),
        )
        .where(UsageEvent.owner_key_id == api_key.id)
        .where(UsageEvent.created_at >= start)
        .where(UsageEvent.created_at < end)
    )
    totals = (await session.exec(total_stmt)).one()
    total_prompt, total_completion, total_tokens, total_cost = totals

    by_model_stmt = (
        select(
            UsageEvent.model,
            func.count(UsageEvent.id),
            func.coalesce(func.sum(func.coalesce(UsageEvent.prompt_tokens, 0)), 0),
            func.coalesce(func.sum(func.coalesce(UsageEvent.completion_tokens, 0)), 0),
            func.coalesce(func.sum(tokens_total_expr), 0),
            func.coalesce(func.sum(func.coalesce(UsageEvent.cost_estimated, 0.0)), 0.0),
        )
        .where(UsageEvent.owner_key_id == api_key.id)
        .where(UsageEvent.created_at >= start)
        .where(UsageEvent.created_at < end)
        .group_by(UsageEvent.model)
        .order_by(UsageEvent.model.asc())
    )
    rows = (await session.exec(by_model_stmt)).all()
    by_model = [
        UsageByModelEntry(
            model=r[0],
            attempts=int(r[1] or 0),
            prompt_tokens=int(r[2] or 0),
            completion_tokens=int(r[3] or 0),
            total_tokens=int(r[4] or 0),
            cost_estimated=float(r[5] or 0.0),
        )
        for r in rows
    ]

    return UsageSummaryResponse(
        **{
            "from": from_date,
            "to": to_date,
        },
        total_prompt_tokens=int(total_prompt or 0),
        total_completion_tokens=int(total_completion or 0),
        total_tokens=int(total_tokens or 0),
        total_cost_estimated=float(total_cost or 0.0),
        by_model=by_model,
    )


@router.get("/api/account/limits", response_model=LimitsResponse)
async def limits(
    api_key: ApiKey | None = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    if api_key is None:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    used = await monthly_tokens_used(session, api_key.id)
    month_start, _ = _month_bounds_utc()
    cap = api_key.monthly_token_cap

    tokens_remaining = None
    quota_exceeded = False
    if cap is not None and cap > 0:
        tokens_remaining = max(0, int(cap) - int(used))
        quota_exceeded = int(used) >= int(cap)

    return LimitsResponse(
        monthly_token_cap=cap,
        month_start=month_start.isoformat(),
        tokens_used_this_month=int(used),
        tokens_remaining=tokens_remaining,
        quota_exceeded=quota_exceeded,
    )
