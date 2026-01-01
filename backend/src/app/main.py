"""FastAPI backend for LLM Council."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import conversations as conversations_routes
from .routes import council as council_routes
from .routes import tools_gateway as tools_gateway_routes
from .routes import account as account_routes
from .. import config
from ..engine import openrouter


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

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}

@app.middleware("http")
async def add_request_id(request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(conversations_routes.router)
app.include_router(council_routes.router)
app.include_router(tools_gateway_routes.router)
app.include_router(account_routes.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
