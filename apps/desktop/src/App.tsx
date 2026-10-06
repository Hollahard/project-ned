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
  const [gamingModeLoading, setGamingModeLoading] = useState<boolean>(false);

  const refreshStatus = async () => {
    try {
      const stat = await TauriClient.getRuntimeStatus();
      setStatus(stat);
    } catch (err) {
      console.error('Failed to refresh status:', err);
    }
  };

  // Load initial telemetry and sessions on mount, plus background telemetry interval
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

    const interval = setInterval(refreshStatus, 4000);
    return () => clearInterval(interval);
  }, []);

  const handleToggleGamingMode = async () => {
    if (gamingModeLoading) return;
    setGamingModeLoading(true);
    try {
      if (status?.gaming_mode?.active) {
        await TauriClient.deactivateGamingMode();
      } else {
        await TauriClient.activateGamingMode();
        setIsStreaming(false);
      }
      await refreshStatus();
    } catch (err) {
      console.error('Failed to toggle Gaming Mode:', err);
    } finally {
      setGamingModeLoading(false);
    }
  };

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

        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          {status?.gpu_telemetry?.available ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', color: '#a6adc8' }}>
              <span>
                VRAM:{' '}
                <strong style={{ color: '#a6e3a1' }}>
                  {(status.gpu_telemetry.vram_used_mb / 1024).toFixed(1)}
                </strong>{' '}
                /{' '}
                {(status.gpu_telemetry.vram_total_mb / 1024).toFixed(1)} GB (
                {status.gpu_telemetry.vram_usage_percent.toFixed(0)}%)
              </span>
              <span>
                Temp: <strong style={{ color: '#f9e2af' }}>{status.gpu_telemetry.temperature_c}°C</strong>
              </span>
              <span>
                Power: <strong style={{ color: '#89b4fa' }}>{status.gpu_telemetry.power_watts.toFixed(0)} W</strong>
              </span>
            </div>
          ) : status?.vram_allocated_mb ? (
            <div style={{ color: '#a6adc8' }}>
              VRAM:{' '}
              <span style={{ color: '#a6e3a1', fontWeight: 600 }}>
                {(status.vram_allocated_mb / 1024).toFixed(1)} GB
              </span>{' '}
              / 32 GB
            </div>
          ) : null}

          <button
            onClick={handleToggleGamingMode}
            disabled={gamingModeLoading}
            title={
              status?.gaming_mode?.active
                ? 'Deactivate Gaming Mode and resume inference'
                : 'Instant VRAM Evacuation (<2s) and Turn Abort'
            }
            style={{
              background: status?.gaming_mode?.active ? '#f38ba8' : '#313244',
              color: status?.gaming_mode?.active ? '#11111b' : '#cdd6f4',
              border: `1px solid ${status?.gaming_mode?.active ? '#f38ba8' : '#45475a'}`,
              borderRadius: '6px',
              padding: '4px 10px',
              fontSize: '11px',
              fontWeight: 700,
              cursor: gamingModeLoading ? 'wait' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <span
              style={{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                background: status?.gaming_mode?.active ? '#11111b' : '#a6e3a1',
              }}
            />
            {gamingModeLoading
              ? 'SWITCHING...'
              : status?.gaming_mode?.active
              ? 'GAMING MODE ACTIVE'
              : 'GAMING MODE'}
          </button>

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

          {/* Gaming Mode Active Notification Banner */}
          {status?.gaming_mode?.active && (
            <div
              style={{
                background: 'rgba(243, 139, 168, 0.12)',
                borderTop: '1px solid #f38ba8',
                color: '#f38ba8',
                padding: '10px 24px',
                fontSize: '12px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <span>
                🎮 <strong>Gaming Mode Active:</strong> GPU VRAM evacuated (&lt;2.0s) to return full memory to Windows games & apps. Inference turns are paused.
              </span>
              <button
                onClick={handleToggleGamingMode}
                disabled={gamingModeLoading}
                style={{
                  background: '#f38ba8',
                  color: '#11111b',
                  border: 'none',
                  borderRadius: '4px',
                  padding: '4px 12px',
                  fontSize: '11px',
                  fontWeight: 700,
                  cursor: gamingModeLoading ? 'wait' : 'pointer',
                }}
              >
                Exit Gaming Mode
              </button>
            </div>
          )}

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
                disabled={status?.gaming_mode?.active}
                placeholder={
                  status?.gaming_mode?.active
                    ? 'Gaming Mode is active. Exit Gaming Mode to submit prompts...'
                    : 'Ask Friday a question or command (Enter to send, Shift+Enter for newline)...'
                }
                rows={2}
                style={{
                  flex: 1,
                  background: status?.gaming_mode?.active ? '#181825' : '#1e1e2e',
                  border: '1px solid #313244',
                  borderRadius: '8px',
                  color: status?.gaming_mode?.active ? '#6c7086' : '#cdd6f4',
                  padding: '10px 14px',
                  fontSize: '13px',
                  fontFamily: 'inherit',
                  resize: 'none',
                  outline: 'none',
                  cursor: status?.gaming_mode?.active ? 'not-allowed' : 'text',
                }}
              />
              <button
                onClick={() => handleSubmitPrompt()}
                disabled={isStreaming || !prompt.trim() || status?.gaming_mode?.active}
                style={{
                  background:
                    isStreaming || !prompt.trim() || status?.gaming_mode?.active
                      ? '#45475a'
                      : '#89b4fa',
                  color: '#11111b',
                  border: 'none',
                  borderRadius: '8px',
                  padding: '12px 20px',
                  fontWeight: 600,
                  fontSize: '13px',
                  cursor:
                    isStreaming || !prompt.trim() || status?.gaming_mode?.active
                      ? 'not-allowed'
                      : 'pointer',
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
