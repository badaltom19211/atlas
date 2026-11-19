import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ConversationDocument } from './ConversationExport';
import type { Conversation, Message } from './types';

const message = (id: string, role: Message['role'], content: string): Message => ({
  id, role, content, createdAt: '2026-11-19T10:00:00Z', feedback: null, saved: false, comments: [], status: 'complete',
});
const conversation = (messages: Message[]): Conversation => ({
  id: 'chat', title: 'Contract review', messages, createdAt: '', updatedAt: '', archived: false, pinned: false,
});
const render = (messages: Message[]) => renderToStaticMarkup(<ConversationDocument conversation={conversation(messages)} />);

describe('conversation PDF document', () => {
  it('includes every turn and answer table, excluding all source, tool, note and feedback metadata', () => {
    const answer = message('a', 'assistant', '**Notice:** 30 days [D1, G1].\n\nRenewal costs £5,000 [1].');
    answer.comments = [{ id: 'note', text: 'PRIVATE REVIEW NOTE', createdAt: '' }];
    answer.feedback = 'down';
    answer.tools = [{ id: 'tool', name: 'secret_tool', status: 'completed', input: 'PRIVATE TOOL INPUT', output: 'PRIVATE TOOL OUTPUT' }];
    answer.custom_outputs = { sources: [], references: [
      { id: 'D1', kind: 'document', label: 'PRIVATE PDF NAME', url: 'https://example.test/private.pdf', used_in_answer: true },
      { id: 'G1', kind: 'genie', label: 'PRIVATE SQL TITLE', url: null, sql: 'SELECT private_column FROM private_table', used_in_answer: true },
    ], genie_results: [{ id: 'G1', title: 'PRIVATE RESULT KEY', columns: ['contract_status', 'total_count'], rows: [['Active', '7'], ['Closed', '3']], truncated: false }] };
    const messages = [message('q', 'user', 'What is the notice period?'), answer, message('q2', 'user', 'और renewal?'), message('a2', 'assistant', 'No automatic renewal.')];
    const original = JSON.stringify(messages);
    const html = render(messages);
    expect(html.match(/class="export-message"/g)).toHaveLength(4);
    for (const text of ['What is the notice period?', '30 days', '£5,000', 'और renewal?', 'No automatic renewal.', 'Contract status', 'Total count', 'Active', 'Closed']) expect(html).toContain(text);
    for (const text of ['[D1', '[G1', '[1]', 'PRIVATE', 'private_table', 'private.pdf', 'secret_tool', 'href=', 'Sources', 'References']) expect(html).not.toContain(text);
    expect(JSON.stringify(messages)).toBe(original);
  });

  it('removes historical source sections, footnotes and citation links while retaining later answer sections', () => {
    const html = render([message('a', 'assistant', 'Term: 12 months [D1](#citation-D1). Fee: $10[^fee].\n\n[Agreement.pdf](https://example.test/agreement.pdf)\n\n## Sources\n- SECRET SOURCE\n```sql\nSELECT secret FROM records\n```\n\n## Next steps\nReview clause 5.3(c).\n\n[^fee]: SECRET FOOTNOTE')]);
    for (const text of ['Term: 12 months', 'Fee: $10', 'Next steps', 'Review clause 5.3(c).']) expect(html).toContain(text);
    expect(html).toContain('Term: 12 months. Fee: $10.');
    for (const text of ['SECRET', 'SELECT', 'Agreement.pdf', 'citation-D1', 'footnote', 'href=']) expect(html).not.toContain(text);
  });

  it('removes plain source appendices and normalizes grouped legacy markers', () => {
    const html = render([message('a', 'assistant', 'First fact [[D2]]; second 【G1】.\n\n**References:**\nSECRET APPENDIX')]);
    expect(html).toContain('First fact; second.');
    expect(html).not.toContain('SECRET');
    expect(html).not.toContain('D2');
    expect(html).not.toContain('G1');
  });

  it('preserves business numbers, lists, literal code and ordinary linked prose; never loads external content', () => {
    const html = render([message('a', 'assistant', 'The range is [2026].\n\n1. Keep 20% and section 4.2.\n2. [Review the terms](https://example.test/terms).\n\n`values[1]`\n\n![tracking](https://example.test/pixel)\n\n<script>alert(1)</script>\n\nhttps://example.test/source')]);
    for (const text of ['[2026]', '20%', 'section 4.2', 'Review the terms', 'values[1]', '<ol>']) expect(html).toContain(text);
    for (const text of ['href=', '<script', '<img', 'example.test', 'alert(1)']) expect(html).not.toContain(text);
  });

  it('does not present interrupted answers or truncated results as complete', () => {
    const answer = message('a', 'assistant', 'Partial answer.');
    answer.status = 'stopped';
    answer.custom_outputs = { sources: [], genie_results: [{ id: 'G1', title: '', columns: ['count'], rows: [['8']], truncated: true }] };
    const html = render([answer]);
    expect(html).toContain('This answer may be incomplete.');
    expect(html).toContain('Partial result: only the rows available');
  });
});
