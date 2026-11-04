import { expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ToolDetails } from './ToolDetails';
import type { ToolRun } from './types';

it('keeps contract source metadata out of the visible chat and preserves legacy tool history', () => {
  const contract: ToolRun = { id: 'contract', name: 'contract_rag_tool', status: 'completed', input: '{}', output: 'hidden-citation' };
  expect(renderToStaticMarkup(<ToolDetails tools={[contract]} />)).toBe('');
  expect(renderToStaticMarkup(<ToolDetails tools={[{ ...contract, name: 'structured_contract_agent' }]} />)).toBe('');
  const legacy: ToolRun = { ...contract, id: 'legacy', name: 'genie_structured_data_tool', output: 'old result' };
  const html = renderToStaticMarkup(<ToolDetails tools={[contract, legacy]} />);
  expect(html).toContain('old result');
  expect(html).not.toContain('hidden-citation');
});
