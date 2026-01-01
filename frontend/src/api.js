/**
 * API client for the LLM Council backend.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001';
const API_KEY_STORAGE = 'llm_council_api_key';

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export function getStoredApiKey() {
  try {
    return localStorage.getItem(API_KEY_STORAGE) || '';
  } catch {
    return '';
  }
}

export function setStoredApiKey(key) {
  localStorage.setItem(API_KEY_STORAGE, key);
}

export function clearStoredApiKey() {
  localStorage.removeItem(API_KEY_STORAGE);
}

function buildHeaders(extra = {}) {
  const headers = { ...extra };
  const apiKey = getStoredApiKey();
  if (apiKey) headers['X-API-Key'] = apiKey;
  return headers;
}

async function requestJson(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: buildHeaders(options.headers || {}),
  });

  let body = null;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    body = await response.json().catch(() => null);
  }

  if (!response.ok) {
    const detail = body?.detail || body?.message || null;
    throw new ApiError(`Request failed: ${path}`, response.status, detail);
  }
  return body;
}

export const api = {
  /**
   * List all conversations.
   */
  async listConversations() {
    return requestJson('/api/conversations');
  },

  /**
   * Create a new conversation.
   */
  async createConversation() {
    return requestJson('/api/conversations', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({}),
    });
  },

  /**
   * Get a specific conversation.
   */
  async getConversation(conversationId) {
    return requestJson(`/api/conversations/${conversationId}`);
  },

  /**
   * Send a message in a conversation.
   */
  async sendMessage(conversationId, content) {
    return requestJson(`/api/conversations/${conversationId}/message`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ content }),
    });
  },

  /**
   * Send a message and receive streaming updates.
   * @param {string} conversationId - The conversation ID
   * @param {string} content - The message content
   * @param {function} onEvent - Callback function for each event: (eventType, data) => void
   * @returns {Promise<void>}
   */
  async sendMessageStream(conversationId, content, onEvent) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message/stream`,
      {
        method: 'POST',
        headers: buildHeaders({
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ content }),
      }
    );

    if (!response.ok) {
      let detail = null;
      try {
        const body = await response.json();
        detail = body?.detail || body?.message || null;
      } catch {
        detail = null;
      }
      throw new ApiError('Failed to send message', response.status, detail);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    let buffer = '';
    let eventType = null;
    let dataLines = [];

    function dispatchEvent() {
      if (!dataLines.length) return;

      const dataStr = dataLines.join('\n');
      dataLines = [];

      // Your backend sends JSON in data:
      try {
        const event = JSON.parse(dataStr);
        onEvent(event.type, event);
      } catch (e) {
        console.error('Failed to parse SSE event payload:', e, dataStr);
      }

      eventType = null;
    }

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE events are separated by a blank line
      let sepIndex;
      while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
        const rawEvent = buffer.slice(0, sepIndex);
        buffer = buffer.slice(sepIndex + 2);

        const lines = rawEvent.split('\n');
        for (const line of lines) {
          if (!line || line.startsWith(':')) continue; // comments / keep-alives

          if (line.startsWith('event:')) {
            eventType = line.slice('event:'.length).trim();
          } else if (line.startsWith('data:')) {
            dataLines.push(line.slice('data:'.length).trimStart());
          }
          // ignore id:/retry: for now
        }

        dispatchEvent();
      }
    }

    // Flush any trailing complete event if it exists (rare)
    dispatchEvent();  
    },
    
  async listAccountApiKeys() {
    return requestJson('/api/account/api-keys');
  },

  async createAccountApiKey({ name, rate_limit_per_min, monthly_token_cap }) {
    return requestJson('/api/account/api-keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, rate_limit_per_min, monthly_token_cap }),
    });
  },

  async deactivateAccountApiKey(apiKeyId) {
    return requestJson(`/api/account/api-keys/${apiKeyId}/deactivate`, {
      method: 'POST',
    });
  },

  async rotateAccountApiKey(apiKeyId) {
    return requestJson(`/api/account/api-keys/${apiKeyId}/rotate`, {
      method: 'POST',
    });
  },

  async getAccountUsage(fromDate, toDate) {
    const params = new URLSearchParams({ from: fromDate, to: toDate });
    return requestJson(`/api/account/usage?${params.toString()}`);
  },

  async getAccountLimits() {
    return requestJson('/api/account/limits');
  },
};
