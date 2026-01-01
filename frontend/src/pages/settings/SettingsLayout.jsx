import { Link, NavLink, Outlet } from 'react-router-dom';
import { useApiKey } from '../../ApiKeyContext';
import './SettingsLayout.css';

export default function SettingsLayout({ onOpenKeyModal }) {
  const { hasKey, clearApiKey } = useApiKey();

  return (
    <div className="settings">
      <div className="settings-topbar">
        <Link className="settings-back" to="/">
          ← Back to chat
        </Link>
        <div className="settings-key">
          <span className={`pill ${hasKey ? 'pill-ok' : 'pill-warn'}`}>
            {hasKey ? 'API key set' : 'No API key'}
          </span>
          <button className="btn" onClick={onOpenKeyModal}>
            Paste key
          </button>
          <button className="btn btn-secondary" onClick={clearApiKey}>
            Clear key
          </button>
        </div>
      </div>

      <div className="settings-body">
        <div className="settings-nav">
          <NavLink to="/settings/api-keys" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            API Keys
          </NavLink>
          <NavLink to="/settings/usage" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            Usage
          </NavLink>
          <NavLink to="/settings/limits" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            Limits
          </NavLink>
        </div>
        <div className="settings-content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}

