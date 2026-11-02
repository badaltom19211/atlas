export type Feedback = 'up' | 'down' | null;
export interface Note { id: string; text: string; createdAt: string; }
export interface ToolRun { id: string; name: string; status: 'running' | 'completed' | 'error' | 'stopped' | 'unavailable'; input: string; output: string; }
export interface Message { id: string; role: 'user' | 'assistant'; content: string; createdAt: string; feedback: Feedback; saved: boolean; comments: Note[]; tools?: ToolRun[]; status?: 'complete' | 'stopped' | 'error'; }
export interface Conversation { id: string; title: string; createdAt: string; updatedAt: string; pinned: boolean; archived: boolean; messages: Message[]; }
export interface User { id: string; name: string; email: string; }
export interface AppSession { id: string; device: string; createdAt: string; expiresAt: string; current: boolean; }
export interface Boot { user: User | null; conversations: Conversation[]; historyStorage: 'local' | 'lakebase'; }
