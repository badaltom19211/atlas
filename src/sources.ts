import type { CitationSource } from './types';

export interface DocumentSource { key: string; name: string; url: string | null; pages: string; count: number; references: CitationSource[]; }

function documentPages(sources: CitationSource[]): string {
  const ranges = sources.flatMap(source => {
    const start = source.page_start;
    if (typeof start !== 'number' || !Number.isSafeInteger(start) || start < 1) return [];
    const end = source.page_end;
    return [[start, typeof end === 'number' && Number.isSafeInteger(end) && end >= start ? end : start]];
  }).sort((a, b) => a[0] - b[0]);
  const merged: number[][] = [];
  for (const range of ranges) {
    const previous = merged.at(-1);
    if (previous && range[0] <= previous[1] + 1) previous[1] = Math.max(previous[1], range[1]);
    else merged.push([...range]);
  }
  return merged.length ? `p. ${merged.map(([start, end]) => start === end ? start : `${start}–${end}`).join(', ')}` : '';
}

export function groupSources(references: CitationSource[], maxDocuments = 3) {
  const sql = new Map<string, CitationSource>();
  const documents = new Map<string, DocumentSource>();
  const used = references.filter(source => source.used_in_answer).sort((a, b) => (a.citation_order ?? 0) - (b.citation_order ?? 0));
  for (const source of used) {
    if (source.kind === 'genie') {
      if (!source.sql?.trim() || source.has_rows !== true) continue;
      // Different long queries may share the same truncated prefix.
      const key = source.sql.trim() + (source.sql_truncated ? `\n${source.id}` : '');
      if (!sql.has(key)) sql.set(key, source);
      continue;
    }
    const name = source.document || source.label;
    const key = JSON.stringify([name, source.url]);
    const entry = documents.get(key) || { key, name, url: source.url, pages: '', count: 0, references: [] };
    entry.count += source.citation_count ?? 1;
    entry.references.push(source);
    documents.set(key, entry);
  }
  const ranked = [...documents.values()].sort((a, b) => b.count - a.count);
  ranked.forEach(document => { document.pages = documentPages(document.references); });
  return { sql: [...sql.values()], documents: ranked.slice(0, maxDocuments), documentCount: ranked.length };
}
