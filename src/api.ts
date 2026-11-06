import type { AppSession, Boot, Conversation, Feedback, Message, Note, ToolRun } from './types';
export { isLive } from './config';

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('X-Atlas-Request', '1');
  if (init.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(`/api${path}`, { ...init, headers, credentials: 'same-origin', redirect: 'error' });
  if (!response.ok) {
    if (response.status === 401) {
      window.dispatchEvent(new Event('atlas:unauthorized'));
      throw new Error('Your Databricks session has ended. Sign in again.');
    }
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string' ? body.detail : `The request failed (${response.status}). Please try again.`);
  }
  return response;
}

async function json<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await request(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
  return response.status === 204 ? undefined as T : response.json();
}

type Answer = { user?: Message; assistant: Message };

/** Consume complete NDJSON events across arbitrary UTF-8/network boundaries. */
export async function readChatResponse(response: Response, onChunk: (text: string) => void, onTool?: (tool: ToolRun) => void): Promise<Answer> {
  if (!response.body) throw new Error('AIA returned an empty response.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  let result: Answer | undefined;
  const event = (line: string) => {
    if (!line.trim()) return;
    const value = JSON.parse(line);
    if (value.type === 'error') throw new Error(value.message || 'AIA could not complete the response.');
    if (result) throw new Error('Unexpected data after the completed response.');
    if (value.type === 'delta' && typeof value.text === 'string') onChunk(value.text);
    else if (value.type === 'tool' && value.tool) onTool?.(value.tool);
    else if (value.type === 'done' && value.assistant?.id && typeof value.assistant.content === 'string') result = value;
  };
  try {
    while (true) {
      const { done, value } = await reader.read();
      pending += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let newline: number;
      while ((newline = pending.indexOf('\n')) >= 0) {
        event(pending.slice(0, newline));
        pending = pending.slice(newline + 1);
      }
      if (done) { event(pending); break; }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  if (!result) throw new Error('The connection ended before the response was complete. Reload to check the saved conversation.');
  return result;
}

export const api = {
  async boot(): Promise<Boot> {
    const response = await fetch('/api/bootstrap', { credentials: 'same-origin', redirect: 'error' });
    if (response.status === 401) return { user: null, conversations: [], historyStorage: 'local' };
    if (!response.ok) throw new Error('Unable to load your conversations. Check that the backend and history database are running.');
    return response.json();
  },
  async signIn(): Promise<Boot> {
    window.location.assign('/api/auth/login');
    return new Promise<Boot>(() => {});
  },
  create: (title: string) => json<Conversation>('/conversations', 'POST', { title }),
  update: (id: string, patch: Partial<Pick<Conversation, 'title' | 'pinned' | 'archived'>>) => json<Conversation>(`/conversations/${encodeURIComponent(id)}`, 'PATCH', patch),
  remove: (id: string) => json<void>(`/conversations/${encodeURIComponent(id)}`, 'DELETE'),
  feedback: (id: string, feedback: Feedback, saved: boolean) => json<Message>(`/messages/${encodeURIComponent(id)}`, 'PATCH', { feedback, saved }),
  comment: (id: string, text: string) => json<Note>(`/messages/${encodeURIComponent(id)}/comments`, 'POST', { text }),
  removeComment: (id: string) => json<void>(`/comments/${encodeURIComponent(id)}`, 'DELETE'),
  sessions: () => json<AppSession[]>('/sessions'),
  logout: () => json<void>('/auth/logout', 'POST'),
  async send(id: string, content: string, onChunk: (text: string) => void, signal: AbortSignal, regenerate = false, onTool?: (tool: ToolRun) => void, ids?: { user?: string; assistant: string }): Promise<Answer> {
    const response = await request(`/conversations/${encodeURIComponent(id)}/messages`, {
      method: 'POST', signal, headers: { Accept: 'application/x-ndjson' },
      body: JSON.stringify({ content, regenerate, user_id: ids?.user, assistant_id: ids?.assistant }),
    });
    return readChatResponse(response, onChunk, onTool);
  },
};
