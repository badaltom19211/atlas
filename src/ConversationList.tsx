import { useEffect, useMemo, useRef, useState } from 'react';
import { Archive, ArrowRight, MessageSquare, MoreHorizontal, PenLine, Plus, Search, Trash2, X } from 'lucide-react';
import { SearchText } from './SearchText';
import { searchConversations } from './search';
import type { ConversationResult, ConversationScope } from './search';
import type { Conversation } from './types';

type OpenConversation = (id: string, messageId?: string) => void;
const date = (value: string) => new Date(value).toLocaleDateString([], { month: 'short', day: 'numeric' });
export const searchShortcut = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘ K' : 'Ctrl K';

function ResultContent({ result, query }: { result: ConversationResult; query: string }) {
  const c = result.conversation;
  return <><span className="recent-icon"><MessageSquare size={18} /></span><span className="result-copy">
    <span className="result-title"><strong><SearchText text={c.title} query={query} /></strong>{c.archived && <span className="result-badge">Archived</span>}</span>
    {result.snippet && <span className="result-snippet"><SearchText text={result.snippet} query={query} /></span>}
    <small>{date(c.updatedAt)}<span aria-hidden="true"> · </span>{c.messages.length} {c.messages.length === 1 ? 'message' : 'messages'}</small>
  </span></>;
}

function SearchField({ query, setQuery, inputRef, label, onKeyDown }: {
  query: string; setQuery: (query: string) => void; inputRef?: React.RefObject<HTMLInputElement | null>;
  label: string; onKeyDown?: React.KeyboardEventHandler<HTMLInputElement>;
}) {
  return <div className="search-field"><Search size={19} /><input ref={inputRef} data-autofocus type="search" autoComplete="off"
    aria-label={label} placeholder="Search titles and messages…" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={onKeyDown} />
    {query && <button className="icon-button" aria-label="Clear search" onClick={() => { setQuery(''); inputRef?.current?.focus(); }}><X size={16} /></button>}
  </div>;
}

export function ConversationSearch({ conversations, onOpen }: { conversations: Conversation[]; onOpen: OpenConversation }) {
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const results = useMemo(() => searchConversations(conversations, query), [conversations, query]);
  return <>
    <SearchField query={query} setQuery={setQuery} inputRef={inputRef} label="Search all conversations" onKeyDown={e => {
      if (e.nativeEvent.isComposing) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); resultsRef.current?.querySelector('button')?.focus(); }
      if (e.key === 'Enter' && results[0]) { e.preventDefault(); onOpen(results[0].conversation.id, results[0].messageId); }
    }} />
    <div className="result-count" role="status">{query.trim() ? `${results.length} ${results.length === 1 ? 'conversation' : 'conversations'} found` : 'Recent conversations'}<span>Includes archived</span></div>
    <div className="search-results" ref={resultsRef} onKeyDown={e => {
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
      const buttons = Array.from(resultsRef.current?.querySelectorAll('button') || []);
      const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
      if (index < 0) return;
      e.preventDefault();
      if (index === 0 && e.key === 'ArrowUp') inputRef.current?.focus();
      else buttons[Math.min(buttons.length - 1, index + (e.key === 'ArrowDown' ? 1 : -1))]?.focus();
    }}>
      {results.map(result => <button key={result.conversation.id} onClick={() => onOpen(result.conversation.id, result.messageId)}>
        <ResultContent result={result} query={query} /><ArrowRight size={16} />
      </button>)}
      {!results.length && <div className="empty-state search-empty"><Search size={28} /><h2>{query.trim() ? 'No matches found' : 'No conversations yet'}</h2><p>{query.trim() ? 'Try a name, topic, or a few words from a message.' : 'Your conversations will appear here.'}</p></div>}
    </div>
    <div className="search-footer"><span><kbd>↑</kbd><kbd>↓</kbd> Navigate</span><span><kbd>Enter</kbd> Open</span><span><kbd>Esc</kbd> Close</span></div>
  </>;
}

export function ChatActions({ title, disabled, onRename, onDelete }: { title: string; disabled?: boolean; onRename: () => void; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => { if (!ref.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open]);
  return <div className="chat-actions-menu" ref={ref} onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setOpen(false); }} onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); trigger.current?.focus(); } }}>
    <button ref={trigger} className="icon-button" aria-label={`Options for ${title}`} aria-expanded={open} onClick={() => setOpen(!open)}><MoreHorizontal size={17} /></button>
    {open && <div className="chat-actions-popover" role="group" aria-label="Conversation actions"><button disabled={disabled} onClick={() => { setOpen(false); onRename(); }}><PenLine size={15} />Rename</button><button className="delete-chat-action" disabled={disabled} onClick={() => { setOpen(false); onDelete(); }}><Trash2 size={15} />Delete</button></div>}
  </div>;
}

export function ConversationHistory({ conversations, onOpen, onNew, onPatch }: {
  conversations: Conversation[]; onOpen: OpenConversation; onNew: () => void;
  onPatch: (id: string, patch: Partial<Pick<Conversation, 'archived'>>) => void;
}) {
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState<ConversationScope>('all');
  const inputRef = useRef<HTMLInputElement>(null);
  const results = useMemo(() => searchConversations(conversations, query, scope), [conversations, query, scope]);
  return <div className="collection-page">
    <div className="collection-heading"><h1>Conversations</h1><button className="primary-button" onClick={onNew}><Plus size={17} /> New conversation</button></div>
    <div className="collection-filters"><SearchField query={query} setQuery={setQuery} inputRef={inputRef} label="Search conversations" />
      <div className="scope-tabs" role="group" aria-label="Conversation filter">{(['all', 'active', 'archived'] as const).map(value =>
        <button key={value} aria-pressed={scope === value} onClick={() => setScope(value)}>{value[0].toUpperCase() + value.slice(1)}</button>)}</div>
    </div>
    <div className="result-count" role="status">{results.length} {results.length === 1 ? 'conversation' : 'conversations'}{query.trim() ? ' found' : ''}</div>
    <div className="history-table">{results.map(result => {
      const c = result.conversation;
      return <div className="history-table-row" key={c.id}>
        <button onClick={() => onOpen(c.id, result.messageId)}><ResultContent result={result} query={query} /></button>
        <div className="history-actions">
          <button className="icon-button" aria-label={c.archived ? 'Restore conversation' : 'Archive conversation'} title={c.archived ? 'Restore' : 'Archive'} onClick={() => onPatch(c.id, { archived: !c.archived })}><Archive size={16} /></button>
        </div>
      </div>;
    })}</div>
    {!results.length && <div className="empty-state"><Search size={32} /><h2>{query.trim() ? 'No matches found' : 'No conversations here'}</h2><p>{query.trim() ? 'Try another word, or choose All to include archived chats.' : 'Start a new conversation or select another filter.'}</p>{!query.trim() && <button className="secondary-button" onClick={onNew}>New conversation <Plus size={16} /></button>}</div>}
  </div>;
}
