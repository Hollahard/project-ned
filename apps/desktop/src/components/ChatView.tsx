import React, { useRef, useEffect } from 'react';
import { ChatMessage } from '../types';
import { MarkdownRenderer } from './MarkdownRenderer';

interface ChatViewProps {
  messages: ChatMessage[];
  streamingToken: string;
  isStreaming: boolean;
  onCancelTurn: () => void;
}

export const ChatView: React.FC<ChatViewProps> = ({
  messages,
  streamingToken,
  isStreaming,
  onCancelTurn,
}) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingToken]);

  return (
    <div
      style={{
        flex: 1,
        overflowY: 'auto',
        padding: '24px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
      }}
    >
      {messages.length === 0 && !isStreaming && (
        <div
          style={{
            margin: 'auto',
            textAlign: 'center',
            color: '#6c7086',
            fontSize: '14px',
          }}
        >
          <div style={{ fontSize: '24px', marginBottom: '8px' }}>🤖</div>
          <div>Project Friday Desktop</div>
          <div style={{ fontSize: '12px', marginTop: '4px' }}>
            NVIDIA RTX 5090 Blackwell Private Inference
          </div>
        </div>
      )}

      {messages.map((msg, index) => {
        const isUser = msg.role === 'user';
        return (
          <div
            key={index}
            style={{
              alignSelf: isUser ? 'flex-end' : 'flex-start',
              maxWidth: '80%',
              background: isUser ? '#89b4fa' : '#1e1e2e',
              color: isUser ? '#11111b' : '#cdd6f4',
              borderRadius: '12px',
              padding: '12px 16px',
              boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
              border: isUser ? 'none' : '1px solid #313244',
            }}
          >
            <div
              style={{
                fontSize: '11px',
                fontWeight: 600,
                marginBottom: '4px',
                color: isUser ? '#181825' : '#a6adc8',
                textTransform: 'uppercase',
              }}
            >
              {msg.role}
            </div>
            {isUser ? (
              <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{msg.content}</div>
            ) : (
              <MarkdownRenderer content={msg.content} />
            )}

            {msg.tool_calls && msg.tool_calls.length > 0 && (
              <div
                style={{
                  marginTop: '8px',
                  padding: '8px',
                  background: '#181825',
                  borderRadius: '6px',
                  fontSize: '12px',
                  border: '1px solid #45475a',
                }}
              >
                <div style={{ fontWeight: 600, color: '#f9e2af' }}>
                  🔧 Tool Call: {msg.tool_calls[0].function.name}
                </div>
                <pre style={{ margin: '4px 0 0', fontSize: '11px', color: '#a6adc8' }}>
                  {msg.tool_calls[0].function.arguments}
                </pre>
              </div>
            )}
          </div>
        );
      })}

      {isStreaming && (
        <div
          style={{
            alignSelf: 'flex-start',
            maxWidth: '80%',
            background: '#1e1e2e',
            color: '#cdd6f4',
            borderRadius: '12px',
            padding: '12px 16px',
            border: '1px solid #89b4fa',
            boxShadow: '0 0 12px rgba(137, 180, 250, 0.2)',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: '6px',
            }}
          >
            <div style={{ fontSize: '11px', fontWeight: 600, color: '#89b4fa' }}>
              ASSISTANT (STREAMING...)
            </div>
            <button
              onClick={onCancelTurn}
              style={{
                background: '#f38ba8',
                color: '#11111b',
                border: 'none',
                borderRadius: '4px',
                padding: '2px 8px',
                fontSize: '11px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Abort Turn
            </button>
          </div>
          <MarkdownRenderer content={streamingToken} />
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
};
