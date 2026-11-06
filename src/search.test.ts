import { describe, expect, it } from 'vitest';
import { matchRanges, searchConversations } from './search';
import type { Conversation, Message } from './types';

function chat(id: string, title: string, content: string, archived = false, updatedAt = '2026-11-05T12:00:00Z'): Conversation {
  const message: Message = { id: `${id}-message`, role: 'assistant', content, createdAt: updatedAt, feedback: null, saved: false, comments: [] };
  return { id, title, messages: [message], createdAt: updatedAt, updatedAt, pinned: false, archived };
}

describe('conversation search', () => {
  const conversations = [chat('one', 'Supplier review', 'The **termination** clause requires 30 days notice.'),
    chat('two', 'Contract totals', 'There are 12 active contracts.'), chat('archived', 'Old agreement', 'Termination notice is 60 days.', true)];

  it('ignores case, extra whitespace, punctuation and word order', () => {
    expect(searchConversations(conversations, '  NOTICE   termination! ').map(r => r.conversation.id)).toEqual(['one', 'archived']);
  });
  it('matches message text even when the title is unrelated, and identifies the message to open', () => {
    const [result] = searchConversations(conversations, '30 days');
    expect(result.conversation.id).toBe('one');
    expect(result.messageId).toBe('one-message');
    expect(result.snippet).toContain('termination');
    expect(result.snippet).not.toContain('**');
  });
  it('requires every word rather than returning unrelated conversations', () => {
    expect(searchConversations(conversations, 'termination bicycle')).toEqual([]);
  });
  it('searches archived chats by default and applies explicit filters', () => {
    expect(searchConversations(conversations, 'termination')).toHaveLength(2);
    expect(searchConversations(conversations, 'termination', 'active').map(r => r.conversation.id)).toEqual(['one']);
    expect(searchConversations(conversations, 'termination', 'archived').map(r => r.conversation.id)).toEqual(['archived']);
  });
  it('ranks title matches first and sorts equal matches by recency without mutating input', () => {
    const records = [chat('a', 'Other', 'Notice', false, '2026-11-05'), chat('b', 'Notice', '', false, '2026-11-01'), chat('c', 'Other', 'Notice', false, '2026-11-04')];
    expect(searchConversations(records, 'notice').map(r => r.conversation.id)).toEqual(['b', 'a', 'c']);
    expect(records.map(c => c.id)).toEqual(['a', 'b', 'c']);
    expect(searchConversations(records, '   ').map(r => r.conversation.id)).toEqual(['a', 'c', 'b']);
  });
  it('handles accented names and Unicode without broken highlights', () => {
    const text = '📝 Résumé for José';
    expect(searchConversations([chat('a', text, '')], 'jose resume')).toHaveLength(1);
    expect(matchRanges(text, 'resume jose').map(([a, b]) => text.slice(a, b))).toEqual(['Résumé', 'José']);
  });
  it('shows a snippet around a match deep inside a long response', () => {
    const [result] = searchConversations([chat('a', 'Agreement', 'Introduction. '.repeat(80) + 'Termination requires notice.')], 'termination');
    expect(result.snippet).toContain('Termination');
    expect(result.snippet.startsWith('…')).toBe(true);
    expect(result.snippet.length).toBeLessThan(180);
  });
  it('can match terms spread across a title and its messages', () => {
    expect(searchConversations(conversations, 'supplier notice')[0].conversation.id).toBe('one');
  });
});
