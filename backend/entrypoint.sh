#!/usr/bin/env sh
set -e

export PYTHONPATH=/app

if [ -n "${DATABASE_URL:-}" ]; then
  python3 -m backend.src.scripts.run_migrations_with_lock
fi

exec uvicorn backend.src.app.main:app --host 0.0.0.0 --port 8001
