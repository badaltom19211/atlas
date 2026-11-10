import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import Answer from './Answer';
import { groupSources } from './sources';
import type { CitationSource } from './types';

const doc = (id: string, document: string, page: number, count = 1): CitationSource => ({
  id, kind: 'document', label: `${document} · p. ${page}`, document,
  url: `https://workspace.example.test/${document}`, page_start: page, page_end: page,
  used_in_answer: true, citation_count: count, citation_order: Number(id.slice(1)),
});
const sql: CitationSource = { id: 'G1', kind: 'genie', label: 'Count', sql: 'SELECT count(*) FROM contracts;',
  has_rows: true, used_in_answer: true, url: 'https://workspace.example.test/genie/chat', citation_order: 0 };

describe('notebook source presentation', () => {
  it('groups by PDF, combines pages and ranks the three most cited files', () => {
    const sources = [doc('D1', 'first.pdf', 1), doc('D2', 'second.pdf', 4, 3), doc('D3', 'first.pdf', 2),
      doc('D4', 'third.pdf', 5), doc('D5', 'fourth.pdf', 9, 4)];
    const grouped = groupSources(sources);
    expect(grouped.documentCount).toBe(4);
    expect(grouped.documents.map(d => d.name)).toEqual(['fourth.pdf', 'second.pdf', 'first.pdf']);
    expect(grouped.documents[2].pages).toBe('p. 1–2');
    expect(sources[0].id).toBe('D1');
  });
  it('keeps files with identical names but different locations separate', () => {
    const first = doc('D1', 'same.pdf', 2);
    const second = { ...doc('D2', 'same.pdf', 4), url: 'https://workspace.example.test/other/same.pdf' };
    expect(groupSources([first, second]).documents).toHaveLength(2);
  });
  it('uses citation order for ties and never fabricates missing page numbers', () => {
    const first = { ...doc('D1', 'first.pdf', 2), citation_order: 5 };
    const second = { ...doc('D2', 'second.pdf', 4), page_start: null, page_end: null, citation_order: 1 };
    const groups = groupSources([first, second]).documents;
    expect(groups[0].name).toBe('second.pdf');
    expect(groups[0].pages).toBe('');
  });
  it('shows only cited SQL with rows, deduplicates it, and keeps truncated queries distinct', () => {
    const candidates = [sql, { ...sql, id: 'G2' }, { ...sql, id: 'G3', sql: 'SELECT unused', used_in_answer: false },
      { ...sql, id: 'G4', sql: 'SELECT empty', has_rows: false }, { ...sql, id: 'G5', sql: undefined }];
    expect(groupSources(candidates).sql).toHaveLength(1);
    expect(groupSources([{ ...sql, sql_truncated: true }, { ...sql, id: 'G2', sql_truncated: true }]).sql).toHaveLength(2);
  });
  it('renders SQL and PDF sources without Genie chat links or inline IDs', () => {
    const html = renderToStaticMarkup(<Answer content="There are 12 contracts." sourceDisplay="grouped" references={[sql, doc('D1', 'contract.pdf', 4)]} />);
    expect(html).toContain('Sources');
    expect(html).toContain('View SQL');
    expect(html).toContain('SELECT count(*) FROM contracts;');
    expect(html).toContain('contract.pdf');
    expect(html).toContain('p. 4');
    expect(html).not.toContain('/genie/chat');
    expect(html).not.toContain('citation-link');
    expect(html).toContain('rel="noopener noreferrer"');
  });
  it('escapes SQL as code and rejects unsafe source URLs', () => {
    const html = renderToStaticMarkup(<Answer content="Answer." sourceDisplay="grouped" references={[
      { ...sql, sql: "SELECT '<script>alert(1)</script>'" }, { ...doc('D1', 'contract.pdf', 4), url: 'javascript:alert(1)' },
    ]} />);
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('href="javascript:');
    expect(html).toContain('Link unavailable');
  });
});
