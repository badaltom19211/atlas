import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import Answer, { citationMarkdown, sourceUrl } from './Answer';
import type { CitationSource } from './types';

const sources: CitationSource[] = [
  { id: 'G1', kind: 'genie', label: 'Contract count', url: 'https://workspace.example.test/genie', used_in_answer: true },
  { id: 'D1', kind: 'document', label: 'Agreement · p. 4', url: null, used_in_answer: true },
  { id: 'D2', kind: 'document', label: 'Unused', url: null, used_in_answer: false },
];

describe('answer citations', () => {
  it('converts only known used citations, including grouped references', () => {
    expect(citationMarkdown('Fact [G1, D1]. Unknown [D99]. Unused [D2].', sources))
      .toBe('Fact [G1](#citation-G1) [D1](#citation-D1). Unknown [D99]. Unused [D2].');
  });
  it('does not turn dangerous or credential URLs into source links', () => {
    for (const url of ['javascript:alert(1)', 'data:text/html,evil', '//evil.example', 'https://user:secret@example.test']) {
      expect(sourceUrl(url)).toBeUndefined();
    }
    expect(sourceUrl('https://workspace.example.test/file')).toBe('https://workspace.example.test/file');
  });
  it('renders citation buttons and source count without rendering untrusted HTML', () => {
    const html = renderToStaticMarkup(<Answer content={'Count 12 [G1]. Notice 30 days [D1]. <script>alert(1)</script>'} references={sources} />);
    expect(html).toContain('View source G1: Contract count');
    expect(html).toContain('2 sources');
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('View source D2');
  });
  it('allows only the authenticated relative PDF route and renders it in Sources', () => {
    const path = '/Volumes/dev_diamonddaas/raw/aia/AIAIMSG/MO_Contract_Mgt/Input/Contract + #1.pdf';
    const link = '/api/documents/pdf?path=' + encodeURIComponent(path);
    expect(sourceUrl(link)).toBe(link);
    expect(sourceUrl(link + '#page=4')).toBe(link + '#page=4');
    for (const value of ['/api/auth/logout', '/api/documents/pdf', '//evil.example/api/documents/pdf?path=x',
      link + '&path=other.pdf', link + '&redirect=https://evil.example', link + '#bad',
      '/api/documents/pdf?path=/etc/file.pdf', '/api/documents/pdf?path=/Volumes/test.html']) {
      expect(sourceUrl(value)).toBeUndefined();
    }
    const html = renderToStaticMarkup(<Answer content="Supported answer." sourceDisplay="grouped" references={[
      { id: 'D1', kind: 'document', label: 'Contract', document: 'Contract.pdf', url: link, used_in_answer: true },
    ]} />);
    expect(html).toContain(`href="${link}"`);
    expect(html).toContain('target="_blank"');
    expect(html).not.toContain('Link unavailable');
  });
  it('keeps older messages with no references readable', () => {
    const html = renderToStaticMarkup(<Answer content="An earlier answer." />);
    expect(html).toContain('An earlier answer.');
    expect(html).not.toContain('sources-toggle');
  });
});
