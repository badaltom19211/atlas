import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import Thinking, { progressStages, thinkingLabel } from './Thinking';

describe('workflow progress', () => {
  it('varies the text within the actual stage without advancing to a made-up stage', () => {
    for (const stage of progressStages) {
      expect(thinkingLabel(stage, 0)).not.toBe(thinkingLabel(stage, 1));
      expect(thinkingLabel(stage, 2)).toBe(thinkingLabel(stage, 0));
    }
    const html = renderToStaticMarkup(<Thinking stage="searching" />);
    expect(html).toContain('Searching contracts and records');
    expect(html).toContain('role="status"');
    expect(html).toContain('thinking-orbit');
    expect(html).not.toContain('Finishing');
  });
});
