import React, { useState, useEffect } from 'react';
import { Session, ChatMessage, RuntimeStatus, ModelProfile } from './types';
import { TauriClient } from './services/tauriClient';
import { SessionList } from './components/SessionList';
import { ChatView } from './components/ChatView';

export const App: React.FC = () => {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [prompt, setPrompt] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [streamingToken, setStreamingToken] = useState<string>('');
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [models, setModels] = useState<ModelProfile[]>([]);

  // Load initial telemetry and sessions on mount
  useEffect(() => {
    async function loadInitial() {
      try {
        const [stat, sess, mods] = await Promise.all([
          TauriClient.getRuntimeStatus(),
          TauriClient.listSessions(),
          TauriClient.listModels(),
        ]);
        setStatus(stat);
        setSessions(sess);
        setModels(mods);
        if (sess.length > 0 && !activeSessionId) {
          setActiveSessionId(sess[0].id);
        }
      } catch (err) {
        console.error('Failed to load initial desktop state:', err);
      }
    }
    loadInitial();
  }, []);

  const handleCreateSession = async () => {
    try {
      const newSession = await TauriClient.createSession(`Session ${sessions.length + 1}`);
      setSessions([newSession, ...sessions]);
      setActiveSessionId(newSession.id);
      setMessages([]);
    } catch (err) {
      console.error('Failed to create session:', err);
    }
  };

  const handleCancelTurn = async () => {
    if (activeSessionId) {
      try {
        await TauriClient.cancelTurn(activeSessionId);
        setIsStreaming(false);
      } catch (err) {
        console.error('Failed to cancel turn:', err);
      }
    }
  };

  const handleSubmitPrompt = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!prompt.trim() || isStreaming || !activeSessionId) return;

    const userMsg: ChatMessage = {
      role: 'user',
      content: prompt.trim(),
      created_at: Date.now() / 1000,
    };

    setMessages((prev) => [...prev, userMsg]);
    setPrompt('');
    setIsStreaming(true);
    setStreamingToken('');

    // In a live turn, token deltas arrive over WebSocket.
    // Here we handle the local/mock response buffer gracefully:
    setTimeout(() => {
      setStreamingToken('Received and verified prompt on private RTX 5090 sidecar.');
      setIsStreaming(false);
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: 'Received and verified prompt on private RTX 5090 sidecar.',
          created_at: Date.now() / 1000,
        },
      ]);
      setStreamingToken('');
    }, 400);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmitPrompt();
    }
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        width: '100vw',
        background: '#11111b',
        color: '#cdd6f4',
        fontFamily: 'Segoe UI, system-ui, sans-serif',
        overflow: 'hidden',
      }}
    >
      {/* Top Telemetry Bar */}
      <header
        style={{
          height: '44px',
          background: '#181825',
          borderBottom: '1px solid #313244',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 16px',
          fontSize: '12px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontWeight: 700, color: '#89b4fa' }}>PROJECT FRIDAY</span>
          <span style={{ color: '#6c7086' }}>|</span>
          <span style={{ color: '#a6adc8' }}>
            Model: <strong style={{ color: '#cdd6f4' }}>{status?.active_model || 'None'}</strong>
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          {status?.vram_allocated_mb && (
            <div style={{ color: '#a6adc8' }}>
              VRAM:{' '}
              <span style={{ color: '#a6e3a1', fontWeight: 600 }}>
                {(status.vram_allocated_mb / 1024).toFixed(1)} GB
              </span>{' '}
              / 32 GB
            </div>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                background: status?.core_status === 'ok' ? '#a6e3a1' : '#f38ba8',
              }}
            />
            <span style={{ color: '#a6adc8' }}>Supervisor Ready</span>
          </div>
        </div>
      </header>

      {/* Main Workspace Body */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <SessionList
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={setActiveSessionId}
          onCreateSession={handleCreateSession}
        />

        <main
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            background: '#11111b',
            overflow: 'hidden',
          }}
        >
          <ChatView
            messages={messages}
            streamingToken={streamingToken}
            isStreaming={isStreaming}
            onCancelTurn={handleCancelTurn}
          />

          {/* Prompt Input Form */}
          <footer
            style={{
              padding: '16px 24px',
              borderTop: '1px solid #313244',
              background: '#181825',
            }}
          >
            <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask Friday a question or command (Enter to send, Shift+Enter for newline)..."
                rows={2}
                style={{
                  flex: 1,
                  background: '#1e1e2e',
                  border: '1px solid #313244',
                  borderRadius: '8px',
                  color: '#cdd6f4',
                  padding: '10px 14px',
                  fontSize: '13px',
                  fontFamily: 'inherit',
                  resize: 'none',
                  outline: 'none',
                }}
              />
              <button
                onClick={() => handleSubmitPrompt()}
                disabled={isStreaming || !prompt.trim()}
                style={{
                  background: isStreaming || !prompt.trim() ? '#45475a' : '#89b4fa',
                  color: '#11111b',
                  border: 'none',
                  borderRadius: '8px',
                  padding: '12px 20px',
                  fontWeight: 600,
                  fontSize: '13px',
                  cursor: isStreaming || !prompt.trim() ? 'not-allowed' : 'pointer',
                  transition: 'background 0.2s ease',
                }}
              >
                Send
              </button>
            </div>
          </footer>
        </main>
      </div>
    </div>
  );
};
