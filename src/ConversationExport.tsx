import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Download, X } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { exportMarkdown } from './exportMarkdown';
import { columnLabel } from './genieData';
import type { Conversation } from './types';
import './conversationExport.css';

export function ConversationDocument({ conversation }: { conversation: Conversation }) {
  return <main className="export-paper">
    <header className="export-document-header"><span className="export-brand">AIA<span>.</span></span>
      <p>Conversation</p><h1>{conversation.title}</h1>
    </header>
    {conversation.messages.map((message, index) => <section className="export-message" key={message.id}>
      <h2><span>{String(index + 1).padStart(2, '0')}</span>{message.role === 'user' ? 'You' : 'AIA'}</h2>
      {message.role === 'user' ? <div className="export-question">{message.content}</div> : <>
        <div className="export-answer"><ReactMarkdown skipHtml remarkPlugins={[remarkGfm,
          exportMarkdown(message.custom_outputs?.references, message.custom_outputs?.sources),
        ]}>{message.content}</ReactMarkdown></div>
        {message.custom_outputs?.genie_results?.map(result => <div className="export-result" key={result.id}>
          <table aria-label="Answer data"><thead><tr>{result.columns.map((name, column) => <th key={column}>{columnLabel(name)}</th>)}</tr></thead>
            <tbody>{result.rows.map((row, rowIndex) => <tr key={rowIndex}>{result.columns.map((_, column) => <td key={column}>{row[column] ?? ''}</td>)}</tr>)}</tbody>
          </table>
          {result.truncated && <p className="export-incomplete">Partial result: only the rows available in this conversation are included.</p>}
        </div>)}
        {message.status === 'stopped' && <p className="export-incomplete">Response stopped. This answer may be incomplete.</p>}
        {message.status === 'error' && <p className="export-incomplete">Response interrupted. This answer may be incomplete.</p>}
      </>}
    </section>)}
  </main>;
}

export default function ConversationExport({ conversation, close }: { conversation: Conversation; close: () => void }) {
  const dialog = useRef<HTMLDivElement>(null);
  const printButton = useRef<HTMLButtonElement>(null);
  const closeRef = useRef(close); closeRef.current = close;
  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    const root = document.getElementById('root');
    const wasInert = root?.inert ?? false;
    const originalTitle = document.title;
    document.title = conversation.title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '').trim().slice(0, 120) || 'AIA conversation';
    if (root) root.inert = true;
    document.body.classList.add('export-open');
    printButton.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); closeRef.current(); }
      if (event.key === 'Tab') {
        const buttons = Array.from(dialog.current?.querySelectorAll<HTMLButtonElement>('button') ?? []);
        const first = buttons[0], last = buttons.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener('keydown', handleKey);
    return () => {
      if (root) root.inert = wasInert;
      document.title = originalTitle;
      document.body.classList.remove('export-open');
      document.removeEventListener('keydown', handleKey);
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, [conversation.title]);

  return createPortal(<div className="conversation-export" role="dialog" aria-modal="true" aria-labelledby="export-title" ref={dialog}>
    <div className="export-toolbar"><div><h2 id="export-title">Export conversation</h2>
      <p>Choose Save as PDF in the print window. Turn off Headers and footers for a clean copy.</p></div>
      <div className="export-actions"><button ref={printButton} className="primary-button" onClick={() => window.print()}><Download size={17} />Save as PDF</button>
        <button className="icon-button" aria-label="Close export preview" onClick={close}><X size={20} /></button></div>
    </div>
    <ConversationDocument conversation={conversation} />
  </div>, document.body);
}
