# LLM Council

![llmcouncil](header.jpg)

The idea of this repo is that instead of asking a question to your favorite LLM provider (e.g. OpenAI GPT 5.1, Google Gemini 3.0 Pro, Anthropic Claude Sonnet 4.5, xAI Grok 4, eg.c), you can group them into your "LLM Council". This repo is a simple, local web app that essentially looks like ChatGPT except it uses OpenRouter to send your query to multiple LLMs, it then asks them to review and rank each other's work, and finally a Chairman LLM produces the final response.

In a bit more detail, here is what happens when you submit a query:

1. **Stage 1: First opinions**. The user query is given to all LLMs individually, and the responses are collected. The individual responses are shown in a "tab view", so that the user can inspect them all one by one.
2. **Stage 2: Review**. Each individual LLM is given the responses of the other LLMs. Under the hood, the LLM identities are anonymized so that the LLM can't play favorites when judging their outputs. The LLM is asked to rank them in accuracy and insight.
3. **Stage 3: Final response**. The designated Chairman of the LLM Council takes all of the model's responses and compiles them into a single final answer that is presented to the user.

## Vibe Code Alert

This project was 99% vibe coded as a fun Saturday hack because I wanted to explore and evaluate a number of LLMs side by side in the process of [reading books together with LLMs](https://x.com/karpathy/status/1990577951671509438). It's nice and useful to see multiple responses side by side, and also the cross-opinions of all LLMs on each other's outputs. I'm not going to support it in any way, it's provided here as is for other people's inspiration and I don't intend to improve it. Code is ephemeral now and libraries are over, ask your LLM to change it in whatever way you like.

## Setup

### 1. Install Dependencies

The project uses [uv](https://docs.astral.sh/uv/) for project management.

**Backend:**
```bash
uv sync
```

**Frontend:**
```bash
cd frontend
npm install
cd ..
```

### 2. Configure API Key

Create a `.env` file in the project root:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

Get your API key at [openrouter.ai](https://openrouter.ai/). Make sure to purchase the credits you need, or sign up for automatic top up.

### 3. Configure Models (Optional)

Edit `backend/config.py` to customize the council:

```python
COUNCIL_MODELS = [
    "openai/gpt-5.1",
    "google/gemini-3-pro-preview",
    "anthropic/claude-sonnet-4.5",
    "x-ai/grok-4",
]

CHAIRMAN_MODEL = "google/gemini-3-pro-preview"
```

## Running the Application

### Option 1: Docker Compose (recommended)

Set `OPENROUTER_API_KEY` in your environment (or a `.env` file):

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
docker compose up --build
```

Then open http://localhost:5173.

By default, local compose runs with `ALLOW_NO_AUTH=true` so you can use the UI without an API key header.

**Option 1: Use the start script**
```bash
./start.sh
```

**Option 2: Run manually**

Terminal 1 (Backend):
```bash
uv run python -m backend.src.app.main
```

Terminal 2 (Frontend):
```bash
cd frontend
npm run dev
```

Then open http://localhost:5173 in your browser.

## Tech Stack

- **Backend:** FastAPI (Python 3.10+), async httpx, OpenRouter API
- **Frontend:** React + Vite, react-markdown for rendering
- **Storage:** Postgres (SQLModel + Alembic)
- **Package Management:** uv for Python, npm for JavaScript

### Alternate backend run command

```bash
uvicorn backend.src.app.main:app --reload --port 8001
```

## Customer UI (Key-only)

The web UI is **key-only** auth for now (no login). You paste an API key once and it is stored in your browser `localStorage` and sent on requests as `X-API-Key`.

Settings pages:
- `http://localhost:5173/settings/api-keys`
- `http://localhost:5173/settings/usage`
- `http://localhost:5173/settings/limits`

Backend endpoints used by the Settings UI:
- `GET /api/account/api-keys`
- `POST /api/account/api-keys`
- `POST /api/account/api-keys/{api_key_id}/deactivate`
- `POST /api/account/api-keys/{api_key_id}/rotate`
- `GET /api/account/usage?from=YYYY-MM-DD&to=YYYY-MM-DD`
- `GET /api/account/limits`

### API keys (production mode)

When `ALLOW_NO_AUTH` is not set to `true`, the backend requires an `X-API-Key` header.

- Create a key (prints plaintext once): `python3 -m backend.src.scripts.create_api_key`
- Deactivate a key: `python3 -m backend.src.scripts.deactivate_api_key <api_key_id>`
- Rotate a key (optionally deactivating an old one): `python3 -m backend.src.scripts.rotate_api_key --deactivate-id <api_key_id>`
- Set a pepper for hashing: `export API_KEY_PEPPER=...`

If `monthly_token_cap` is set for a key, requests that start a run will be rejected with HTTP `402` `quota_exceeded` once the current UTC calendar month cap is exceeded.

## MCP (Local, stdio)

This repo includes an MCP server that runs over **stdio** for locally spawned IDE/tool sessions.
It is not a hosted multi-client network service and is not directly usable from a remote deployment (e.g. Railway)
because MCP stdio requires a local process connection. Use the HTTP API for hosted/multi-client access.
In the future, an HTTP gateway could expose MCP tools remotely, but that is not implemented here.

Run locally:

```bash
export DATABASE_URL=postgresql+asyncpg://...
export MCP_API_KEY=...  # optional if ALLOW_NO_AUTH=true
python3 -m backend.src.mcp.server
```

Available tools:
- `council.ask`: run the 3-stage council and return a final answer (strict JSON)
- `council.pipeline`: run a bounded software-factory pipeline and return a Codex prompt (strict JSON)

## Hosted Tools Gateway (HTTP)

For hosted / multi-client usage over the internet, call the HTTP tools gateway endpoints (authenticated via `X-API-Key`):

- `POST /api/tools/council.ask`
- `POST /api/tools/council.pipeline`

These endpoints accept the same JSON inputs as the MCP tools (except `api_key` is not accepted in the request body) and return the same strict JSON outputs.

Example:

```bash
curl -sS http://localhost:8001/api/tools/council.ask \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: lc_***' \
  -d '{"prompt":"Hello","mode":"balanced"}'
```
