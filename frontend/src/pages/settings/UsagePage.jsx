import { useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../../api';
import './UsagePage.css';

function isoDate(d) {
  return d.toISOString().slice(0, 10);
}

export default function UsagePage({ onAuthRequired }) {
  const [fromDate, setFromDate] = useState(isoDate(new Date(Date.now() - 29 * 24 * 60 * 60 * 1000)));
  const [toDate, setToDate] = useState(isoDate(new Date()));
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getAccountUsage(fromDate, toDate);
      setData(res);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        onAuthRequired?.();
        setError('API key required.');
      } else {
        setError(e?.detail || e?.message || 'Failed to load usage.');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const totals = useMemo(() => {
    if (!data) return null;
    return {
      totalTokens: data.total_tokens,
      totalPrompt: data.total_prompt_tokens,
      totalCompletion: data.total_completion_tokens,
      totalCost: data.total_cost_estimated,
    };
  }, [data]);

  return (
    <div className="usage">
      <div className="page-title">Usage</div>
      <div className="filters">
        <label>
          From
          <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
        </label>
        <label>
          To
          <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
        </label>
        <button className="btn btn-primary" onClick={load} disabled={loading}>
          {loading ? 'Loading…' : 'Load'}
        </button>
      </div>

      {error ? <div className="error">{String(error)}</div> : null}

      {totals ? (
        <div className="cards">
          <div className="card">
            <div className="label">Total tokens</div>
            <div className="value">{totals.totalTokens}</div>
          </div>
          <div className="card">
            <div className="label">Prompt tokens</div>
            <div className="value">{totals.totalPrompt}</div>
          </div>
          <div className="card">
            <div className="label">Completion tokens</div>
            <div className="value">{totals.totalCompletion}</div>
          </div>
          <div className="card">
            <div className="label">Cost (estimated)</div>
            <div className="value">${Number(totals.totalCost || 0).toFixed(6)}</div>
          </div>
        </div>
      ) : null}

      {data ? (
        <div className="table">
          <div className="row header">
            <div>Model</div>
            <div>Attempts</div>
            <div>Total tokens</div>
            <div>Cost</div>
          </div>
          {data.by_model?.length ? (
            data.by_model.map((m) => (
              <div className="row" key={m.model}>
                <div className="mono">{m.model}</div>
                <div>{m.attempts}</div>
                <div>{m.total_tokens}</div>
                <div>${Number(m.cost_estimated || 0).toFixed(6)}</div>
              </div>
            ))
          ) : (
            <div className="row">
              <div>No usage in range.</div>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

