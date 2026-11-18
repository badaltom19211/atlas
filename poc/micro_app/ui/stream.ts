import { progressStages, type ProgressStage } from '../../../src/Thinking';
import type { CitationSource, GenieResult } from '../../../src/types';

export interface ChatResult {
  answer: string;
  custom_outputs: { references: CitationSource[]; notebook_query: string; genie_results?: GenieResult[] };
  elapsed_seconds: number;
}

export async function readPocResponse(response: Response, onProgress: (stage: ProgressStage) => void): Promise<ChatResult> {
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === 'string' ? data.detail : 'The request could not be completed.');
  }
  if (!response.body || !response.headers.get('content-type')?.includes('application/x-ndjson')) {
    throw new Error('The app is starting. Please try again in a moment.');
  }
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let pending = '', result: ChatResult | undefined;
  const consume = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (result) throw new Error('Unexpected data after the completed response.');
    if (event.type === 'progress' && progressStages.includes(event.stage)) onProgress(event.stage);
    if (event.type === 'error') throw new Error(typeof event.message === 'string' ? event.message : 'The response failed.');
    if (event.type === 'done' && typeof event.answer === 'string' && Array.isArray(event.custom_outputs?.references)) result = event;
  };
  try {
    while (true) {
      const { done, value } = await reader.read();
      pending += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let end: number;
      while ((end = pending.indexOf('\n')) >= 0) { consume(pending.slice(0, end)); pending = pending.slice(end + 1); }
      if (done) { consume(pending); break; }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  if (!result) throw new Error('The connection ended before the response was complete. Please try again.');
  return result;
}
