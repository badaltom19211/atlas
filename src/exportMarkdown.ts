import type { Root } from 'mdast';
import type { CitationSource, ContractSource } from './types';

// Only the export copy is transformed. Stored messages and their citations stay intact.
interface Node {
  type: string;
  value?: string;
  url?: string;
  depth?: number;
  children?: Node[];
}
const textOf = (node: Node): string => node.value ?? node.children?.map(textOf).join('') ?? '';
const sourceHeading = /^(?:sources?|references?|citations?|supporting sources?|supporting documents?)\s*:?$/i;
const sourceLink = /(?:#citation-|\/api\/documents\/pdf(?:\?|$)|\/Volumes\/|\.pdf(?:[?#]|$))/i;
const idLabel = /^\[?\s*(?:[GD]\d+|\d+|source\s*\d+)(?:\s*[,;]\s*(?:[GD]\d+|\d+))*\s*\]?$/i;

export function exportMarkdown(references: CitationSource[] = [], sources: ContractSource[] = []) {
  const urls = new Set(references.map(source => source.url).filter(Boolean));
  const numbers = new Set(sources.map(source => String(source.source_no)));
  references.forEach((_, index) => numbers.add(String(index + 1)));

  function cleanText(value: string): string {
    return value
      .replace(/\[+\s*(?:[GD]\d+|source\s*\d+)(?:\s*[,;]\s*(?:[GD]\d+|source\s*\d+))*\s*\]+/gi, '')
      .replace(/【[^】]*[GD]\d+[^】]*】/g, '')
      .replace(/\[((?:\d+\s*[,;]\s*)*\d+)\]/g, (match, ids: string) => ids.split(/\s*[,;]\s*/).every(id => numbers.has(id)) ? '' : match)
      .replace(/[ \t]+([.,;:!?])/g, '$1');
  }

  function cleanChildren(children: Node[]): Node[] {
    const output: Node[] = [];
    let sourceDepth: number | undefined;
    for (const node of children) {
      const label = textOf(node).trim();
      // Historical replies can contain an appended source section in the answer itself.
      if ((node.type === 'heading' || node.type === 'paragraph') &&
          (sourceHeading.test(label) || /^(?:sources?|references?|citations?)\s*:\s+\S/i.test(label))) {
        sourceDepth = node.type === 'heading' ? node.depth : 6;
        continue;
      }
      if (sourceDepth !== undefined) {
        if (node.type !== 'heading' || (node.depth ?? 6) > sourceDepth) continue;
        sourceDepth = undefined;
      }
      if (['footnoteDefinition', 'footnoteReference', 'definition', 'image', 'imageReference', 'html'].includes(node.type)) continue;
      if (node.type === 'link' || node.type === 'linkReference') {
        // Drop citation labels/URLs; retain ordinary prose used as link text, without a link.
        if (idLabel.test(label) || label === node.url || urls.has(node.url ?? '') || sourceLink.test(node.url ?? '')) continue;
        output.push(...cleanChildren(node.children ?? []));
        continue;
      }
      if (node.type === 'text') {
        output.push({ ...node, value: cleanText(node.value ?? '') });
      } else if (node.children) {
        const cleaned = cleanChildren(node.children);
        if (cleaned.length) output.push({ ...node, children: cleaned });
      } else {
        // Preserve literal code and business figures instead of guessing that they are citations.
        output.push(node);
      }
    }
    // Removing a link/footnote can leave adjacent text nodes and a space before punctuation.
    const merged: Node[] = [];
    for (const node of output) {
      const previous = merged.at(-1);
      if (node.type === 'text' && previous?.type === 'text') previous.value = cleanText((previous.value ?? '') + (node.value ?? ''));
      else merged.push(node);
    }
    return merged;
  }

  return () => (tree: Root) => {
    tree.children = cleanChildren(tree.children) as Root['children'];
  };
}
