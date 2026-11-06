import type { Conversation } from './types';

export type ConversationScope = 'all' | 'active' | 'archived';
export interface ConversationResult {
  conversation: Conversation;
  snippet: string;
  messageId?: string;
  score: number;
}

export function normalizeSearch(text: string): string {
  return text.normalize('NFKD').replace(/\p{M}/gu, '').toLocaleLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
}

function termsFor(query: string): string[] {
  return [...new Set(normalizeSearch(query).split(' ').filter(Boolean))];
}

export function plainText(text: string): string {
  return text.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^[\s]*#{1,6}\s+/gm, '').replace(/[*`_~|]/g, '').replace(/\s+/g, ' ').trim();
}

// Keep offsets into the original text so accents and Unicode highlights stay correct.
export function matchRanges(text: string, query: string): [number, number][] {
  let folded = '';
  const starts: number[] = [], ends: number[] = [];
  let offset = 0;
  for (const char of text) {
    const part = char.normalize('NFKD').replace(/\p{M}/gu, '').toLocaleLowerCase();
    folded += part;
    for (let i = 0; i < part.length; i++) { starts.push(offset); ends.push(offset + char.length); }
    offset += char.length;
  }
  const ranges: [number, number][] = [];
  for (const term of termsFor(query)) {
    let from = 0, index: number;
    while ((index = folded.indexOf(term, from)) !== -1) {
      ranges.push([starts[index], ends[index + term.length - 1]]);
      from = index + term.length;
    }
  }
  ranges.sort((a, b) => a[0] - b[0]);
  return ranges.reduce<[number, number][]>((merged, range) => {
    const last = merged.at(-1);
    if (last && range[0] <= last[1]) last[1] = Math.max(last[1], range[1]);
    else merged.push([...range]);
    return merged;
  }, []);
}

function excerpt(text: string, query: string): string {
  const first = matchRanges(text, query)[0]?.[0] ?? 0;
  const start = Math.max(0, first - 42);
  const end = Math.min(text.length, start + 175);
  return `${start ? '…' : ''}${text.slice(start, end)}${end < text.length ? '…' : ''}`;
}

export function searchConversations(conversations: Conversation[], query: string, scope: ConversationScope = 'all'): ConversationResult[] {
  const terms = termsFor(query);
  const phrase = normalizeSearch(query);
  return conversations.flatMap(conversation => {
    if (scope === 'active' && conversation.archived || scope === 'archived' && !conversation.archived) return [];
    const title = normalizeSearch(conversation.title);
    const messages = conversation.messages.map(message => {
      const text = plainText(message.content);
      const normalized = normalizeSearch(text);
      return { message, text, normalized, hits: terms.filter(term => normalized.includes(term)).length };
    });
    const haystack = [title, ...messages.map(m => m.normalized)].join(' ');
    if (!terms.every(term => haystack.includes(term))) return [];
    const best = [...messages].sort((a, b) => b.hits - a.hits)[0];
    const matched = terms.length > 0 && best && best.hits > 0;
    const score = terms.length ? (title === phrase ? 100 : title.includes(phrase) ? 60 : 0)
      + terms.filter(term => title.includes(term)).length * 10 + (best?.hits ?? 0) : 0;
    return [{ conversation, score, snippet: excerpt(best?.text || '', query),
      messageId: matched ? best.message.id : undefined }];
  }).sort((a, b) => b.score - a.score || b.conversation.updatedAt.localeCompare(a.conversation.updatedAt));
}
