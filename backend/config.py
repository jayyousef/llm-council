"""Compatibility re-exports for the prototype layout.

Phase A moves config to `backend.src.config`.
"""

from backend.src.config import (  # noqa: F401
    OPENROUTER_API_KEY,
    COUNCIL_MODELS,
    CHAIRMAN_MODEL,
    OPENROUTER_API_URL,
    DATA_DIR,
)
