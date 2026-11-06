import type { Conversation, Message } from './types';

export const uuid = () => crypto.randomUUID();
export const makeMessage = (role: Message['role'], content: string): Message => ({ id: uuid(), role, content, createdAt: new Date().toISOString(), feedback: null, saved: false, comments: [], status: 'complete' });
export const makeConversation = (title = 'New conversation'): Conversation => ({ id: uuid(), title, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), pinned: false, archived: false, messages: [] });

export function demoAnswer(): string {
  return 'This is a UI preview. Open the deployed AIA app to get an answer from your data.';
}

export function readStored(): Conversation[] {
  try {
    const raw = localStorage.getItem('atlas.conversations.v1');
    if (!raw) return [];
    const data: unknown = JSON.parse(raw);
    if (!Array.isArray(data) || !data.every(c => c && typeof c.id === 'string' && typeof c.title === 'string' && Array.isArray(c.messages))) return [];
    return data as Conversation[];
  } catch { return []; }
}
