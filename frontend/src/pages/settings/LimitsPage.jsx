import { useEffect, useState } from 'react';
import { ApiError, api } from '../../api';
import './LimitsPage.css';

export default function LimitsPage({ onAuthRequired }) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getAccountLimits();
      setData(res);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        onAuthRequired?.();
        setError('API key required.');
      } else {
        setError(e?.detail || e?.message || 'Failed to load limits.');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="limits">
      <div className="page-title">Limits</div>
      <button className="btn btn-primary" onClick={load} disabled={loading}>
        {loading ? 'Loading…' : 'Refresh'}
      </button>
      {error ? <div className="error">{String(error)}</div> : null}

      {data ? (
        <div className="panel">
          <div className="row">
            <div className="label">Month start (UTC)</div>
            <div className="value">{data.month_start}</div>
          </div>
          <div className="row">
            <div className="label">Monthly token cap</div>
            <div className="value">{data.monthly_token_cap ?? '—'}</div>
          </div>
          <div className="row">
            <div className="label">Used this month</div>
            <div className="value">{data.tokens_used_this_month}</div>
          </div>
          <div className="row">
            <div className="label">Remaining</div>
            <div className="value">{data.tokens_remaining ?? '—'}</div>
          </div>
          <div className="row">
            <div className="label">Quota exceeded</div>
            <div className="value">
              <span className={`pill ${data.quota_exceeded ? 'pill-bad' : 'pill-ok'}`}>
                {data.quota_exceeded ? 'YES' : 'NO'}
              </span>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

