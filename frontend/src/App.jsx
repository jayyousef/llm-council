import './App.css';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { useState } from 'react';

import { ApiKeyProvider } from './ApiKeyContext';
import ApiKeyModal from './components/ApiKeyModal';
import ChatPage from './pages/ChatPage';
import SettingsLayout from './pages/settings/SettingsLayout';
import ApiKeysPage from './pages/settings/ApiKeysPage';
import UsagePage from './pages/settings/UsagePage';
import LimitsPage from './pages/settings/LimitsPage';

function App() {
  const [keyModalOpen, setKeyModalOpen] = useState(false);

  return (
    <ApiKeyProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<ChatPage onAuthRequired={() => setKeyModalOpen(true)} />} />
          <Route path="/settings" element={<SettingsLayout onOpenKeyModal={() => setKeyModalOpen(true)} />}>
            <Route index element={<Navigate to="/settings/api-keys" replace />} />
            <Route path="api-keys" element={<ApiKeysPage onAuthRequired={() => setKeyModalOpen(true)} />} />
            <Route path="usage" element={<UsagePage onAuthRequired={() => setKeyModalOpen(true)} />} />
            <Route path="limits" element={<LimitsPage onAuthRequired={() => setKeyModalOpen(true)} />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
      <ApiKeyModal open={keyModalOpen} onClose={() => setKeyModalOpen(false)} />
    </ApiKeyProvider>
  );
}

export default App;
