"""FastAPI backend for LLM Council."""

from __future__ import annotations

import logging
import re
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .routes import conversations as conversations_routes
from .routes import council as council_routes
from .routes import tools_gateway as tools_gateway_routes
from .routes import account as account_routes
from .. import config
from ..engine import openrouter

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(
        max_connections=max(1, config.OPENROUTER_MAX_CONCURRENCY),
        max_keepalive_connections=max(1, config.OPENROUTER_MAX_CONCURRENCY),
    )
    timeout = httpx.Timeout(config.OPENROUTER_TIMEOUT_SECONDS)
    client = httpx.AsyncClient(timeout=timeout, limits=limits)
    openrouter.set_client(client)
    try:
        yield
    finally:
        openrouter.set_client(None)
        await client.aclose()


app = FastAPI(title="LLM Council API", lifespan=lifespan)

_cors_origins = config.cors_allow_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False if _cors_origins == ["*"] else True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _safe_detail(detail: object) -> str:
    if isinstance(detail, str):
        return detail
    return "Request failed"


def _maybe_error_code(detail: str) -> str | None:
    if re.fullmatch(r"[a-z0-9_]+", detail or ""):
        return detail
    return None


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    detail = _safe_detail(exc.detail)
    payload: dict[str, object] = {"detail": detail, "request_id": request_id}
    code = _maybe_error_code(detail)
    if code:
        payload["error_code"] = code
    logger.info("HTTPException %s request_id=%s detail=%s", exc.status_code, request_id, detail)
    resp = JSONResponse(status_code=exc.status_code, content=payload)
    resp.headers["X-Request-ID"] = request_id
    return resp


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    logger.exception("Unhandled exception request_id=%s", request_id)
    resp = JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id, "error_code": "internal_server_error"},
    )
    resp.headers["X-Request-ID"] = request_id
    return resp


app.include_router(conversations_routes.router)
app.include_router(council_routes.router)
app.include_router(tools_gateway_routes.router)
app.include_router(account_routes.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
