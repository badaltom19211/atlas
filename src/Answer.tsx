import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ChevronDown, ExternalLink, FileText, Database } from 'lucide-react';
import type { CitationSource } from './types';
import { groupSources } from './sources';

export function sourceUrl(value: string | null): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : undefined;
  } catch { return undefined; }
}

export function citationMarkdown(content: string, sources: CitationSource[]) {
  const known = new Set(sources.filter(s => s.used_in_answer).map(s => s.id));
  return content.replace(/\[\s*([GD]\d+(?:\s*[,;]\s*[GD]\d+)*)\s*\]/g, (original, group: string) => {
    const ids = group.match(/[GD]\d+/g) || [];
    return ids.every(id => known.has(id)) ? ids.map(id => `[${id}](#citation-${id})`).join(' ') : original;
  });
}

export function GroupedSources({ references }: { references: CitationSource[] }) {
  const { sql, documents, documentCount } = groupSources(references);
  if (!sql.length && !documents.length) return null;
  return <details className="answer-sources grouped-sources" aria-label="Sources">
    <summary className="sources-toggle"><FileText size={15} /> Sources <span className="source-count">{sql.length + documentCount}</span><ChevronDown size={15} /></summary>
    <ul className="sources-list">
      {sql.map((source, index) => <li key={source.id} className="sql-source">
        <div className="source-heading"><Database size={15} /><span>SQL query {index + 1}</span></div>
        <details><summary>View SQL{source.sql_truncated ? ' (excerpt)' : ''}</summary><pre><code>{source.sql}</code></pre></details>
      </li>)}
      {documents.map(source => <li key={source.key}>
        <div className="source-heading"><FileText size={15} />
          {sourceUrl(source.url) ? <a href={sourceUrl(source.url)} target="_blank" rel="noopener noreferrer">{source.name}<ExternalLink size={13} /></a> : <span>{source.name}</span>}
        </div>
        {(source.pages || !sourceUrl(source.url)) && <small>{[source.pages, !sourceUrl(source.url) ? 'Link unavailable' : ''].filter(Boolean).join(' · ')}</small>}
      </li>)}
    </ul>
    {documentCount > documents.length && <small className="source-limit">Showing the {documents.length} most cited documents of {documentCount}.</small>}
  </details>;
}

export default function Answer({ content, references = [], sourceDisplay }: { content: string; references?: CitationSource[]; sourceDisplay?: 'grouped' }) {
  const [expanded, setExpanded] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const used = references.filter(source => source.used_in_answer);
  return <>
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
      a: ({ href, children }) => {
        const source = used.find(s => href === `#citation-${s.id}`);
        if (source) return <button className="citation-link" title={source.label} aria-label={`View source ${source.id}: ${source.label}`}
          onClick={() => { setExpanded(true); setSelected(source.id); }}>{children}</button>;
        const safe = sourceUrl(href || null);
        return safe ? <a href={safe} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>;
      },
    }}>{sourceDisplay === 'grouped' ? content : citationMarkdown(content, references)}</ReactMarkdown>
    {sourceDisplay === 'grouped' ? <GroupedSources references={references} /> : used.length > 0 && <div className="answer-sources">
      <button className="sources-toggle" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
        <FileText size={15} /> {used.length} {used.length === 1 ? 'source' : 'sources'} <ChevronDown size={15} className={expanded ? 'rotated' : ''} />
      </button>
      {expanded && <ul className="sources-list">{used.map(source => <li key={source.id} className={selected === source.id ? 'selected-source' : ''}>
        <div className="source-heading">{source.kind === 'genie' ? <Database size={15} /> : <FileText size={15} />}<span className="source-id">{source.id}</span>
          {sourceUrl(source.url) ? <a href={sourceUrl(source.url)} target="_blank" rel="noopener noreferrer">{source.label}<ExternalLink size={13} /></a> : <span>{source.label}</span>}
        </div>
        <small>{source.kind === 'genie' ? 'Structured contract data' : 'Contract document'}{!sourceUrl(source.url) && ' · Link unavailable'}</small>
        {source.sql && <details><summary>View query{source.sql_truncated ? ' (excerpt)' : ''}</summary><pre><code>{source.sql}</code></pre></details>}
      </li>)}</ul>}
    </div>}
  </>;
}
