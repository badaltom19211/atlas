import { StrictMode, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowUp, Plus, Copy, Check, Square } from 'lucide-react';
import Answer from '../../../src/Answer';
import Thinking, { type ProgressStage } from '../../../src/Thinking';
import { readPocResponse } from './stream';
import type { CitationSource, GenieResult } from '../../../src/types';
import './poc.css';
import '../../../src/genie.css';

type Item = { role: 'user' | 'assistant'; content: string; notebook_query?: string; refs?: CitationSource[]; results?: GenieResult[]; seconds?: number };

function Chat() {
  const [name, setName] = useState('');
  const [items, setItems] = useState<Item[]>([]);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState(false);
  const [progress, setProgress] = useState<ProgressStage>('queued');
  const request = useRef<AbortController | null>(null);
  const [error, setError] = useState('');
  const [session, setSession] = useState(() => crypto.randomUUID());
  const [copied, setCopied] = useState<number | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    fetch('/api/me').then(async r => { const data = await r.json(); if (!r.ok) throw new Error(data.detail); setName(data.name); })
      .catch(e => setError(e.message || 'Unable to verify sign-in.'));
  }, []);
  useEffect(() => {
    // Keep the scroll method's return value out of React's effect cleanup slot.
    bottom.current?.scrollIntoView({ behavior: 'smooth' });
  }, [items, pending]);
  const displayName = name.includes('@') ? name.split('@')[0].split(/[._]/).map(s => s[0]?.toUpperCase() + s.slice(1)).join(' ') : name;
  async function send() {
    const question = draft.trim();
    if (!question || request.current || !name) return;
    const controller = new AbortController(); request.current = controller;
    const history = items.slice(-6).map(({ role, content, notebook_query }) => ({ role, content, notebook_query }));
    setItems(previous => [...previous, { role: 'user', content: question }]); setDraft(''); setError(''); setPending(true); setProgress('queued');
    try {
      const response = await fetch('/api/chat', { method: 'POST', signal: controller.signal, headers: { 'Content-Type': 'application/json', 'x-atlas-request': '1', Accept: 'application/x-ndjson' },
        body: JSON.stringify({ question, history, session_id: session }) });
      const result = await readPocResponse(response, setProgress);
      setItems(previous => [...previous, { role: 'assistant', content: result.answer, refs: result.custom_outputs.references,
        results: result.custom_outputs.genie_results, notebook_query: result.custom_outputs.notebook_query, seconds: result.elapsed_seconds }]);
    } catch (e) { setError(controller.signal.aborted ? 'Response stopped.' : e instanceof Error ? e.message : 'The request could not be completed.'); }
    finally { setPending(false); request.current = null; }
  }
  return <main className="poc-shell">
    <header><div className="brand">AIA<span>Micro App POC</span></div><div className="profile"><span>{displayName || 'Signing in…'}</span><b>{displayName[0]?.toUpperCase() || '?'}</b></div></header>
    <div className="session-strip"><span>Bike Store & project documents</span><button disabled={pending} onClick={() => { setItems([]); setDraft(''); setError(''); setSession(crypto.randomUUID()); }}><Plus size={16} /> New chat</button></div>
    <div className="notice">Session-only POC · Chats are not saved. Refreshing this page clears the conversation.</div>
    <section className="messages" aria-label="Conversation">
      {items.length === 0 && <div className="empty"><div className="mark">A</div><h1>What would you like to know?</h1><p>Ask about bike-store data or documented projects.</p></div>}
      {items.map((item, index) => <article key={index} className={`message ${item.role}`}><div className="message-label">{item.role === 'user' ? 'You' : 'AIA'}{item.seconds !== undefined && <span>{item.seconds.toFixed(1)}s</span>}</div>
        <div className="body markdown">{item.role === 'assistant' ? <Answer content={item.content} references={item.refs} results={item.results} sourceDisplay="grouped" /> : item.content}</div>
        {item.role === 'assistant' && <button className="copy" aria-label="Copy answer" onClick={async () => { try { await navigator.clipboard.writeText(item.content); setCopied(index); } catch { setError('Unable to copy. Select the answer text to copy it.'); } }}>{copied === index ? <Check size={16} /> : <Copy size={16} />}</button>}
      </article>)}
      {pending && <Thinking stage={progress} searchLabel="Searching bike data and projects" />}
      {error && <div className="error" role="alert">{error}</div>}<div ref={bottom} />
    </section>
    <form className="composer" onSubmit={e => { e.preventDefault(); void send(); }}><textarea aria-label="Your question" placeholder="Message AIA…" value={draft} maxLength={12000} disabled={pending}
      onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
      <div><small>Enter to send · Shift + Enter for a new line</small>{pending ? <button type="button" aria-label="Stop response" onClick={() => request.current?.abort()}><Square size={18} /></button> : <button aria-label="Send question" disabled={!name || !draft.trim()}><ArrowUp size={21} /></button>}</div>
    </form><footer>Review the sources before using an answer.</footer>
  </main>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><Chat /></StrictMode>);
