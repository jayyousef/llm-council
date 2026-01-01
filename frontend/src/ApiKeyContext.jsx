import { createContext, useContext, useMemo, useState } from 'react';
import { clearStoredApiKey, getStoredApiKey, setStoredApiKey } from './api';

const ApiKeyContext = createContext(null);

export function ApiKeyProvider({ children }) {
  const [apiKey, setApiKeyState] = useState(getStoredApiKey());

  const value = useMemo(() => {
    return {
      apiKey,
      hasKey: Boolean(apiKey),
      setApiKey: (key) => {
        const trimmed = (key || '').trim();
        setStoredApiKey(trimmed);
        setApiKeyState(trimmed);
      },
      clearApiKey: () => {
        clearStoredApiKey();
        setApiKeyState('');
      },
    };
  }, [apiKey]);

  return <ApiKeyContext.Provider value={value}>{children}</ApiKeyContext.Provider>;
}

export function useApiKey() {
  const ctx = useContext(ApiKeyContext);
  if (!ctx) throw new Error('useApiKey must be used within ApiKeyProvider');
  return ctx;
}

