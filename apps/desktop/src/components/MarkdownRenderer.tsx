import React from 'react';

interface MarkdownProps {
  content: string;
}

export const MarkdownRenderer: React.FC<MarkdownProps> = ({ content }) => {
  // Simple, secure native Markdown formatter for desktop presentation
  const lines = content.split('\n');
  const elements: React.ReactNode[] = [];
  let inCodeBlock = false;
  let codeBuffer: string[] = [];
  let codeLang = '';

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.startsWith('```')) {
      if (inCodeBlock) {
        // End code block
        elements.push(
          <div key={`code-${i}`} style={{
            background: '#1e1e2e',
            color: '#cdd6f4',
            padding: '12px',
            borderRadius: '6px',
            fontFamily: 'Consolas, monospace',
            fontSize: '13px',
            overflowX: 'auto',
            margin: '8px 0',
            border: '1px solid #313244'
          }}>
            {codeLang && <div style={{ fontSize: '11px', color: '#a6adc8', marginBottom: '6px', textTransform: 'uppercase' }}>{codeLang}</div>}
            <pre style={{ margin: 0 }}>{codeBuffer.join('\n')}</pre>
          </div>
        );
        codeBuffer = [];
        inCodeBlock = false;
      } else {
        // Start code block
        inCodeBlock = true;
        codeLang = line.replace('```', '').trim();
      }
      continue;
    }

    if (inCodeBlock) {
      codeBuffer.push(line);
      continue;
    }

    if (line.startsWith('# ')) {
      elements.push(<h1 key={i} style={{ fontSize: '18px', fontWeight: 700, margin: '8px 0' }}>{line.slice(2)}</h1>);
    } else if (line.startsWith('## ')) {
      elements.push(<h2 key={i} style={{ fontSize: '16px', fontWeight: 600, margin: '6px 0' }}>{line.slice(3)}</h2>);
    } else if (line.startsWith('### ')) {
      elements.push(<h3 key={i} style={{ fontSize: '14px', fontWeight: 600, margin: '4px 0' }}>{line.slice(4)}</h3>);
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      elements.push(
        <li key={i} style={{ marginLeft: '16px', listStyleType: 'disc' }}>
          {formatInline(line.slice(2))}
        </li>
      );
    } else if (line.trim() === '') {
      elements.push(<div key={i} style={{ height: '8px' }} />);
    } else {
      elements.push(
        <p key={i} style={{ margin: '4px 0', lineHeight: 1.5 }}>
          {formatInline(line)}
        </p>
      );
    }
  }

  return <div style={{ wordBreak: 'break-word' }}>{elements}</div>;
};

function formatInline(text: string): React.ReactNode {
  // Bold **text** and inline `code`
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code
          key={index}
          style={{
            background: '#313244',
            color: '#f38ba8',
            padding: '2px 5px',
            borderRadius: '4px',
            fontFamily: 'Consolas, monospace',
            fontSize: '12px',
          }}
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}
