import { describe, expect, it, vi } from 'vitest';
import { readPocResponse } from './stream';

const response = (events: unknown[]) => {
  const bytes = new TextEncoder().encode(events.map(event => JSON.stringify(event)).join('\n'));
  return new Response(new ReadableStream({ start(c) { for (const byte of bytes) c.enqueue(new Uint8Array([byte])); c.close(); } }),
    { headers: { 'content-type': 'application/x-ndjson' } });
};
describe('Micro App progress stream', () => {
  it('decodes split Unicode and stages before the final sourced answer', async () => {
    const progress = vi.fn();
    const result = await readPocResponse(response([
      { type: 'progress', stage: 'searching' }, { type: 'progress', stage: 'unknown' },
      { type: 'done', answer: 'Answer ✨', custom_outputs: { references: [{ id: 'G1' }] } },
    ]), progress);
    expect(progress.mock.calls).toEqual([['searching']]);
    expect(result.answer).toBe('Answer ✨');
    expect(result.custom_outputs.references[0].id).toBe('G1');
  });
  it('rejects startup pages, truncated responses and explicit failures', async () => {
    await expect(readPocResponse(new Response('<html>Starting</html>', { status: 202 }), vi.fn())).rejects.toThrow('starting');
    await expect(readPocResponse(response([{ type: 'progress', stage: 'queued' }]), vi.fn())).rejects.toThrow('before the response');
    await expect(readPocResponse(response([{ type: 'error', message: 'Source unavailable' }]), vi.fn())).rejects.toThrow('Source unavailable');
  });
});
