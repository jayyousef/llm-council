"""Compatibility re-exports for the prototype layout.

Phase A moves the OpenRouter client to `backend.src.engine.openrouter`.
"""

from backend.src.engine.openrouter import (  # noqa: F401
    query_model,
    query_models_parallel,
)
