from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import asyncpg


LOCK_ID = 987654321


def _dsn_for_asyncpg(database_url: str) -> str:
    # App URLs use SQLAlchemy dialect prefixes; asyncpg wants plain postgresql://
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if database_url.startswith("postgresql+psycopg2://"):
        return database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    return database_url


async def _run() -> int:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        print("DATABASE_URL is not set; skipping migrations.", file=sys.stderr)
        return 0

    dsn = _dsn_for_asyncpg(database_url)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("SELECT pg_advisory_lock($1);", LOCK_ID)
        try:
            completed = subprocess.run(
                ["alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
                check=True,
            )
            return completed.returncode
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1);", LOCK_ID)
    finally:
        await conn.close()


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()

