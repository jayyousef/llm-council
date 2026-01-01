import { useEffect, useState } from 'react';
import { useApiKey } from '../ApiKeyContext';
import './ApiKeyModal.css';

export default function ApiKeyModal({ open, onClose, title = 'Enter API Key' }) {
  const { apiKey, setApiKey, clearApiKey } = useApiKey();
  const [value, setValue] = useState(apiKey || '');

  useEffect(() => {
    if (open) setValue(apiKey || '');
  }, [open, apiKey]);

  if (!open) return null;

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal-card">
        <div className="modal-header">
          <div className="modal-title">{title}</div>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="modal-body">
          <p className="modal-hint">
            Paste your API key once. It’s stored locally in your browser and sent as the{' '}
            <code>X-API-Key</code> header.
          </p>
          <textarea
            className="modal-input"
            placeholder="lc_..."
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={3}
          />
        </div>

        <div className="modal-actions">
          <button
            className="btn-secondary"
            onClick={() => {
              clearApiKey();
              setValue('');
            }}
          >
            Clear
          </button>
          <button
            className="btn-primary"
            onClick={() => {
              setApiKey(value);
              onClose();
            }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

