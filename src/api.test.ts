import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ChatResponseError, failedResponseContent, readChatResponse } from './api';
import { makeMessage } from './demo';

afterEach(() => vi.unstubAllGlobals());
const assistant = makeMessage('assistant', 'Answer ✨');
const ndjson = (events: unknown[], split = 1) => {
  const bytes = new TextEncoder().encode(events.map(e => JSON.stringify(e)).join('\r\n'));
  return new Response(new ReadableStream({ start(c) { for (let i = 0; i < bytes.length; i += split) c.enqueue(bytes.slice(i, i + split)); c.close(); } }));
};

describe('FastAPI chat integration', () => {
  it('decodes split UTF-8, tool receipts, and final messages', async () => {
    const chunk = vi.fn(), tool = vi.fn();
    const receipt = { id: 'genie', name: 'genie_structured_data_tool', status: 'error', input: '{}', output: '{"ok":false}' };
    const result = await readChatResponse(ndjson([{ type: 'tool', tool: receipt }, { type: 'delta', text: 'Answer ✨' }, { type: 'done', assistant }]), chunk, tool);
    expect(chunk).toHaveBeenCalledWith('Answer ✨');
    expect(tool).toHaveBeenCalledWith(receipt);
    expect(result.assistant).toEqual(assistant);
  });
  it('rejects truncated responses and explicit errors', async () => {
    await expect(readChatResponse(ndjson([{ type: 'delta', text: 'Partial' }]), vi.fn())).rejects.toThrow('before the response was complete');
    await expect(readChatResponse(ndjson([{ type: 'error', message: 'Tool failed' }]), vi.fn())).rejects.toThrow('Tool failed');
  });
  it('keeps safe backend diagnostics in the chat bubble instead of a temporary toast only', async () => {
    const message = 'AI Gateway chat model failed (HTTP 403). Check the app scope and your access.';
    let failure: unknown;
    try { await readChatResponse(ndjson([{ type: 'error', message }]), vi.fn()); } catch (error) { failure = error; }
    expect(failure).toBeInstanceOf(ChatResponseError);
    expect(failedResponseContent(failure)).toBe(message);
    expect(failedResponseContent(new Error('private transport detail'))).not.toContain('private transport detail');
    expect(failedResponseContent(new DOMException('Stopped', 'AbortError'))).toBe('Response stopped.');
  });
  it('preserves contract metadata without putting it in the visible answer', async () => {
    const chunk = vi.fn();
    const message = { ...assistant, content: 'The notice period is 30 days.', tools: [], custom_outputs: {
      sources: [{ source_no: 1, file_name: 'fixture.pdf', pages: 'p. 4', used_in_answer: true }],
      citation_status: 'reported',
    } };
    const result = await readChatResponse(ndjson([
      { type: 'delta', text: message.content }, { type: 'done', assistant: message },
    ]), chunk);
    expect(result.assistant.custom_outputs).toEqual(message.custom_outputs);
    expect(chunk).toHaveBeenCalledExactlyOnceWith(message.content);
    expect(result.assistant.content).not.toContain('fixture.pdf');
  });
  it('sends to the same-origin API with stable IDs, cancellation, and no browser token', async () => {
    const fetcher = vi.fn().mockResolvedValue(ndjson([{ type: 'done', assistant }]));
    vi.stubGlobal('fetch', fetcher);
    const signal = new AbortController().signal;
    await api.send('conversation', 'Question', vi.fn(), signal, false, vi.fn(), { user: 'u', assistant: 'a' });
    const [url, request] = fetcher.mock.calls[0];
    expect(url).toBe('/api/conversations/conversation/messages');
    expect(request.signal).toBe(signal);
    expect(request.credentials).toBe('same-origin');
    expect(request.headers.has('Authorization')).toBe(false);
    expect(request.headers.get('X-Atlas-Request')).toBe('1');
    expect(JSON.parse(request.body)).toEqual({ content: 'Question', user_id: 'u', assistant_id: 'a', regenerate: false });
  });
  it('loads history from the backend and writes feedback and comments there', async () => {
    const fetcher = vi.fn().mockImplementation(async (url: string) => Response.json(url === '/api/bootstrap' ? { user: { id: 'user' }, conversations: [], historyStorage: 'lakebase' } : {}));
    vi.stubGlobal('fetch', fetcher);
    expect((await api.boot()).historyStorage).toBe('lakebase');
    await api.feedback('answer', 'up', true);
    await api.comment('answer', 'Source checked');
    expect(fetcher.mock.calls[1][0]).toBe('/api/messages/answer');
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ feedback: 'up', saved: true });
    expect(fetcher.mock.calls[2][0]).toBe('/api/messages/answer/comments');
  });
  it('does not replace unauthorized or failed server requests with preview answers', async () => {
    const dispatch = vi.fn();
    vi.stubGlobal('window', { dispatchEvent: dispatch });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 401 })));
    expect((await api.boot()).user).toBeNull();
    await expect(api.create('Private')).rejects.toThrow('session has ended');
    expect(dispatch).toHaveBeenCalled();
  });
});
