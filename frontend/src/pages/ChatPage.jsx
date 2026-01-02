import { useEffect, useState } from 'react';
import Sidebar from '../components/Sidebar';
import ChatInterface from '../components/ChatInterface';
import { ApiError, api } from '../api';
import { asArray, asString } from '../utils/safe';
import './ChatPage.css';

function normalizeConversation(conversation) {
  if (!conversation || typeof conversation !== 'object') return null;
  return {
    ...conversation,
    title: asString(conversation.title, ''),
    messages: asArray(conversation.messages),
  };
}

export default function ChatPage({ onAuthRequired }) {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isCreatingConversation, setIsCreatingConversation] = useState(false);
  const [banner, setBanner] = useState(null);

  useEffect(() => {
    loadConversations();
  }, []);

  useEffect(() => {
    if (currentConversationId) {
      if (currentConversation?.id !== currentConversationId) {
        loadConversation(currentConversationId);
      }
    }
  }, [currentConversationId, currentConversation?.id]);

  const handleApiError = (error) => {
    if (error instanceof ApiError && error.status === 0) {
      setBanner('Network error: could not reach the API.');
      return true;
    }
    if (error instanceof ApiError && error.status === 401) {
      setBanner('API key required (401).');
      onAuthRequired?.();
      return true;
    }
    if (error instanceof ApiError && error.status === 402 && error.detail === 'quota_exceeded') {
      setBanner('Quota exceeded (402).');
      return true;
    }
    return false;
  };

  const showError = (action, error) => {
    if (error instanceof ApiError) {
      console.error(`${action} failed`, { status: error.status, detail: error.detail, error });
      if (handleApiError(error)) return;
      setBanner(`${action} failed (${error.status}). ${error.detail || 'Please try again.'}`);
      return;
    }
    console.error(`${action} failed`, error);
    setBanner(`${action} failed. ${error?.message || 'Please try again.'}`);
  };

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations();
      if (!Array.isArray(convs)) throw new Error('Invalid response: expected conversations array');
      setConversations(convs);
      setBanner(null);
    } catch (error) {
      showError('Loading conversations', error);
    }
  };

  const loadConversation = async (id) => {
    try {
      const conv = await api.getConversation(id);
      const normalized = normalizeConversation(conv);
      if (!normalized) throw new Error('Invalid response: expected conversation object');
      setCurrentConversation(normalized);
      setBanner(null);
    } catch (error) {
      showError('Loading conversation', error);
    }
  };

  const handleNewConversation = async () => {
    if (isCreatingConversation) return;
    setIsCreatingConversation(true);
    try {
      const newConv = await api.createConversation();
      const normalized = normalizeConversation(newConv);
      if (!normalized) throw new Error('Invalid response: expected conversation object');
      setConversations((prev) => [
        {
          id: normalized.id,
          created_at: normalized.created_at,
          title: normalized.title,
          message_count: 0,
        },
        ...asArray(prev),
      ]);
      setCurrentConversationId(normalized.id);
      setCurrentConversation(normalized);
      setBanner(null);
    } catch (error) {
      showError('Creating conversation', error);
    } finally {
      setIsCreatingConversation(false);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
  };

  const handleSendMessage = async (content) => {
    if (!currentConversationId) return;

    setIsLoading(true);
    try {
      const userMessage = { role: 'user', content };
      setCurrentConversation((prev) => {
        const prevMessages = asArray(prev?.messages);
        return { ...(prev || {}), messages: [...prevMessages, userMessage] };
      });

      const assistantMessage = {
        role: 'assistant',
        stage1: null,
        stage2: null,
        stage3: null,
        metadata: null,
        loading: {
          stage1: false,
          stage2: false,
          stage3: false,
        },
      };

      setCurrentConversation((prev) => {
        const prevMessages = asArray(prev?.messages);
        return { ...(prev || {}), messages: [...prevMessages, assistantMessage] };
      });

      await api.sendMessageStream(currentConversationId, content, (eventType, event) => {
        switch (eventType) {
          case 'stage1_start':
            setCurrentConversation((prev) => {
              const messages = [...asArray(prev?.messages)];
              const lastMsg = messages[messages.length - 1];
              if (!lastMsg) return prev;
              lastMsg.loading.stage1 = true;
              return { ...prev, messages };
            });
            break;
          case 'stage1_complete':
            setCurrentConversation((prev) => {
              const messages = [...asArray(prev?.messages)];
              const lastMsg = messages[messages.length - 1];
              if (!lastMsg) return prev;
              lastMsg.stage1 = event.data;
              lastMsg.loading.stage1 = false;
              return { ...prev, messages };
            });
            break;
          case 'stage2_start':
            setCurrentConversation((prev) => {
              const messages = [...asArray(prev?.messages)];
              const lastMsg = messages[messages.length - 1];
              if (!lastMsg) return prev;
              lastMsg.loading.stage2 = true;
              return { ...prev, messages };
            });
            break;
          case 'stage2_complete':
            setCurrentConversation((prev) => {
              const messages = [...asArray(prev?.messages)];
              const lastMsg = messages[messages.length - 1];
              if (!lastMsg) return prev;
              lastMsg.stage2 = event.data;
              lastMsg.metadata = event.metadata;
              lastMsg.loading.stage2 = false;
              return { ...prev, messages };
            });
            break;
          case 'stage3_start':
            setCurrentConversation((prev) => {
              const messages = [...asArray(prev?.messages)];
              const lastMsg = messages[messages.length - 1];
              if (!lastMsg) return prev;
              lastMsg.loading.stage3 = true;
              return { ...prev, messages };
            });
            break;
          case 'stage3_complete':
            setCurrentConversation((prev) => {
              const messages = [...asArray(prev?.messages)];
              const lastMsg = messages[messages.length - 1];
              if (!lastMsg) return prev;
              lastMsg.stage3 = event.data;
              lastMsg.loading.stage3 = false;
              return { ...prev, messages };
            });
            break;
          case 'title_complete':
            loadConversations();
            break;
          case 'complete':
            loadConversations();
            setIsLoading(false);
            break;
          case 'error':
            console.error('Stream error:', event.message);
            setBanner(`Stream error. ${event.message || 'Please try again.'}`);
            setIsLoading(false);
            break;
          default:
            break;
        }
      });
      setBanner(null);
    } catch (error) {
      showError('Sending message', error);
      setCurrentConversation((prev) => ({
        ...prev,
        messages: asArray(prev?.messages).slice(0, -2),
      }));
      setIsLoading(false);
    }
  };

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        isCreatingConversation={isCreatingConversation}
      />
      <div className="chat-shell">
        {banner ? <div className="banner">{banner}</div> : null}
        <ChatInterface conversation={currentConversation} onSendMessage={handleSendMessage} isLoading={isLoading} />
      </div>
    </div>
  );
}
