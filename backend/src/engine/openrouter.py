"""OpenRouter API client for making LLM requests (hardened)."""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from ..config import (
    OPENROUTER_API_KEY,
    OPENROUTER_API_URL,
    OPENROUTER_AUTH_COOLDOWN_SECONDS,
    OPENROUTER_MAX_CONCURRENCY,
    OPENROUTER_MAX_RETRIES,
    OPENROUTER_RETRY_BASE_SECONDS,
    OPENROUTER_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


@dataclass
class OpenRouterResult:
    ok: bool
    model: str
    call_id: uuid.UUID
    attempt: int
    content: Optional[str]
    reasoning_details: Any
    usage: Optional[dict[str, Any]]
    raw_response: Optional[dict[str, Any]]
    latency_ms: Optional[int]
    status_code: Optional[int]
    error_text: Optional[str]


_SEMAPHORE = asyncio.Semaphore(max(1, OPENROUTER_MAX_CONCURRENCY))
_CLIENT: httpx.AsyncClient | None = None
_AUTH_INVALID_UNTIL: float = 0.0


def set_client(client: httpx.AsyncClient | None) -> None:
    global _CLIENT
    _CLIENT = client


def _get_client(timeout_seconds: float) -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    logger.warning("OpenRouter httpx client not set via lifespan; creating a fallback client.")
    _CLIENT = httpx.AsyncClient(timeout=timeout_seconds)
    return _CLIENT


def _should_retry(status_code: Optional[int]) -> bool:
    if status_code is None:
        return True
    if status_code == 429:
        return True
    if 500 <= status_code <= 599:
        return True
    return False


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    *,
    call_id: uuid.UUID | None = None,
    attempt: int = 0,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout_seconds: Optional[float] = None,
) -> OpenRouterResult:
    global _AUTH_INVALID_UNTIL
    call_id = call_id or uuid.uuid4()
    now = time.time()
    if now < _AUTH_INVALID_UNTIL:
        return OpenRouterResult(
            ok=False,
            model=model,
            call_id=call_id,
            attempt=attempt,
            content=None,
            reasoning_details=None,
            usage=None,
            raw_response=None,
            latency_ms=0,
            status_code=401,
            error_text="OpenRouter credentials invalid (cooldown)",
        )
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {"model": model, "messages": messages}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    timeout = timeout_seconds if timeout_seconds is not None else OPENROUTER_TIMEOUT_SECONDS
    client = _get_client(timeout)

    async with _SEMAPHORE:
        last_error: Optional[str] = None
        for http_attempt in range(OPENROUTER_MAX_RETRIES + 1):
            start = time.monotonic()
            try:
                resp = await client.post(
                    OPENROUTER_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
                latency_ms = int((time.monotonic() - start) * 1000)

                status_code = resp.status_code
                if status_code in (401, 403):
                    _AUTH_INVALID_UNTIL = time.time() + max(1, int(OPENROUTER_AUTH_COOLDOWN_SECONDS))
                    return OpenRouterResult(
                        ok=False,
                        model=model,
                        call_id=call_id,
                        attempt=attempt,
                        content=None,
                        reasoning_details=None,
                        usage=None,
                        raw_response=None,
                        latency_ms=latency_ms,
                        status_code=status_code,
                        error_text=f"OpenRouter auth error ({status_code})",
                    )

                if status_code >= 400:
                    last_error = f"OpenRouter HTTP {status_code}: {resp.text[:500]}"
                    if http_attempt < OPENROUTER_MAX_RETRIES and _should_retry(status_code):
                        base = OPENROUTER_RETRY_BASE_SECONDS * (2**http_attempt)
                        await asyncio.sleep(base + random.random() * base)
                        continue
                    return OpenRouterResult(
                        ok=False,
                        model=model,
                        call_id=call_id,
                        attempt=attempt,
                        content=None,
                        reasoning_details=None,
                        usage=None,
                        raw_response=None,
                        latency_ms=latency_ms,
                        status_code=status_code,
                        error_text=last_error,
                    )

                data = resp.json()
                message = (data.get("choices") or [{}])[0].get("message") or {}
                usage = data.get("usage") if isinstance(data.get("usage"), dict) else None

                return OpenRouterResult(
                    ok=True,
                    model=model,
                    call_id=call_id,
                    attempt=attempt,
                    content=message.get("content"),
                    reasoning_details=message.get("reasoning_details"),
                    usage=usage,
                    raw_response=data,
                    latency_ms=latency_ms,
                    status_code=status_code,
                    error_text=None,
                )

            except Exception as e:
                latency_ms = int((time.monotonic() - start) * 1000)
                last_error = f"Error querying model {model}: {e}"
                if http_attempt < OPENROUTER_MAX_RETRIES:
                    base = OPENROUTER_RETRY_BASE_SECONDS * (2**http_attempt)
                    await asyncio.sleep(base + random.random() * base)
                    continue
                return OpenRouterResult(
                    ok=False,
                    model=model,
                    call_id=call_id,
                    attempt=attempt,
                    content=None,
                    reasoning_details=None,
                    usage=None,
                    raw_response=None,
                    latency_ms=latency_ms,
                    status_code=None,
                    error_text=last_error,
                )

        return OpenRouterResult(
            ok=False,
            model=model,
            call_id=call_id,
            attempt=attempt,
            content=None,
            reasoning_details=None,
            usage=None,
            raw_response=None,
            latency_ms=None,
            status_code=None,
            error_text=last_error or "Unknown OpenRouter error",
        )


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]],
    *,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout_seconds: Optional[float] = None,
) -> Dict[str, OpenRouterResult]:
    tasks = [
        query_model(
            model,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        for model in models
    ]
    results = await asyncio.gather(*tasks)
    return {model: result for model, result in zip(models, results)}
