import { useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { ArrowDown, ArrowRight, ArrowUp, Bookmark, CheckCheck, ChevronRight, CircleHelp, Copy, History, LogOut, Menu, MessageCircle, MessageSquare, Monitor, PanelLeftClose, PenLine, Plus, Search, ShieldCheck, Sparkles, Square, ThumbsDown, ThumbsUp, Trash2, X } from 'lucide-react';
import Answer from './Answer';
import { api, failedResponseContent, isLive } from './api';
import { ToolDetails } from './ToolDetails';
import { ConversationHistory, ConversationSearch, ChatActions, searchShortcut } from './ConversationList';
import { demoAnswer, makeConversation, makeMessage, readStored, uuid } from './demo';
import type { AppSession, Conversation, Message, User } from './types';

type View = 'home' | 'chat' | 'history' | 'library';
type Modal = 'search' | 'settings' | 'delete' | 'rename' | 'about' | null;

function Mark({ small = false }: { small?: boolean }) { return <span className={`brand-mark ${small ? 'small' : ''}`} aria-hidden="true">AIA</span>; }
function WelcomeMark() {
  return <div className="welcome-mark" aria-hidden="true"><div className="welcome-halo" /><svg viewBox="0 0 160 160" fill="none">
    <defs><linearGradient id="aia-ribbon" x1="32" y1="120" x2="125" y2="35" gradientUnits="userSpaceOnUse"><stop stopColor="#93032d" /><stop offset=".52" stopColor="#dc0741" /><stop offset="1" stopColor="#ff678b" /></linearGradient><linearGradient id="aia-fold" x1="70" y1="68" x2="114" y2="124" gradientUnits="userSpaceOnUse"><stop stopColor="#ffb1c3" /><stop offset="1" stopColor="#df154a" /></linearGradient></defs>
    <path d="M26 124 64 39C70 25 87 23 94 39l42 85h-31L78 65l-26 59H26Z" fill="url(#aia-ribbon)" />
    <path d="m61 106 17-41 27 59h31l-16-32-59 14Z" fill="url(#aia-fold)" />
    <path d="m64 39 14 26 27 59" stroke="white" strokeOpacity=".4" strokeWidth="1.5" />
  </svg></div>;
}
function IconButton({ label, children, onClick, active, disabled }: { label: string; children: ReactNode; onClick?: () => void; active?: boolean; disabled?: boolean }) { return <button type="button" className={`icon-button ${active ? 'active' : ''}`} title={label} aria-label={label} aria-pressed={active} disabled={disabled} onClick={onClick}>{children}</button>; }
function Dialog({ title, children, close, wide = false }: { title: string; children: ReactNode; close: () => void; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(close); closeRef.current = close;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    const node = ref.current!;
    const controls = () => Array.from(node.querySelectorAll<HTMLElement>('button:not(:disabled), input, textarea, select, a[href], [tabindex="0"]'));
    (node.querySelector<HTMLElement>('[data-autofocus]') || controls()[0])?.focus();
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeRef.current();
      if (e.key === 'Tab') { const items = controls(); const first = items[0], last = items[items.length - 1]; if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); } }
    };
    node.addEventListener('keydown', handler);
    return () => { node.removeEventListener('keydown', handler); previous?.focus(); };
  }, []);
  return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) close(); }}><div ref={ref} role="dialog" aria-modal="true" aria-label={title} className={`dialog ${wide ? 'wide' : ''}`}><div className="dialog-header"><h2>{title}</h2><IconButton label="Close dialog" onClick={close}><X size={19} /></IconButton></div>{children}</div></div>;
}

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>(isLive ? [] : readStored);
  const [user, setUser] = useState<User | null>(isLive || sessionStorage.getItem('atlas.signed-out') ? null : { id: 'demo', name: 'You', email: 'UI preview' });
  const [ready, setReady] = useState(!isLive);
  const [authError, setAuthError] = useState('');
  const [historyStorage, setHistoryStorage] = useState<'local' | 'lakebase'>('local');
  const [view, setView] = useState<View>('home');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [modal, setModal] = useState<Modal>(null);
  const [renameTitle, setRenameTitle] = useState('');
  const [savingTitle, setSavingTitle] = useState(false);
  const [targetId, setTargetId] = useState<string | null>(null);
  const [sidebar, setSidebar] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [commentTarget, setCommentTarget] = useState<{ cid: string; mid: string } | null>(null);
  const [note, setNote] = useState('');
  const [toast, setToast] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [settingsTab, setSettingsTab] = useState('General');
  const [sessions, setSessions] = useState<AppSession[]>([]);
  const [compact, setCompact] = useState(() => localStorage.getItem('atlas.compact') === 'true');
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const [showJump, setShowJump] = useState(false);
  const [searchTarget, setSearchTarget] = useState<{ cid: string; mid: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const lock = useRef(false);
  const rawName = (user?.name || user?.email || 'User').replace(/\s*\[[^\]]*\]/g, '').trim();
  const profileName = rawName.includes(',') ? rawName.split(',').map(part => part.trim()).reverse().join(' ') : rawName;
  const profileInitial = Array.from(profileName || 'User')[0].toLocaleUpperCase();
  const active = conversations.find(c => c.id === activeId);
  const noteMessage = conversations.find(c => c.id === commentTarget?.cid)?.messages.find(m => m.id === commentTarget?.mid);
  const visible = conversations.filter(c => !c.archived).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  const saved = conversations.flatMap(c => c.messages.filter(m => m.saved).map(m => ({ c, m })));
  const notify = (message: string) => setToast(message);
  const safe = async (work: () => Promise<void>) => { try { await work(); } catch (e) { notify(e instanceof Error ? e.message : 'Something went wrong. Please try again.'); } };
  const update = (id: string, fn: (c: Conversation) => Conversation) => setConversations(cs => cs.map(c => c.id === id ? fn(c) : c));

  useEffect(() => {
    if (isLive) api.boot().then(data => { setUser(data.user); setConversations(data.conversations); setHistoryStorage(data.historyStorage); }).catch(e => setAuthError(e.message)).finally(() => setReady(true));
    const unauthorized = () => { setAuthError('Your Databricks session expired. Please sign in again.'); setUser(null); setConversations([]); abortRef.current?.abort(); };
    window.addEventListener('atlas:unauthorized', unauthorized);
    return () => { window.removeEventListener('atlas:unauthorized', unauthorized); };
  }, []);
  useEffect(() => { if (!isLive) { try { localStorage.setItem('atlas.conversations.v1', JSON.stringify(conversations)); } catch { setToast('Browser storage is full. Export important conversations before closing this tab.'); } } }, [conversations]);
  useEffect(() => { if (toast) { const id = setTimeout(() => setToast(''), 4500); return () => clearTimeout(id); } }, [toast]);
  useEffect(() => {
    const handle = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setModal('search'); } if (e.key === 'Escape') { setSidebar(false); setCommentTarget(null); } };
    window.addEventListener('keydown', handle); return () => window.removeEventListener('keydown', handle);
  }, []);
  useEffect(() => {
    if (searchTarget?.cid === activeId) {
      const message = document.getElementById(`message-${searchTarget.mid}`);
      message?.scrollIntoView({ block: 'center', behavior: 'instant' });
      message?.focus({ preventScroll: true });
    } else if (nearBottom.current) bottomRef.current?.scrollIntoView({ block: 'end', behavior: 'instant' });
  }, [view, activeId, active?.messages.length, active?.messages.at(-1)?.content, searchTarget]);
  useEffect(() => { if (searchTarget) { const timer = setTimeout(() => setSearchTarget(null), 4000); return () => clearTimeout(timer); } }, [searchTarget]);
  useEffect(() => { if (inputRef.current) { inputRef.current.style.height = 'auto'; inputRef.current.style.height = `${Math.min(inputRef.current.scrollHeight, 180)}px`; } }, [input]);

  const openConversation = (id: string, messageId?: string) => { nearBottom.current = !messageId; setSearchTarget(messageId ? { cid: id, mid: messageId } : null); setActiveId(id); setView('chat'); setCommentTarget(null); setSidebar(false); setModal(null); setInput(''); };
  const renameChat = (id: string) => { setTargetId(id); setRenameTitle(conversations.find(c => c.id === id)?.title || ''); setModal('rename'); };
  const deleteChat = (id: string) => { setTargetId(id); setModal('delete'); };
  const newChat = () => { nearBottom.current = true; setSearchTarget(null); setShowJump(false); setActiveId(null); setView('home'); setInput(''); setCommentTarget(null); setSidebar(false); setTimeout(() => inputRef.current?.focus(), 0); };
  const patchConversation = async (id: string, patch: Partial<Pick<Conversation, 'title' | 'pinned' | 'archived'>>) => { if (isLive) { const next = await api.update(id, patch); update(id, () => next); } else update(id, c => ({ ...c, ...patch })); };
  const setMessage = async (cid: string, message: Message, patch: Partial<Pick<Message, 'feedback' | 'saved'>>) => { const next = { ...message, ...patch }; if (isLive) await api.feedback(message.id, next.feedback, next.saved); update(cid, c => ({ ...c, messages: c.messages.map(m => m.id === message.id ? next : m) })); };
  const send = async (regenerate = false) => {
    if (lock.current || (!regenerate && !input.trim())) return;
    lock.current = true;
    nearBottom.current = true; setSearchTarget(null);
    const content = regenerate ? active?.messages.filter(m => m.role === 'user').at(-1)?.content || '' : input.trim();
    let conversation = active;
    let assistant: Message | undefined;
    let localUser: Message | undefined;
    const controller = new AbortController(); abortRef.current = controller;
    try {
      if (!conversation) { conversation = isLive ? await api.create(input.trim().slice(0, 70)) : makeConversation(input.trim().slice(0, 70)); setConversations(cs => [conversation!, ...cs]); }
      const id = conversation.id;
      setActiveId(id); setView('chat'); setBusyId(id); setInput('');
      assistant = makeMessage('assistant', ''); localUser = regenerate ? undefined : makeMessage('user', content);
      const aid = assistant.id;
      update(id, c => ({ ...c, updatedAt: new Date().toISOString(), messages: [...c.messages, ...(localUser ? [localUser] : []), assistant!] }));
      if (isLive) {
        const result = await api.send(id, content, text => update(id, c => ({ ...c, messages: c.messages.map(m => m.id === aid ? { ...m, content: m.content + text } : m) })), controller.signal, regenerate, tool => update(id, c => ({ ...c, messages: c.messages.map(m => m.id === aid ? { ...m, tools: [...(m.tools || []).filter(t => t.id !== tool.id), tool] } : m) })), { user: localUser?.id, assistant: aid });
        update(id, c => ({ ...c, messages: c.messages.map(m => m.id === aid ? result.assistant : m.id === localUser?.id && result.user ? result.user : m) }));
      } else {
        const answer = demoAnswer();
        for (let i = 0; i < answer.length; i += 24) {
          if (controller.signal.aborted) throw new DOMException('Stopped', 'AbortError');
          await new Promise(resolve => setTimeout(resolve, 14));
          update(id, c => ({ ...c, messages: c.messages.map(m => m.id === aid ? { ...m, content: answer.slice(0, i + 24) } : m) }));
        }
      }
    } catch (e) {
      const stopped = e instanceof DOMException && e.name === 'AbortError';
      if (conversation && assistant) update(conversation.id, c => ({ ...c, messages: c.messages.map(m => m.id === assistant!.id ? { ...m, status: stopped ? 'stopped' : 'error', tools: m.tools?.map(t => t.status === 'running' ? { ...t, status: stopped ? 'stopped' : 'error' } : t), content: m.content || failedResponseContent(e) } : m) }));
      if (!stopped) notify(e instanceof Error ? e.message : 'Unable to send your message.');
    } finally { setBusyId(null); lock.current = false; abortRef.current = null; }
  };
  const openSettings = () => { setSettingsTab('General'); setModal('settings'); safe(async () => setSessions(isLive ? await api.sessions() : [{ id: 'demo-session', device: 'This browser', createdAt: new Date().toISOString(), expiresAt: '', current: true }])); };
  const logout = async () => { abortRef.current?.abort(); if (isLive) await api.logout(); else sessionStorage.setItem('atlas.signed-out', 'true'); setUser(null); setModal(null); setCommentTarget(null); newChat(); };
  const addComment = async (e: FormEvent) => { e.preventDefault(); if (!note.trim() || !commentTarget) return; const target = commentTarget; const text = note.trim(); await safe(async () => { const comment = isLive ? await api.comment(target.mid, text) : { id: uuid(), text, createdAt: new Date().toISOString() }; update(target.cid, c => ({ ...c, messages: c.messages.map(m => m.id === target.mid ? { ...m, comments: [...m.comments, comment] } : m) })); setNote(''); }); };

  const composer = <div className={`composer-wrap ${view === 'chat' ? 'chat-composer' : ''}`}>
    <form className="composer" onSubmit={e => { e.preventDefault(); void send(); }}>
      <textarea ref={inputRef} aria-label="Message AIA" placeholder="Message AIA…" value={input} maxLength={16000} rows={1} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
      <div className="composer-bottom"><div className="composer-send"><span>{busyId ? 'Working on your response…' : 'Enter to send · Shift + Enter for a new line'}</span>{busyId ? <button type="button" className="send-button stop" aria-label="Stop response" onClick={() => abortRef.current?.abort()}><Square size={15} fill="currentColor" /></button> : <button className="send-button" aria-label="Send message" disabled={!input.trim()}><ArrowUp size={20} /></button>}</div></div>
    </form>
    <p className="composer-disclaimer">{isLive ? 'AI can make mistakes. Check important details.' : <><span className="demo-dot" /> UI preview · saved in this browser.</>}</p>
  </div>;

  if (!ready) return <div className="loading-screen"><Mark /><p>Loading…</p></div>;
  if (!user) return <div className="login-page"><div className="login-brand"><span className="wordmark">AIA</span></div><div className="login-card"><h1>Sign in</h1>{authError && <p role="alert" className="auth-error">{authError}</p>}<button className="primary-button" onClick={() => { if (isLive) { setAuthError(''); void api.signIn().then(data => { setUser(data.user); setConversations(data.conversations); setHistoryStorage(data.historyStorage); }).catch(e => setAuthError(e.message)); } else { sessionStorage.removeItem('atlas.signed-out'); setUser({ id: 'demo', name: 'You', email: 'UI preview' }); } }}>{isLive ? <><ShieldCheck size={18} /> Continue with Databricks</> : <><ArrowRight size={18} /> Open preview</>}</button><span className="login-footnote"><ShieldCheck size={14} />{isLive ? 'Databricks workspace sign-in' : 'UI preview · no account required'}</span></div></div>;

  return <div className={`app ${compact ? 'compact' : ''} ${navCollapsed ? 'nav-collapsed' : ''}`}>
    {sidebar && <button className="sidebar-scrim" aria-label="Close navigation" onClick={() => { setSidebar(false); if (window.innerWidth > 760) setNavCollapsed(true); }} />}
    <aside className={`sidebar ${sidebar ? 'is-open' : ''}`}>
      <div className="brand-row"><button className="brand" onClick={newChat}><span className="wordmark">AIA<span className="brand-dot" aria-hidden="true">.</span></span></button><IconButton label="Close navigation" onClick={() => { setSidebar(false); if (window.innerWidth > 760) setNavCollapsed(true); }}><PanelLeftClose size={17} /></IconButton></div>
      <button className="new-chat" onClick={newChat}><Plus size={17} /><span>New conversation</span><span className="new-shortcut">↗</span></button>
      <nav className="main-nav" aria-label="Main navigation"><button onClick={() => { setSidebar(false); setModal('search'); }}><Search size={18} /><span>Search</span><kbd>{searchShortcut}</kbd></button><button className={view === 'history' ? 'selected' : ''} onClick={() => { setView('history'); setSidebar(false); setCommentTarget(null); }}><History size={18} /><span>Conversations</span><span className="nav-count">{visible.length}</span></button><button className={view === 'library' ? 'selected' : ''} onClick={() => { setView('library'); setSidebar(false); setCommentTarget(null); }}><Bookmark size={18} /><span>Saved responses</span>{saved.length > 0 && <span className="nav-count">{saved.length}</span>}</button></nav>
      <div className="sidebar-conversations"><div className="sidebar-section-title"><span>CONVERSATIONS</span><span className="conversation-total">{visible.length}</span></div>{visible.map(c => <div className={`sidebar-chat ${activeId === c.id && view === 'chat' ? 'selected' : ''}`} key={c.id}><button className="history-link" onClick={() => openConversation(c.id)}><MessageSquare size={15} /><span>{c.title}</span></button><ChatActions title={c.title} disabled={busyId === c.id} onRename={() => renameChat(c.id)} onDelete={() => deleteChat(c.id)} /></div>)}</div>
    </aside>
    <main className="main-shell">
      <header className="topbar"><div className="breadcrumb"><button className="mobile-menu icon-button" aria-label="Open navigation" onClick={() => { setNavCollapsed(false); setSidebar(true); }}><Menu size={20} /></button><span className="workspace-name"><span className="workspace-symbol" aria-hidden="true" />AIA</span><ChevronRight size={13} /><strong>{view === 'home' ? 'New conversation' : view === 'chat' ? (active?.title || 'Conversation') : view === 'history' ? 'Conversations' : 'Saved responses'}</strong></div><div className="topbar-right"><IconButton label="About AIA" onClick={() => setModal('about')}><CircleHelp size={18} /></IconButton><span className="topbar-divider" /><button className="header-profile" onClick={openSettings} aria-label={`Account settings for ${profileName}`} title={profileName}><span className="header-profile-name">{profileName}</span><span className="avatar" aria-hidden="true">{profileInitial}</span></button></div></header>
      <div className={`content-layout ${commentTarget ? 'with-comments' : ''}`}><div className="main-content">
        {view === 'home' && <div className="home-content"><WelcomeMark />{composer}</div>}
        {view === 'chat' && active && <>
          <div className="chat-toolbar"><span>{active.messages.length} {active.messages.length === 1 ? 'message' : 'messages'}</span>{active.archived && <span className="result-badge">Archived conversation</span>}</div>
          <div className="chat-thread">
            <div className="message-scroll" ref={scrollRef} onScroll={() => {
              const node = scrollRef.current;
              if (node) { nearBottom.current = node.scrollHeight - node.scrollTop - node.clientHeight < 100; setShowJump(!nearBottom.current); }
            }}><div className="messages">{active.messages.map((m, index) => <article
              className={`message ${m.role} ${searchTarget?.mid === m.id ? 'search-match' : ''}`}
              id={`message-${m.id}`} tabIndex={-1} aria-label={`${m.role === 'assistant' ? 'AIA' : 'Your'} message`} key={m.id}>
              <div className="message-avatar">{m.role === 'assistant' ? <Mark small /> : <span className="avatar">{profileInitial}</span>}</div>
              <div className="message-main">
                <div className="message-meta"><strong>{m.role === 'assistant' ? 'AIA' : 'You'}</strong><time dateTime={m.createdAt} title={new Date(m.createdAt).toLocaleString()}>{new Date(m.createdAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</time></div>
                <div className="markdown">{m.content ? (m.role === 'user' ? <div className="user-text">{m.content}</div> : <Answer content={m.content} references={m.custom_outputs?.references} sourceDisplay={m.custom_outputs?.source_display} />) : <div className="thinking" role="status"><i /><i /><i /><span>Thinking…</span></div>}</div>
                <ToolDetails tools={m.tools} />
                {m.status === 'stopped' && <span className="response-status">Response stopped</span>}
                {m.status === 'error' && <span className="response-status error">Response interrupted. You can try again.</span>}
                {m.role === 'assistant' && m.content && !(busyId === active.id && index === active.messages.length - 1) && <div className="response-actions">
                  <IconButton label="Copy response" onClick={() => void safe(async () => { await navigator.clipboard.writeText(m.content); notify('Response copied'); })}><Copy size={16} /></IconButton>
                  <IconButton label="Helpful response" active={m.feedback === 'up'} onClick={() => void safe(() => setMessage(active.id, m, { feedback: m.feedback === 'up' ? null : 'up' }))}><ThumbsUp size={16} /></IconButton>
                  <IconButton label="Unhelpful response" active={m.feedback === 'down'} onClick={() => void safe(() => setMessage(active.id, m, { feedback: m.feedback === 'down' ? null : 'down' }))}><ThumbsDown size={16} /></IconButton>
                  <span className="action-separator" />
                  <button className={`comment-action ${commentTarget?.mid === m.id ? 'active' : ''}`} onClick={() => { setCommentTarget({ cid: active.id, mid: m.id }); setNote(''); }}><MessageCircle size={16} />{m.comments.length ? `${m.comments.length} note${m.comments.length > 1 ? 's' : ''}` : 'Add note'}</button>
                  <IconButton label={m.saved ? 'Unsave response' : 'Save response'} active={m.saved} onClick={() => void safe(() => setMessage(active.id, m, { saved: !m.saved }))}><Bookmark size={16} /></IconButton>
                </div>}
              </div>
            </article>)}<div ref={bottomRef} /></div></div>
            {showJump && <button className="jump-latest" aria-label="Jump to latest message" onClick={() => { setSearchTarget(null); nearBottom.current = true; bottomRef.current?.scrollIntoView({ block: 'end', behavior: 'instant' }); }}><ArrowDown size={17} /> Latest</button>}
          </div>{composer}
        </>}
        {view === 'history' && <ConversationHistory conversations={conversations} onOpen={openConversation} onNew={newChat}
          onPatch={(id, patch) => void safe(() => patchConversation(id, patch))} />}
        {view === 'library' && <div className="collection-page"><h1>Saved responses</h1>{saved.length ? <div className="saved-grid">{saved.map(({ c, m }) => <article className="saved-card" key={m.id}><div><Mark small /><IconButton label="Unsave response" active onClick={() => void safe(() => setMessage(c.id, m, { saved: false }))}><Bookmark size={16} /></IconButton></div><h2>{c.title}</h2><p>{m.content.replace(/[#*`]/g, '').slice(0, 240)}…</p><button className="text-button" onClick={() => openConversation(c.id)}>Open conversation <ArrowRight size={15} /></button></article>)}</div> : <div className="empty-state"><Bookmark size={35} /><h2>No saved responses</h2><p>Tap the bookmark below any response to save it here.</p><button className="secondary-button" onClick={newChat}>New chat <ArrowRight size={15} /></button></div>}</div>}
      </div>{commentTarget && noteMessage && <aside className="notes-panel"><div className="notes-header"><div><MessageCircle size={18} /><h2>Response notes</h2></div><IconButton label="Close response notes" onClick={() => setCommentTarget(null)}><X size={18} /></IconButton></div><div className="note-context"><span>AIA RESPONSE</span><p>{noteMessage.content.slice(0, 150).replace(/[#*]/g, '')}…</p></div><div className="notes-list">{noteMessage.comments.length === 0 && <div className="notes-empty"><PenLine size={24} /><h3>No notes yet</h3></div>}{noteMessage.comments.map(n => <div className="note-card" key={n.id}><div><span className="avatar small-avatar">{profileInitial}</span><strong>You</strong><IconButton label="Delete note" onClick={() => void safe(async () => { if (isLive) await api.removeComment(n.id); update(commentTarget.cid, c => ({ ...c, messages: c.messages.map(m => m.id === commentTarget.mid ? { ...m, comments: m.comments.filter(x => x.id !== n.id) } : m) })); })}><Trash2 size={13} /></IconButton></div><p>{n.text}</p><time>{new Date(n.createdAt).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</time></div>)}</div><form className="note-form" onSubmit={e => void addComment(e)}><textarea aria-label="Write a response note" placeholder="Add a note…" value={note} maxLength={4000} onChange={e => setNote(e.target.value)} /><button className="primary-button" disabled={!note.trim()}>Add note <ArrowUp size={15} /></button></form><p className="notes-private"><ShieldCheck size={12} /> Only visible to you</p></aside>}</div>
    </main>
    {toast && <div className="toast" role="status"><CheckCheck size={17} />{toast}<button aria-label="Dismiss notification" onClick={() => setToast('')}><X size={14} /></button></div>}
    {modal === 'search' && <Dialog title="Search conversations" close={() => setModal(null)} wide><ConversationSearch conversations={conversations} onOpen={openConversation} /></Dialog>}
    {modal === 'rename' && <Dialog title="Rename conversation" close={() => { if (!savingTitle) setModal(null); }}><form onSubmit={e => { e.preventDefault(); if (!targetId || !renameTitle.trim() || savingTitle) return; setSavingTitle(true); void safe(async () => { await patchConversation(targetId, { title: renameTitle.trim() }); setModal(null); notify('Conversation renamed'); }).finally(() => setSavingTitle(false)); }}><label className="rename-label" htmlFor="conversation-title">Conversation name</label><input id="conversation-title" className="rename-input" data-autofocus value={renameTitle} maxLength={120} onChange={e => setRenameTitle(e.target.value)} /><div className="dialog-footer"><button type="button" className="secondary-button" disabled={savingTitle} onClick={() => setModal(null)}>Cancel</button><button className="primary-button" disabled={savingTitle || !renameTitle.trim()}>{savingTitle ? 'Saving…' : 'Save'}</button></div></form></Dialog>}
    {modal === 'delete' && <Dialog title="Delete conversation?" close={() => setModal(null)}><p className="dialog-copy">This removes “{conversations.find(c => c.id === targetId)?.title}” and its messages, notes, and saved responses. This cannot be undone.</p><div className="dialog-footer"><button className="secondary-button" onClick={() => setModal(null)}>Keep conversation</button><button className="danger-button" onClick={() => void safe(async () => { if (targetId) { if (isLive) await api.remove(targetId); setConversations(cs => cs.filter(c => c.id !== targetId)); if (activeId === targetId) newChat(); setModal(null); notify('Conversation deleted'); } })}>Delete conversation</button></div></Dialog>}
    {modal === 'settings' && <Dialog title="Settings" close={() => setModal(null)} wide><div className="settings-tabs">{['General', 'Sessions', 'Connections'].map(tab => <button className={settingsTab === tab ? 'selected' : ''} key={tab} onClick={() => setSettingsTab(tab)}>{tab}</button>)}</div>{settingsTab === 'General' && <div className="settings-body"><div className="account-summary"><span className="avatar">{profileInitial}</span><div><strong>{profileName}</strong><span>{user.email}</span></div><span className="soft-badge">{isLive ? 'Databricks authentication' : 'Preview'}</span></div><div className="setting-row"><div><strong>Compact conversations</strong><p>Reduce message spacing.</p></div><button role="switch" aria-checked={compact} aria-label="Compact conversations" className={`toggle ${compact ? 'on' : ''}`} onClick={() => { setCompact(!compact); localStorage.setItem('atlas.compact', String(!compact)); }}><span /></button></div><button className="signout-button" onClick={() => void safe(logout)}><LogOut size={16} />{isLive ? 'Sign out of AIA' : 'Leave preview'}</button></div>}{settingsTab === 'Sessions' && <div className="settings-body"><p className="dialog-copy">Sign out of this browser here. Other signed-in devices are managed in Databricks.</p>{sessions.map(s => <div className="session-row" key={s.id}><Monitor size={22} /><div><strong>{s.device}</strong><span>{s.current ? 'This session' : `Signed in ${new Date(s.createdAt).toLocaleDateString()}`}</span></div><button className="secondary-button" onClick={() => void safe(async () => { if (s.current) await logout(); else notify('Manage other signed-in devices in Databricks.'); })}>{s.current ? 'Sign out' : 'Revoke'}</button></div>)}</div>}{settingsTab === 'Connections' && <div className="settings-body">{[[ShieldCheck, 'Databricks sign-in', 'Workspace account', isLive ? 'Connected' : 'Preview'], [Sparkles, 'Contract assistant', 'Contract search', isLive ? 'Configured' : 'Preview'], [History, 'History', isLive ? (historyStorage === 'lakebase' ? 'Lakebase' : 'Local database') : 'This browser', isLive && historyStorage === 'lakebase' ? 'Connected' : 'Local']].map(([Icon, title, desc, status]) => { const I = Icon as typeof ShieldCheck; return <div className="connection-row" key={String(title)}><I size={20} /><div><strong>{String(title)}</strong><span>{String(desc)}</span></div><span className="soft-badge">{String(status)}</span></div>; })}</div>}</Dialog>}
    {modal === 'about' && <Dialog title="About AIA" close={() => setModal(null)}><div className="about-body"><Mark /><div className="about-status"><span className="demo-dot" />{isLive ? 'Databricks' : 'UI preview'}</div><p className="fine-print">{isLive ? 'Chat history is saved ' + (historyStorage === 'lakebase' ? 'in Lakebase.' : 'in the local database.') : 'Preview conversations and notes stay in this browser.'}</p><button className="primary-button" onClick={() => setModal(null)}>Close <ArrowRight size={16} /></button></div></Dialog>}
  </div>;
}
