import { Fragment } from 'react';
import { matchRanges } from './search';

export function SearchText({ text, query }: { text: string; query: string }) {
  const ranges = matchRanges(text, query);
  let end = 0;
  return <>{ranges.map(([start, finish]) => {
    const before = text.slice(end, start); end = finish;
    return <Fragment key={start}>{before}<mark>{text.slice(start, finish)}</mark></Fragment>;
  })}{text.slice(end)}</>;
}
