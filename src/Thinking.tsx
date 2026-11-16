import { useEffect, useState } from 'react';
import { Sparkles } from 'lucide-react';

export const progressStages = ['queued', 'understanding', 'searching', 'composing', 'sources'] as const;
export type ProgressStage = typeof progressStages[number];
const labels: Record<ProgressStage, string[]> = {
  queued: ['Getting started', 'Waiting for the assistant'],
  understanding: ['Understanding your question', 'Working through the context'],
  searching: ['Searching contracts and records', 'Waiting for search results'],
  composing: ['Putting the answer together', 'Preparing your response'],
  sources: ['Preparing source references', 'Finishing your response'],
};

export function thinkingLabel(stage: ProgressStage, tick: number) {
  return labels[stage][tick % labels[stage].length];
}

export default function Thinking({ stage = 'queued' }: { stage?: ProgressStage }) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    setTick(0);
    const timer = window.setInterval(() => setTick(value => value + 1), 4500);
    return () => window.clearInterval(timer);
  }, [stage]);
  return <div className="thinking" role="status" aria-live="polite" aria-atomic="true">
    <span className="thinking-orbit" aria-hidden="true"><Sparkles size={17} /></span>
    <span key={`${stage}-${tick}`} className="thinking-label">{thinkingLabel(stage, tick)}</span>
    <span className="thinking-dots" aria-hidden="true"><i /><i /><i /></span>
  </div>;
}
