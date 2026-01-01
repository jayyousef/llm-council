"""Configuration for the LLM Council."""

import os
import json
from dotenv import load_dotenv

# Load local env files if present (never commit these).
# - `.env.local` is convenient for local dev (Vite also loads it automatically).
# - `.env` is the default for docker-compose variable substitution.
load_dotenv(dotenv_path=".env.local", override=False)
load_dotenv(dotenv_path=".env", override=False)

# Environment name (used for warnings/behavior toggles)
ENV = os.getenv("ENV", "development")

# Database URL (async driver recommended: postgresql+asyncpg://...)
DATABASE_URL = os.getenv("DATABASE_URL")

# Auth (Phase B): allow bypassing API key auth in local dev.
ALLOW_NO_AUTH = os.getenv("ALLOW_NO_AUTH", "false").lower() == "true"

# API key hashing pepper/secret (required when ALLOW_NO_AUTH is false).
API_KEY_PEPPER = os.getenv("API_KEY_PEPPER", "")

# OpenRouter API key
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Council members - list of OpenRouter model identifiers
COUNCIL_MODELS = [
    "openai/gpt-5.1",
    "google/gemini-3-pro-preview",
    "anthropic/claude-sonnet-4.5",
    "x-ai/grok-4",
]

# Chairman model - synthesizes final response
CHAIRMAN_MODEL = "google/gemini-3-pro-preview"

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# OpenRouter client hardening knobs
OPENROUTER_MAX_CONCURRENCY = int(os.getenv("OPENROUTER_MAX_CONCURRENCY", "6"))
OPENROUTER_MAX_RETRIES = int(os.getenv("OPENROUTER_MAX_RETRIES", "2"))
OPENROUTER_RETRY_BASE_SECONDS = float(os.getenv("OPENROUTER_RETRY_BASE_SECONDS", "0.5"))
OPENROUTER_TIMEOUT_SECONDS = float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "120.0"))
OPENROUTER_AUTH_COOLDOWN_SECONDS = int(os.getenv("OPENROUTER_AUTH_COOLDOWN_SECONDS", "60"))

# Optional per-mode timeout overrides (Phase C.3). If unset, fall back to OPENROUTER_TIMEOUT_SECONDS.
OPENROUTER_TIMEOUT_SECONDS_FAST = os.getenv("OPENROUTER_TIMEOUT_SECONDS_FAST")
OPENROUTER_TIMEOUT_SECONDS_BALANCED = os.getenv("OPENROUTER_TIMEOUT_SECONDS_BALANCED")
OPENROUTER_TIMEOUT_SECONDS_DEEP = os.getenv("OPENROUTER_TIMEOUT_SECONDS_DEEP")

def openrouter_timeout_for_mode(mode: str) -> float | None:
    value: str | None = None
    if mode == "fast":
        value = OPENROUTER_TIMEOUT_SECONDS_FAST
    elif mode == "deep":
        value = OPENROUTER_TIMEOUT_SECONDS_DEEP
    else:
        value = OPENROUTER_TIMEOUT_SECONDS_BALANCED
    if not value:
        return None
    try:
        return float(value)
    except Exception:
        return None

# Caching (Phase B)
COUNCIL_CACHE_ENABLED = os.getenv("COUNCIL_CACHE_ENABLED", "true").lower() == "true"
COUNCIL_CACHE_TTL_SECONDS = os.getenv("COUNCIL_CACHE_TTL_SECONDS")
COUNCIL_CACHE_TTL_SECONDS_INT = int(COUNCIL_CACHE_TTL_SECONDS) if COUNCIL_CACHE_TTL_SECONDS else None

# Model pricing config (JSON mapping, per 1M tokens).
# Example:
# {
#   "openai/gpt-4o": {"prompt_per_1m": 5.0, "completion_per_1m": 15.0}
# }
MODEL_PRICING_JSON = os.getenv("MODEL_PRICING_JSON")
MODEL_PRICING: dict[str, dict[str, float]] = json.loads(MODEL_PRICING_JSON) if MODEL_PRICING_JSON else {}

# Cost/pricebook versioning (Phase C.3)
PRICE_BOOK_VERSION = os.getenv("PRICE_BOOK_VERSION", "v1")

# MCP mode routing (comma-separated lists; env-first).
def _parse_csv_list(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [v.strip() for v in value.split(",")]
    items = [v for v in items if v]
    return items or None


MCP_MODELS_BALANCED = _parse_csv_list(os.getenv("MCP_MODELS_BALANCED"))
MCP_MODELS_FAST = _parse_csv_list(os.getenv("MCP_MODELS_FAST"))
MCP_MODELS_DEEP = _parse_csv_list(os.getenv("MCP_MODELS_DEEP"))

MCP_JUDGES_BALANCED = _parse_csv_list(os.getenv("MCP_JUDGES_BALANCED"))
MCP_JUDGES_FAST = _parse_csv_list(os.getenv("MCP_JUDGES_FAST"))
MCP_JUDGES_DEEP = _parse_csv_list(os.getenv("MCP_JUDGES_DEEP"))

MCP_CHAIR_BALANCED = os.getenv("MCP_CHAIR_BALANCED")
MCP_CHAIR_FAST = os.getenv("MCP_CHAIR_FAST")
MCP_CHAIR_DEEP = os.getenv("MCP_CHAIR_DEEP")

# MCP operational limits (Phase C.2)
MCP_MAX_CONCURRENT_CALLS = int(os.getenv("MCP_MAX_CONCURRENT_CALLS", "4"))
MCP_TOOL_TIMEOUT_SECONDS = float(os.getenv("MCP_TOOL_TIMEOUT_SECONDS", "300"))
MCP_MAX_PROMPT_CHARS = int(os.getenv("MCP_MAX_PROMPT_CHARS", "20000"))
MCP_MAX_TASK_CHARS = int(os.getenv("MCP_MAX_TASK_CHARS", "20000"))
MCP_MAX_REPO_FILES = int(os.getenv("MCP_MAX_REPO_FILES", "25"))
MCP_MAX_REPO_TOTAL_CHARS = int(os.getenv("MCP_MAX_REPO_TOTAL_CHARS", "200000"))
MCP_MAX_PATH_CHARS = int(os.getenv("MCP_MAX_PATH_CHARS", "300"))

# Hosted tools gateway operational limits (Phase D.0)
HTTP_MAX_CONCURRENT_TOOL_CALLS = int(os.getenv("HTTP_MAX_CONCURRENT_TOOL_CALLS", "16"))
HTTP_TOOL_TIMEOUT_SECONDS = float(os.getenv("HTTP_TOOL_TIMEOUT_SECONDS", "300"))

# Pipeline role model routing (Phase C.1): env-first; mode provides defaults.
LEADER_MODEL = os.getenv("LEADER_MODEL")
REVIEWER_MODEL = os.getenv("REVIEWER_MODEL")
SECURITY_MODEL = os.getenv("SECURITY_MODEL")
TEST_WRITER_MODEL = os.getenv("TEST_WRITER_MODEL")
IMPLEMENTER_MODEL = os.getenv("IMPLEMENTER_MODEL")
GATE_MODEL = os.getenv("GATE_MODEL")

# Data directory for conversation storage
DATA_DIR = "data/conversations"
