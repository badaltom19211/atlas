import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import GenieResult, { BarView, PieView } from './GenieResult';
import Answer from './Answer';
import { chartData, defaultAxes, numericCell, numericColumns } from './genieData';
import type { GenieResult as Result } from './types';

const result: Result = { id: 'G1', title: 'Contracts by status', columns: ['Status', 'Count'], rows: [['Active', '12'], ['Expired', '3']], truncated: false };

describe('Genie result views', () => {
  it('shows actual rows, accessible view controls and sources alongside the answer', () => {
    const html = renderToStaticMarkup(<Answer content="12 active contracts." results={[result]} sourceDisplay="grouped" references={[{ id: 'G1', kind: 'genie', label: 'Count', sql: 'SELECT count(*)', has_rows: true, url: null, used_in_answer: true }]} />);
    for (const text of ['Genie results', 'Contracts by status', '<th scope="col">Status', '>Active</td>', '>12</td>', 'Table', 'Bar', 'Pie', 'View SQL']) expect(html).toContain(text);
    expect(html).not.toContain('Retrieved references');
  });
  it('preserves formatted values and rejects ambiguous or unsafe numbers', () => {
    expect(numericCell('$1,200.50')).toEqual({ value: 1200.5, unit: '$' });
    expect(numericCell('-12.3%')).toEqual({ value: -12.3, unit: '%' });
    for (const text of ['null', '', '2026-11-17', '1,2', 'Infinity', '9007199254740993', '12 USD', '<script>']) expect(numericCell(text)).toBeNull();
    expect(numericColumns({ ...result, rows: [['A', '$10'], ['B', '€12']] })).toEqual([]);
    expect(numericColumns({ ...result, rows: [['A', '10'], ['B', 'null']] })).toEqual([]);
  });
  it('chooses suitable axes including year-based results', () => {
    expect(defaultAxes(result)).toEqual({ dimension: 0, measure: 1 });
    expect(defaultAxes({ ...result, columns: ['Year', 'Count'], rows: [['2025', '12'], ['2026', '3']] })).toEqual({ dimension: 0, measure: 1 });
  });
  it('never charts truncated rows, duplicate categories, missing values or arbitrary text', () => {
    for (const data of [{ ...result, truncated: true }, { ...result, rows: [['A', '12'], ['A', '3']] }, { ...result, rows: [['A', 'null']] }, { ...result, rows: [['A', 'hello']] }]) {
      expect(chartData(data, 0, 1).barReason).not.toBe('');
      expect(chartData(data, 0, 1).pieReason).not.toBe('');
    }
  });
  it('supports negative bar values but refuses negative and all-zero pie charts', () => {
    const negative = chartData({ ...result, rows: [['A', '-12'], ['B', '3']] }, 0, 1);
    expect(negative.barReason).toBe(''); expect(negative.pieReason).not.toBe('');
    const html = renderToStaticMarkup(<BarView points={negative.points} category="Status" measure="Count" />);
    expect(html).toContain('A: -12'); expect(html).not.toContain('width="-');
    expect(chartData({ ...result, rows: [['A', '0'], ['B', '0']] }, 0, 1).pieReason).not.toBe('');
    expect(chartData({ ...result, rows: [['A', '0'], ['B', '12']] }, 0, 1).pieReason).toBe('');
  });
  it('shows percentages based only on returned values with accessible labels', () => {
    const chart = chartData(result, 0, 1);
    const html = renderToStaticMarkup(<PieView points={chart.points} total={chart.total} measure="Count" />);
    expect(html).toContain('Active: 12 (80.0%)'); expect(html).toContain('Share of returned results');
  });
  it('paginates tables without dropping rows and escapes untrusted data', () => {
    const html = renderToStaticMarkup(<GenieResult result={{ ...result, rows: Array.from({ length: 15 }, (_, i) => [`<script>${i}</script>`, String(i)]) }} />);
    expect(html).toContain('1–10 of 15 rows'); expect(html).toContain('Next result rows');
    expect(html).toContain('&lt;script&gt;'); expect(html).not.toContain('<script>');
    expect(html).not.toContain('&lt;script&gt;14');
    expect(renderToStaticMarkup(<GenieResult result={{ ...result, rows: [] }} />)).toContain('No rows returned.');
  });
});
