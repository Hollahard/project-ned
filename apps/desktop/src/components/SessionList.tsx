import React from 'react';
import { Session } from '../types';

interface SessionListProps {
  sessions: Session[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onCreateSession: () => void;
}

export const SessionList: React.FC<SessionListProps> = ({
  sessions,
  activeSessionId,
  onSelectSession,
  onCreateSession,
}) => {
  return (
    <aside
      style={{
        width: '260px',
        background: '#181825',
        borderRight: '1px solid #313244',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
      }}
    >
      <div
        style={{
          padding: '16px',
          borderBottom: '1px solid #313244',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <span style={{ fontWeight: 600, fontSize: '14px', color: '#cdd6f4' }}>Sessions</span>
        <button
          onClick={onCreateSession}
          style={{
            background: '#89b4fa',
            color: '#11111b',
            border: 'none',
            borderRadius: '4px',
            padding: '4px 10px',
            fontSize: '12px',
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          + New
        </button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
        {sessions.map((s) => {
          const isActive = s.id === activeSessionId;
          return (
            <div
              key={s.id}
              onClick={() => onSelectSession(s.id)}
              style={{
                padding: '10px 12px',
                borderRadius: '6px',
                marginBottom: '4px',
                cursor: 'pointer',
                background: isActive ? '#313244' : 'transparent',
                color: isActive ? '#f5e0dc' : '#a6adc8',
                transition: 'background 0.15s ease',
              }}
            >
              <div
                style={{
                  fontSize: '13px',
                  fontWeight: isActive ? 600 : 400,
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {s.title}
              </div>
              <div style={{ fontSize: '11px', color: '#6c7086', marginTop: '4px' }}>
                {new Date(s.updated_at * 1000).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
};
