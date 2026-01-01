function normalizeApiBaseUrl(value) {
  if (typeof value !== 'string') return '';
  const trimmed = value.trim();
  if (!trimmed) return '';
  return trimmed.endsWith('/') ? trimmed.slice(0, -1) : trimmed;
}

export function getApiBaseUrl() {
  const runtime = globalThis?.__LLM_COUNCIL_CONFIG__?.API_BASE_URL;
  const vite = import.meta.env.VITE_API_BASE_URL;

  const candidate = normalizeApiBaseUrl(runtime || vite);
  if (candidate) return candidate;

  if (import.meta.env.DEV) return 'http://localhost:8001';

  throw new Error(
    'Missing API base URL. Set VITE_API_BASE_URL (Railway runtime env) or provide /config.js.'
  );
}

