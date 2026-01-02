import { useEffect, useState } from 'react';
import { ApiError, api } from '../../api';
import { useApiKey } from '../../ApiKeyContext';
import { asArray } from '../../utils/safe';
import './ApiKeysPage.css';

function KeyReveal({ title, plaintextKey, onUseNow, onClose }) {
  if (!plaintextKey) return null;
  return (
    <div className="reveal">
      <div className="reveal-header">
        <div className="reveal-title">{title}</div>
        <button className="reveal-close" onClick={onClose}>
          ×
        </button>
      </div>
      <div className="reveal-body">
        <div className="reveal-warning">Save this key now. It will not be shown again.</div>
        <pre className="reveal-key">{plaintextKey}</pre>
        <div className="reveal-actions">
          <button
            className="btn"
            onClick={() => {
              const p = navigator.clipboard?.writeText?.(plaintextKey);
              if (p && typeof p.catch === 'function') p.catch(() => {});
            }}
          >
            Copy
          </button>
          <button className="btn btn-primary" onClick={onUseNow}>
            Use this key now
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ApiKeysPage({ onAuthRequired }) {
  const { setApiKey } = useApiKey();
  const [loading, setLoading] = useState(false);
  const [keys, setKeys] = useState([]);
  const [error, setError] = useState(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState('');
  const [createRate, setCreateRate] = useState('60');
  const [createCap, setCreateCap] = useState('');

  const [revealedKey, setRevealedKey] = useState(null);
  const [revealedTitle, setRevealedTitle] = useState('');

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listAccountApiKeys();
      if (!Array.isArray(data)) throw new Error('Invalid response: expected API keys array');
      setKeys(asArray(data));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        onAuthRequired?.();
        setError('API key required.');
      } else {
        setError(e?.message || 'Failed to load API keys.');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const createKey = async () => {
    setError(null);
    try {
      const res = await api.createAccountApiKey({
        name: createName || undefined,
        rate_limit_per_min: createRate ? Number(createRate) : undefined,
        monthly_token_cap: createCap ? Number(createCap) : undefined,
      });
      setRevealedTitle('New API key created');
      setRevealedKey(res.plaintext_key);
      setCreateOpen(false);
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        onAuthRequired?.();
        setError('API key required.');
      } else {
        setError(e?.detail || e?.message || 'Failed to create key.');
      }
    }
  };

  const deactivateKey = async (id) => {
    if (!confirm('Deactivate this key? Clients using it will lose access.')) return;
    setError(null);
    try {
      await api.deactivateAccountApiKey(id);
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        onAuthRequired?.();
        setError('API key required.');
      } else {
        setError(e?.detail || e?.message || 'Failed to deactivate key.');
      }
    }
  };

  const rotateKey = async (id) => {
    if (!confirm('Rotate this key? The old key will be deactivated.')) return;
    setError(null);
    try {
      const res = await api.rotateAccountApiKey(id);
      setRevealedTitle('API key rotated');
      setRevealedKey(res.plaintext_key);
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        onAuthRequired?.();
        setError('API key required.');
      } else {
        setError(e?.detail || e?.message || 'Failed to rotate key.');
      }
    }
  };

  return (
    <div className="keys">
      <div className="page-title">API Keys</div>
      <div className="page-subtitle">
        Keys are never stored in the backend in plaintext. Paste a key in Settings or when prompted.
      </div>

      {revealedKey ? (
        <KeyReveal
          title={revealedTitle}
          plaintextKey={revealedKey}
          onUseNow={() => {
            setApiKey(revealedKey);
            setRevealedKey(null);
          }}
          onClose={() => setRevealedKey(null)}
        />
      ) : null}

      <div className="keys-actions">
        <button className="btn btn-primary" onClick={() => setCreateOpen(true)}>
          Create new key
        </button>
        <button className="btn" onClick={load} disabled={loading}>
          Refresh
        </button>
      </div>

      {error ? <div className="error">{String(error)}</div> : null}

      {createOpen ? (
        <div className="panel">
          <div className="panel-title">Create API key</div>
          <div className="panel-grid">
            <label>
              Name
              <input value={createName} onChange={(e) => setCreateName(e.target.value)} placeholder="default" />
            </label>
            <label>
              Rate limit / min
              <input value={createRate} onChange={(e) => setCreateRate(e.target.value)} placeholder="60" />
            </label>
            <label>
              Monthly token cap (optional)
              <input value={createCap} onChange={(e) => setCreateCap(e.target.value)} placeholder="e.g. 200000" />
            </label>
          </div>
          <div className="panel-actions">
            <button className="btn" onClick={() => setCreateOpen(false)}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={createKey}>
              Create
            </button>
          </div>
        </div>
      ) : null}

      <div className="table">
        <div className="row header">
          <div>ID</div>
          <div>Name</div>
          <div>Created</div>
          <div>Last used</div>
          <div>Status</div>
          <div>Actions</div>
        </div>
        {loading ? <div className="row"><div>Loading…</div></div> : null}
        {!loading && keys.length === 0 ? <div className="row"><div>No keys found.</div></div> : null}
        {keys.map((k) => (
          <div className="row" key={k.id}>
            <div className="mono" title={k.id}>
              {k.id.slice(0, 8)}…
            </div>
            <div>{k.name}</div>
            <div>{k.created_at ? new Date(k.created_at).toLocaleString() : '—'}</div>
            <div>{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : '—'}</div>
            <div>
              <span className={`status ${k.is_active ? 'active' : 'inactive'}`}>
                {k.is_active ? 'active' : 'inactive'}
              </span>
            </div>
            <div className="actions">
              <button className="btn btn-small" onClick={() => rotateKey(k.id)} disabled={!k.is_active}>
                Rotate
              </button>
              <button className="btn btn-small" onClick={() => deactivateKey(k.id)} disabled={!k.is_active}>
                Deactivate
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
