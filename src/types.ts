export type Feedback = 'up' | 'down' | null;
export interface Note { id: string; text: string; createdAt: string; }
export interface ToolRun { id: string; name: string; status: 'running' | 'completed' | 'error' | 'stopped' | 'unavailable'; input: string; output: string; }
export interface ContractSource { source_no: number; used_in_answer: boolean | null; chunk_id: string | null; file_name: string | null; document_title: string | null; vendor_name: string | null; section_title: string | null; page_start: number | null; page_end: number | null; pages: string; citation: string | null; excerpt_truncated: boolean; }
export interface Message { id: string; role: 'user' | 'assistant'; content: string; createdAt: string; feedback: Feedback; saved: boolean; comments: Note[]; tools?: ToolRun[]; status?: 'complete' | 'stopped' | 'error'; custom_outputs?: { sources: ContractSource[]; citation_status?: 'reported' | 'missing' | 'invalid' | 'not_applicable' }; }
export interface Conversation { id: string; title: string; createdAt: string; updatedAt: string; pinned: boolean; archived: boolean; messages: Message[]; }
export interface User { id: string; name: string; email: string; }
export interface AppSession { id: string; device: string; createdAt: string; expiresAt: string; current: boolean; }
export interface Boot { user: User | null; conversations: Conversation[]; historyStorage: 'local' | 'lakebase'; }
