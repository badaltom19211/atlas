import type { GenieResult } from './types';

const empty = /^(?:null|none|n\/a|—|-)$/i;

export function numericCell(raw: string): { value: number; unit: string } | null {
  const text = raw.trim();
  if (!text || empty.test(text)) return null;
  const match = text.match(/^([$€£¥]?)\s*([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:e[+-]?\d+)?)(%?)$/i);
  if (!match || (match[1] && match[3])) return null;
  const value = Number(match[2].replaceAll(',', ''));
  if (!Number.isFinite(value) || Math.abs(value) > Number.MAX_SAFE_INTEGER) return null;
  return { value, unit: match[1] || match[3] };
}

export function numericColumns(result: GenieResult): number[] {
  return result.columns.flatMap((_, index) => {
    const cells = result.rows.map(row => numericCell(row[index] ?? ''));
    return cells.length && cells.every(cell => cell && cell.unit === cells[0]?.unit) ? [index] : [];
  });
}

export function defaultAxes(result: GenieResult): { dimension: number; measure: number } {
  const numbers = numericColumns(result);
  const measure = numbers.find(index => !/(^|[ _])(id|year|month|day|zip|code|page)([ _]|$)/i.test(result.columns[index])) ?? numbers[0] ?? -1;
  const dimension = result.columns.findIndex((_, index) => index !== measure && !numbers.includes(index));
  return { dimension: dimension >= 0 ? dimension : result.columns.findIndex((_, index) => index !== measure), measure };
}

export function chartData(result: GenieResult, dimension: number, measure: number) {
  const points = result.rows.map(row => ({ label: row[dimension] ?? '', raw: row[measure] ?? '', value: numericCell(row[measure] ?? '')?.value ?? NaN }));
  let reason = '';
  if (result.truncated) reason = 'Charts need a complete result. Ask Genie for fewer rows or a grouped summary.';
  else if (dimension < 0 || measure < 0 || dimension === measure || !numericColumns(result).includes(measure)) reason = 'Choose a category and a numeric value to create a chart.';
  else if (!points.length || points.some(point => !point.label.trim() || empty.test(point.label) || !Number.isFinite(point.value))) reason = 'Charts need a category and value for every row.';
  else if (new Set(points.map(point => point.label.trim())).size !== points.length) reason = 'This category repeats. Choose a unique category or ask Genie to group the results.';
  else if (points.length > 40) reason = 'Ask Genie for 40 or fewer categories to show a chart.';
  const total = points.reduce((sum, point) => sum + point.value, 0);
  const pieReason = reason || (points.length < 2 || points.length > 12 ? 'Pie charts need 2–12 categories.' : points.some(point => point.value < 0) || !Number.isFinite(total) || total <= 0 ? 'Pie charts need non-negative values with a positive total.' : '');
  return { points, total, barReason: reason, pieReason };
}
