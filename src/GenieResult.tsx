import { useId, useState } from 'react';
import { BarChart3, PieChart, Table2, ChevronLeft, ChevronRight } from 'lucide-react';
import type { GenieResult as Result } from './types';
import { chartData, defaultAxes, numericColumns } from './genieData';

const colors = ['#d90048', '#5b64cc', '#198781', '#ae6d19', '#994eae', '#3285bb', '#ce653c', '#586e45', '#7d5c91', '#24758c', '#ad4770', '#68728a'];
const compact = (value: number) => new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
type Point = { label: string; raw: string; value: number };

export function BarView({ points, category, measure }: { points: Point[]; category: string; measure: string }) {
  const low = Math.min(0, ...points.map(p => p.value));
  const high = Math.max(0, ...points.map(p => p.value));
  const span = high - low || 1;
  const x = (value: number) => 206 + (value - low) / span * 400;
  const height = points.length * 38 + 38;
  return <div className="genie-chart-scroll" tabIndex={0} aria-label="Bar chart, scroll horizontally if needed">
    <svg className="genie-bar" viewBox={`0 0 710 ${height}`} role="img" aria-label={`${measure} by ${category}`}>
      {Array.from({ length: 5 }, (_, i) => low + span * i / 4).map((tick, i) => <g key={i} className="chart-grid">
        <line x1={x(tick)} x2={x(tick)} y1={8} y2={height - 30} /><text x={x(tick)} y={height - 9} textAnchor="middle">{compact(tick)}</text>
      </g>)}
      <line className="chart-zero" x1={x(0)} x2={x(0)} y1={8} y2={height - 30} />
      {points.map((point, i) => <g key={i}>
        <title>{`${point.label}: ${point.raw}`}</title>
        <text className="chart-category" x={192} y={i * 38 + 27} textAnchor="end">{point.label.length > 25 ? point.label.slice(0, 23) + '…' : point.label}</text>
        <rect x={Math.min(x(0), x(point.value))} y={i * 38 + 10} width={Math.abs(x(point.value) - x(0))} height={25} rx={4} fill={point.value < 0 ? '#5b64cc' : '#d90048'} />
        <text className="chart-value" x={point.value < 0 ? 702 : x(point.value) + 8} y={i * 38 + 27} textAnchor={point.value < 0 ? 'end' : 'start'}>{compact(point.value)}</text>
      </g>)}
    </svg>
  </div>;
}

export function PieView({ points, total, measure }: { points: Point[]; total: number; measure: string }) {
  let offset = 0;
  return <div className="genie-pie-layout">
    <svg viewBox="0 0 240 240" className="genie-pie" role="img" aria-label={`${measure}: share of returned results`}>
      {points.map((point, i) => {
        const share = point.value / total * 100;
        const start = offset; offset += share;
        return <circle key={i} cx={120} cy={120} r={86} fill="none" stroke={colors[i % colors.length]} strokeWidth={34} pathLength={100}
          strokeDasharray={`${share} ${100 - share}`} strokeDashoffset={-start} transform="rotate(-90 120 120)">
          <title>{`${point.label}: ${point.raw} (${share.toFixed(1)}%)`}</title>
        </circle>;
      })}
      <text x={120} y={116} textAnchor="middle" className="pie-total">{compact(total)}</text>
      <text x={120} y={138} textAnchor="middle" className="pie-total-label">Total</text>
    </svg>
    <ul className="genie-legend">{points.map((point, i) => <li key={i}>
      <span className="legend-dot" style={{ backgroundColor: colors[i % colors.length] }} /><span>{point.label}</span>
      <strong>{point.raw}</strong><small>{(point.value / total * 100).toFixed(1)}%</small>
    </li>)}</ul>
    <p className="chart-caption">Share of returned results</p>
  </div>;
}

export default function GenieResult({ result }: { result: Result }) {
  const id = useId();
  const [view, setView] = useState<'table' | 'bar' | 'pie'>('table');
  const [axes, setAxes] = useState(() => defaultAxes(result));
  const [page, setPage] = useState(0);
  const numbers = numericColumns(result);
  const chart = chartData(result, axes.dimension, axes.measure);
  const pageSize = 10;
  const start = page * pageSize;
  const modes = [{ key: 'table', label: 'Table', Icon: Table2 }, { key: 'bar', label: 'Bar', Icon: BarChart3 }, { key: 'pie', label: 'Pie', Icon: PieChart }] as const;
  const reason = view === 'pie' ? chart.pieReason : chart.barReason;
  return <section className="genie-result" aria-labelledby={`${id}-title`}>
    <div className="genie-result-header"><div><span className="genie-result-eyebrow">Genie results</span><h3 id={`${id}-title`}>{result.title}</h3></div>
      <div className="genie-view-switch" role="group" aria-label="Result view">{modes.map(({ key, label, Icon }) =>
        <button type="button" key={key} aria-pressed={view === key} onClick={() => setView(key)}><Icon size={15} />{label}</button>)}</div>
    </div>
    {result.truncated && <p className="genie-result-notice">Partial result · {result.rows.length} rows available. Ask for a smaller result to chart all values.</p>}
    {view === 'table' ? <>
      <div className="genie-table-scroll" tabIndex={0} role="region" aria-label={`${result.title} table`}>
        <table><caption className="sr-only">{result.title}</caption><thead><tr>{result.columns.map((name, i) => <th scope="col" key={i}>{name}</th>)}</tr></thead>
          <tbody>{result.rows.slice(start, start + pageSize).map((row, i) => <tr key={start + i}>{result.columns.map((_, j) => <td key={j} className={numbers.includes(j) ? 'numeric' : ''}>{row[j] || '—'}</td>)}</tr>)}</tbody>
        </table>
        {!result.rows.length && <p className="genie-empty">No rows returned.</p>}
      </div>
      <div className="genie-pagination"><span>{result.rows.length ? `${start + 1}–${Math.min(start + pageSize, result.rows.length)} of ${result.rows.length} rows` : '0 rows'}</span>
        {result.rows.length > pageSize && <div><button type="button" aria-label="Previous result rows" disabled={page === 0} onClick={() => setPage(p => p - 1)}><ChevronLeft size={16} /></button><button type="button" aria-label="Next result rows" disabled={start + pageSize >= result.rows.length} onClick={() => setPage(p => p + 1)}><ChevronRight size={16} /></button></div>}
      </div>
    </> : <>
      <div className="genie-chart-controls">
        <label>Category<select value={axes.dimension} onChange={e => setAxes(a => ({ ...a, dimension: Number(e.target.value) }))}>{axes.dimension < 0 && <option value={-1}>Select category</option>}{result.columns.map((name, i) => <option key={i} value={i}>{name}</option>)}</select></label>
        <label>Value<select value={axes.measure} onChange={e => setAxes(a => ({ ...a, measure: Number(e.target.value) }))}>{axes.measure < 0 && <option value={-1}>No numeric column</option>}{numbers.map(i => <option key={i} value={i}>{result.columns[i]}</option>)}</select></label>
      </div>
      {reason ? <p className="genie-empty" role="status">{reason}</p> : view === 'bar'
        ? <BarView points={chart.points} category={result.columns[axes.dimension]} measure={result.columns[axes.measure]} />
        : <PieView points={chart.points} total={chart.total} measure={result.columns[axes.measure]} />}
    </>}
  </section>;
}
