from __future__ import annotations

import asyncio

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .. import config
from ..engine import openrouter
from ..db.session import get_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from . import tools
from .runtime import call_tool_with_guards


def build_server() -> Server:
    server = Server(name="llm-council-mcp")

    @server.list_tools()
    async def _list_tools():
        return tools.list_tools()

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict):
        if name not in ("council.ask", "council.pipeline"):
            return {"degraded": True, "errors": ["unknown_tool"]}

        engine = get_engine()
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                result = await call_tool_with_guards(session, name, arguments)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

    return server


async def run_stdio() -> None:
    limits = httpx.Limits(
        max_connections=max(1, config.OPENROUTER_MAX_CONCURRENCY),
        max_keepalive_connections=max(1, config.OPENROUTER_MAX_CONCURRENCY),
    )
    timeout = httpx.Timeout(config.OPENROUTER_TIMEOUT_SECONDS)
    client = httpx.AsyncClient(timeout=timeout, limits=limits)
    openrouter.set_client(client)

    server = build_server()
    init_options = server.create_initialization_options()

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, init_options)
    finally:
        openrouter.set_client(None)
        await client.aclose()


def main() -> None:
    asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
