import React, { useState, useContext, useMemo } from 'react';
import { DataContext } from '../DataContext.js';
import { normCity, StatCard, BrierTrendChart } from '../shared.jsx';

// ---------------------------------------------------------------------------
// EquityCurveChart — running cumulative P&L from closedTrades, sorted by date
// ---------------------------------------------------------------------------
function EquityCurveChart() {
  const M = useContext(DataContext);
  const trades = M.closedTrades;

  const points = useMemo(() => {
    if (!trades || trades.length === 0) return [];
    const sorted = [...trades]
      .filter(t => t.entered_at && t.pnl != null)
      .sort((a, b) => a.entered_at.localeCompare(b.entered_at));
    let cum = 0;
    return sorted.map(t => {
      cum += t.pnl;
      return { date: t.entered_at.slice(0, 10), cum, pnl: t.pnl };
    });
  }, [trades]);

  if (points.length === 0) {
    return (
      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Equity curve</h3>
        <p style={{ color: 'var(--text-faint)', fontSize: 13, fontStyle: 'italic' }}>No closed trades yet.</p>
      </section>
    );
  }

  const W = 900, H = 120, PAD = { top: 12, right: 16, bottom: 8, left: 56 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const cums = points.map(p => p.cum);
  const minC = Math.min(0, ...cums);
  const maxC = Math.max(0, ...cums);
  const range = maxC - minC || 1;

  const xs = points.map((_, i) => PAD.left + (i / Math.max(points.length - 1, 1)) * innerW);
  const toY = c => PAD.top + (1 - (c - minC) / range) * innerH;
  const ys = points.map(p => toY(p.cum));
  const zeroY = toY(0);

  const linePts = xs.map((x, i) => `${x},${ys[i]}`).join(' ');
  const lastCum = cums[cums.length - 1];
  const lineColor = lastCum >= 0 ? '#16a34a' : '#ef4444';

  return (
    <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Equity curve</h3>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}>
        {/* Zero line */}
        {zeroY >= PAD.top && zeroY <= PAD.top + innerH && (
          <line x1={PAD.left} y1={zeroY} x2={W - PAD.right} y2={zeroY}
            stroke="var(--border)" strokeWidth="1" strokeDasharray="4,3" />
        )}
        {/* Equity line */}
        <polyline points={linePts} fill="none" stroke={lineColor} strokeWidth="2" strokeLinejoin="round" />
        {/* Endpoint dot */}
        <circle cx={xs[xs.length - 1]} cy={ys[ys.length - 1]} r="4" fill={lineColor} stroke="white" strokeWidth="2" />
        {/* Y-axis labels */}
        <text x={PAD.left - 6} y={PAD.top + 4} textAnchor="end" fontSize="10" fill="var(--text-faint)" fontFamily="ui-monospace, monospace">
          ${Math.round(maxC)}
        </text>
        <text x={PAD.left - 6} y={PAD.top + innerH + 4} textAnchor="end" fontSize="10" fill="var(--text-faint)" fontFamily="ui-monospace, monospace">
          ${Math.round(minC)}
        </text>
      </svg>
      <div style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 6 }}>
        {points.length} trades · cumulative P&L: <strong style={{ color: lineColor }}>{lastCum >= 0 ? '+' : ''}${lastCum.toFixed(2)}</strong>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// MinEdgeBacktestChart — interactive slider showing P&L if a min-edge filter
// had been applied retrospectively to all closed trades
// ---------------------------------------------------------------------------
function MinEdgeBacktestChart({ threshold, onThresholdChange }) {
  const M = useContext(DataContext);
  const trades = M.closedTrades;

  const result = useMemo(() => {
    const taken = trades.filter(t => t.net_edge != null && t.net_edge * 100 >= threshold);
    const wins = taken.filter(t => t.pnl > 0).length;
    const totalPnl = taken.reduce((s, t) => s + (t.pnl || 0), 0);
    return { taken: taken.length, wins, totalPnl };
  }, [trades, threshold]);

  return (
    <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Min-edge backtest</h3>
      <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
        Simulate what P&L would look like if only trades above a minimum edge threshold had been taken.
      </p>
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 18 }}>
        <label style={{ fontSize: 13, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>Min edge threshold:</label>
        <input
          type="range" min="0" max="60" step="0.5"
          value={threshold}
          onChange={e => onThresholdChange(parseFloat(e.target.value))}
          style={{ flex: 1 }}
        />
        <span style={{ fontSize: 14, fontWeight: 700, fontFamily: 'ui-monospace, monospace', minWidth: 48, color: '#3b82f6' }}>
          {threshold.toFixed(1)}%
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
        <div style={{ padding: '14px 16px', background: 'var(--bg-subtle)', borderRadius: 10 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Trades taken</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{result.taken}</div>
          <div style={{ fontSize: 11, color: 'var(--text-faint)' }}>of {trades.length} total</div>
        </div>
        <div style={{ padding: '14px 16px', background: 'var(--bg-subtle)', borderRadius: 10 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Win rate</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>
            {result.taken > 0 ? ((result.wins / result.taken) * 100).toFixed(0) + '%' : '—'}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-faint)' }}>{result.wins}W / {result.taken - result.wins}L</div>
        </div>
        <div style={{ padding: '14px 16px', background: 'var(--bg-subtle)', borderRadius: 10 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Total P&L</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: result.totalPnl >= 0 ? '#16a34a' : '#ef4444' }}>
            {result.taken > 0 ? (result.totalPnl >= 0 ? '+' : '') + '$' + result.totalPnl.toFixed(2) : '—'}
          </div>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// ForecastHeatmapChart — grid of cities vs Brier score, color-coded
// ---------------------------------------------------------------------------
function ForecastHeatmapChart() {
  const M = useContext(DataContext);
  const cityBrier = M.cityBrier || {};
  const entries = Object.entries(cityBrier);

  if (entries.length === 0) {
    return (
      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Forecast heatmap</h3>
        <p style={{ color: 'var(--text-faint)', fontSize: 13, fontStyle: 'italic' }}>No city Brier data yet.</p>
      </section>
    );
  }

  function cellColor(b) {
    if (b == null) return { bg: 'var(--bg-muted)', text: 'var(--text-faint)' };
    if (b < 0.20) return { bg: 'rgba(34,197,94,0.15)', text: '#16a34a' };
    if (b < 0.30) return { bg: 'rgba(234,179,8,0.15)', text: '#ca8a04' };
    return { bg: 'rgba(239,68,68,0.15)', text: '#ef4444' };
  }

  return (
    <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Forecast heatmap</h3>
      <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
        Brier score per city. Green &lt;0.20 (good), yellow &lt;0.30 (fair), red ≥0.30 (poor).
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10 }}>
        {entries.sort((a, b) => Number(a[1]) - Number(b[1])).map(([city, brier]) => {
          const b = brier != null ? Number(brier) : null;
          const { bg, text } = cellColor(b);
          return (
            <div key={city} style={{
              padding: '12px 14px', borderRadius: 10,
              background: bg, border: '1px solid var(--border)',
            }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>{normCity(city)}</div>
              <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'ui-monospace, monospace', color: text }}>
                {b != null ? b.toFixed(3) : '—'}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ display: 'flex', gap: 16, marginTop: 12, fontSize: 11, color: 'var(--text-faint)' }}>
        <span style={{ color: '#16a34a' }}>● &lt;0.20 good</span>
        <span style={{ color: '#ca8a04' }}>● &lt;0.30 fair</span>
        <span style={{ color: '#ef4444' }}>● ≥0.30 poor</span>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// CalendarPnLChart — last 12 weeks of P&L, color-coded green/red by week total
// ---------------------------------------------------------------------------
function CalendarPnLChart() {
  const M = useContext(DataContext);
  const trades = M.closedTrades;

  // Group closed trades by ISO week (Monday-based), take last 12 weeks
  const weeks = useMemo(() => {
    if (!trades || trades.length === 0) return [];

    function getWeekKey(dateStr) {
      const d = new Date(dateStr);
      // Find Monday of that week
      const day = d.getDay();
      const diff = (day === 0 ? -6 : 1 - day);
      const mon = new Date(d);
      mon.setDate(d.getDate() + diff);
      return mon.toISOString().slice(0, 10);
    }

    const map = {};
    trades.forEach(t => {
      if (!t.entered_at || t.pnl == null) return;
      const wk = getWeekKey(t.entered_at);
      if (!map[wk]) map[wk] = { week: wk, pnl: 0, count: 0 };
      map[wk].pnl += t.pnl;
      map[wk].count += 1;
    });

    return Object.values(map)
      .sort((a, b) => a.week.localeCompare(b.week))
      .slice(-12);
  }, [trades]);

  if (weeks.length === 0) {
    return (
      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Weekly P&L calendar</h3>
        <p style={{ color: 'var(--text-faint)', fontSize: 13, fontStyle: 'italic' }}>No closed trades yet.</p>
      </section>
    );
  }

  const maxAbs = Math.max(...weeks.map(w => Math.abs(w.pnl)), 1);

  return (
    <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Weekly P&L calendar</h3>
      <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
        Last {weeks.length} week{weeks.length !== 1 ? 's' : ''} of closed-trade P&L.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))', gap: 8 }}>
        {weeks.map(w => {
          const intensity = Math.min(0.8, (Math.abs(w.pnl) / maxAbs) * 0.6 + 0.1);
          const bg = w.pnl >= 0
            ? `rgba(34,197,94,${intensity})`
            : `rgba(239,68,68,${intensity})`;
          const textColor = w.pnl >= 0 ? '#14532d' : '#7f1d1d';
          const weekLabel = new Date(w.week).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
          return (
            <div key={w.week} style={{
              padding: '10px 12px', borderRadius: 8, background: bg,
              border: '1px solid transparent',
            }}>
              <div style={{ fontSize: 10, color: textColor, opacity: 0.8, marginBottom: 3 }}>{weekLabel}</div>
              <div style={{ fontSize: 14, fontWeight: 700, fontFamily: 'ui-monospace, monospace', color: textColor }}>
                {w.pnl >= 0 ? '+' : ''}{w.pnl.toFixed(2)}
              </div>
              <div style={{ fontSize: 10, color: textColor, opacity: 0.7, marginTop: 2 }}>{w.count} trade{w.count !== 1 ? 's' : ''}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// SamedayCalibCard — same-day METAR calibration, completely isolated from
// the multi-day calibration views above.  Shows:
//   1. Calibration curve: predicted prob vs actual outcome rate per bucket
//   2. Time-of-day bias bars: morning/afternoon/evening mean_prob vs mean_actual
// Neither chart shares data or state with the multi-day views.
// ---------------------------------------------------------------------------
function SamedayCalibCard() {
  const M = useContext(DataContext);
  const sd = M.samedayCalibration;

  if (!sd) return null;

  const { n, gate, gate_met, brier, t_sameday, calibration_buckets, by_time_of_day } = sd;
  const buckets = calibration_buckets || [];
  const tod = by_time_of_day || {};

  const brierColor = brier == null ? '#8b949e' : brier < 0.20 ? '#16a34a' : brier < 0.30 ? '#ca8a04' : '#ef4444';

  // Calibration chart — SVG scatter of (predicted_mean, actual_rate) dots with a diagonal
  const W = 320, H = 220, PAD = { top: 16, right: 16, bottom: 36, left: 44 };
  const iW = W - PAD.left - PAD.right;
  const iH = H - PAD.top - PAD.bottom;
  const toX = p => PAD.left + p * iW;
  const toY = p => PAD.top + (1 - p) * iH;

  // Time-of-day slot ordering and labels — must match tod_slots in tracker.py
  const TOD_ORDER = ['night', 'morning', 'afternoon', 'evening'];
  const TOD_LABELS = { night: 'Night (0–5)', morning: 'Morning (6–11)', afternoon: 'Afternoon (12–17)', evening: 'Evening (18+)' };
  const TOD_HINT = {
    night:     'Pre-dawn placement — temperature still well below daily max; strong underestimation expected',
    morning:   'Temp still rising → model tends to underestimate daily high (negative bias)',
    afternoon: 'Near daily peak → most reliable window',
    evening:   'Temp falling after peak → model may overestimate remaining YES chance (positive bias)',
  };

  return (
    <section style={{
      background: 'var(--bg-card)', border: '1px solid var(--border)',
      borderRadius: 14, padding: '20px', marginBottom: 18,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Same-Day METAR Calibration</h3>
        <span style={{
          fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 10,
          background: gate_met ? 'rgba(34,197,94,0.12)' : 'rgba(234,179,8,0.12)',
          color: gate_met ? '#16a34a' : '#ca8a04',
        }}>
          {n}/{gate} samples{gate_met ? ' — trained' : ' — gate not met'}
        </span>
      </div>
      <p style={{ margin: '0 0 16px', color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.4 }}>
        METAR-locked predictions only (days_out=0). Completely separate from multi-day ensemble calibration.
        Gate for T_sameday training: {gate} settled same-day trades.
      </p>

      {n === 0 ? (
        <p style={{ color: 'var(--text-faint)', fontSize: 13, fontStyle: 'italic' }}>
          No settled same-day trades yet — first batch settles after tonight.
        </p>
      ) : (
        <>
          {/* Summary stats row */}
          <div style={{ display: 'flex', gap: 16, marginBottom: 20, flexWrap: 'wrap' }}>
            <div style={{ padding: '12px 16px', background: 'var(--bg-subtle)', borderRadius: 10, minWidth: 110 }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>Brier (same-day)</div>
              <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'ui-monospace, monospace', color: brierColor }}>
                {brier != null ? brier.toFixed(3) : '—'}
              </div>
            </div>
            <div style={{ padding: '12px 16px', background: 'var(--bg-subtle)', borderRadius: 10, minWidth: 110 }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>T_sameday</div>
              <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'ui-monospace, monospace', color: 'var(--text)' }}>
                {t_sameday != null ? t_sameday.toFixed(2) : 'untrained'}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-faint)' }}>
                {t_sameday == null ? 'needs ' + gate + ' settled' : Math.abs(t_sameday - 1.0) < 0.01 ? 'identity (no compression)' : 'calibration active'}
              </div>
            </div>
            <div style={{ padding: '12px 16px', background: 'var(--bg-subtle)', borderRadius: 10, minWidth: 110 }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>Settled trades</div>
              <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>{n}</div>
              <div style={{ fontSize: 10, color: 'var(--text-faint)' }}>days_out = 0 only</div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: 24 }}>
            {/* Calibration curve SVG */}
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: 'var(--text-muted)' }}>
                Calibration curve (predicted vs actual)
              </div>
              <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}>
                {/* Axes */}
                <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={PAD.top + iH}
                  stroke="var(--border)" strokeWidth="1" />
                <line x1={PAD.left} y1={PAD.top + iH} x2={PAD.left + iW} y2={PAD.top + iH}
                  stroke="var(--border)" strokeWidth="1" />
                {/* Perfect calibration diagonal */}
                <line x1={toX(0)} y1={toY(0)} x2={toX(1)} y2={toY(1)}
                  stroke="rgba(99,102,241,0.35)" strokeWidth="1.5" strokeDasharray="5,3" />
                {/* Axis labels */}
                <text x={PAD.left - 6} y={toY(1.0) + 4} textAnchor="end" fontSize="9" fill="var(--text-faint)" fontFamily="ui-monospace, monospace">1.0</text>
                <text x={PAD.left - 6} y={toY(0.5) + 4} textAnchor="end" fontSize="9" fill="var(--text-faint)" fontFamily="ui-monospace, monospace">0.5</text>
                <text x={PAD.left - 6} y={toY(0.0) + 4} textAnchor="end" fontSize="9" fill="var(--text-faint)" fontFamily="ui-monospace, monospace">0.0</text>
                <text x={toX(0.0)} y={PAD.top + iH + 14} textAnchor="middle" fontSize="9" fill="var(--text-faint)" fontFamily="ui-monospace, monospace">0.0</text>
                <text x={toX(0.5)} y={PAD.top + iH + 14} textAnchor="middle" fontSize="9" fill="var(--text-faint)" fontFamily="ui-monospace, monospace">0.5</text>
                <text x={toX(1.0)} y={PAD.top + iH + 14} textAnchor="middle" fontSize="9" fill="var(--text-faint)" fontFamily="ui-monospace, monospace">1.0</text>
                {/* X axis label */}
                <text x={PAD.left + iW / 2} y={H - 2} textAnchor="middle" fontSize="9" fill="var(--text-faint)">Predicted prob</text>
                {/* Calibration dots — sized by n */}
                {buckets.map((b, i) => {
                  const cx = toX(b.predicted_mean);
                  const cy = toY(b.actual_rate);
                  const r = Math.max(5, Math.min(14, 4 + b.n * 1.5));
                  const isAboveDiag = b.actual_rate > b.predicted_mean;
                  const dotColor = isAboveDiag ? '#16a34a' : '#ef4444';
                  return (
                    <g key={i}>
                      <circle cx={cx} cy={cy} r={r} fill={dotColor} fillOpacity={0.75} stroke="white" strokeWidth="1.5" />
                      <text x={cx} y={cy + 4} textAnchor="middle" fontSize="9" fill="white" fontWeight="700">{b.n}</text>
                    </g>
                  );
                })}
                {buckets.length === 0 && (
                  <text x={PAD.left + iW / 2} y={PAD.top + iH / 2} textAnchor="middle"
                    fontSize="11" fill="var(--text-faint)" fontStyle="italic">No data yet</text>
                )}
              </svg>
              <div style={{ fontSize: 10, color: 'var(--text-faint)', marginTop: 4 }}>
                Dot size = sample count · diagonal = perfect calibration
              </div>
            </div>

            {/* Time-of-day bias */}
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: 'var(--text-muted)' }}>
                Time-of-day bias (predicted vs actual)
              </div>
              {TOD_ORDER.filter(slot => tod[slot]).length === 0 ? (
                <p style={{ fontSize: 12, color: 'var(--text-faint)', fontStyle: 'italic' }}>
                  No local_hour data yet — trades placed before the field was logged.
                </p>
              ) : (
                TOD_ORDER.filter(slot => tod[slot]).map(slot => {
                  const s = tod[slot];
                  const bias = s.bias;
                  const absMax = 0.30; // fixed scale so bars are comparable across sessions
                  const barPct = Math.min(100, (Math.abs(bias) / absMax) * 100);
                  const biasColor = bias > 0.05 ? '#ef4444' : bias < -0.05 ? '#3b82f6' : '#16a34a';
                  const biasLabel = bias > 0.05 ? 'overestimates' : bias < -0.05 ? 'underestimates' : 'well-calibrated';
                  return (
                    <div key={slot} style={{ marginBottom: 14 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 3 }}>
                        <span style={{ fontSize: 12, fontWeight: 600 }}>{TOD_LABELS[slot]}</span>
                        <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>n={s.n}</span>
                      </div>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
                        {/* Bias bar centered at 0 */}
                        <div style={{ flex: 1, height: 8, background: 'var(--bg-muted)', borderRadius: 4, position: 'relative', overflow: 'visible' }}>
                          {/* Center marker */}
                          <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: 'var(--border)' }} />
                          {/* Bias fill */}
                          <div style={{
                            position: 'absolute',
                            top: 0, bottom: 0, borderRadius: 4,
                            left: bias >= 0 ? '50%' : `${50 - barPct / 2}%`,
                            width: `${barPct / 2}%`,
                            background: biasColor,
                          }} />
                        </div>
                        <span style={{
                          fontSize: 11, fontWeight: 700, fontFamily: 'ui-monospace, monospace',
                          color: biasColor, minWidth: 48, textAlign: 'right',
                        }}>
                          {bias >= 0 ? '+' : ''}{bias.toFixed(3)}
                        </span>
                      </div>
                      <div style={{ display: 'flex', gap: 16, fontSize: 10, color: 'var(--text-faint)', marginBottom: 2 }}>
                        <span>pred {s.mean_prob.toFixed(2)} · actual {s.mean_actual.toFixed(2)}</span>
                        <span style={{ color: biasColor }}>{biasLabel}</span>
                      </div>
                      <div style={{ fontSize: 10, color: 'var(--text-faint)', lineHeight: 1.4, fontStyle: 'italic' }}>
                        {TOD_HINT[slot]}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// MultiDayCalibCard — multi-day temperature-scaling calibration gate status.
// Shows when calibration last ran (at N trades) and when next run is eligible.
// Analogous to SamedayCalibCard but for the multi-day ensemble.
// ---------------------------------------------------------------------------
function MultiDayCalibCard() {
  const M = useContext(DataContext);
  const cal = M.calibrationStatus;
  if (!cal) return null;

  const { last_calibration_n, current_n, next_eligible_n, eligible, T_global, T_between } = cal;
  const progress = next_eligible_n > 0 ? Math.min(100, (current_n / next_eligible_n) * 100) : 100;

  return (
    <section style={{
      background: 'var(--bg-card)', border: '1px solid var(--border)',
      borderRadius: 14, padding: '20px', marginBottom: 18,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Multi-Day Calibration Gate</h3>
        <span style={{
          fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 10,
          background: eligible ? 'rgba(34,197,94,0.12)' : 'rgba(234,179,8,0.12)',
          color: eligible ? '#16a34a' : '#ca8a04',
        }}>
          {eligible ? 'eligible — run calibrate' : `${current_n}/${next_eligible_n} trades`}
        </span>
      </div>
      <p style={{ margin: '0 0 16px', color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.4 }}>
        Multi-day temperature scaling (T_global, T_between). Gate: 50 first run, then every 25 new settled trades.
        {last_calibration_n != null ? ` Last run at ${last_calibration_n} settled.` : ' Never run yet.'}
      </p>

      {/* Progress toward next eligible run */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
          <span style={{ fontWeight: 600 }}>Progress to next eligible run</span>
          <span style={{ fontFamily: 'ui-monospace, monospace', color: eligible ? '#16a34a' : 'var(--text-muted)' }}>
            {current_n} / {next_eligible_n} settled
          </span>
        </div>
        <div style={{ height: 8, background: 'var(--bg-muted)', borderRadius: 4, overflow: 'hidden' }}>
          <div style={{
            width: progress + '%', height: '100%',
            background: eligible ? '#16a34a' : '#3b82f6', transition: 'width 0.4s',
          }} />
        </div>
      </div>

      {/* Current T values */}
      <div style={{ display: 'flex', gap: 12 }}>
        <div style={{ padding: '12px 16px', background: 'var(--bg-subtle)', borderRadius: 10, minWidth: 110 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>T_global</div>
          <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>
            {T_global != null ? T_global.toFixed(2) : '—'}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-faint)' }}>
            {T_global == null ? 'not calibrated' : T_global > 1 ? 'sharpening probs' : 'flattening probs'}
          </div>
        </div>
        <div style={{ padding: '12px 16px', background: 'var(--bg-subtle)', borderRadius: 10, minWidth: 110 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>T_between</div>
          <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>
            {T_between != null ? T_between.toFixed(2) : '—'}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-faint)' }}>between markets only</div>
        </div>
        {last_calibration_n != null && (
          <div style={{ padding: '12px 16px', background: 'var(--bg-subtle)', borderRadius: 10, minWidth: 110 }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>Last ran at</div>
            <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>{last_calibration_n}</div>
            <div style={{ fontSize: 10, color: 'var(--text-faint)' }}>settled trades</div>
          </div>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// CityPnLChart — total P&L and win rate by city, derived from closedTrades.
// Complements ForecastHeatmapChart (which shows Brier) with financial outcomes.
// ---------------------------------------------------------------------------
function CityPnLChart() {
  const M = useContext(DataContext);

  const cityData = useMemo(() => {
    if (!M.closedTrades || M.closedTrades.length === 0) return [];
    const map = {};
    M.closedTrades.forEach(t => {
      const city = t.city || 'Unknown';
      if (!map[city]) map[city] = { city, pnl: 0, wins: 0, total: 0 };
      map[city].pnl += t.pnl || 0;
      map[city].total += 1;
      if ((t.pnl || 0) > 0) map[city].wins += 1;
    });
    return Object.values(map).sort((a, b) => b.pnl - a.pnl);
  }, [M.closedTrades]);

  if (cityData.length === 0) {
    return (
      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 8 }}>City P&L</h3>
        <p style={{ color: 'var(--text-faint)', fontSize: 13, fontStyle: 'italic' }}>No closed trades yet.</p>
      </section>
    );
  }

  const maxAbsPnl = Math.max(1, ...cityData.map(c => Math.abs(c.pnl)));

  return (
    <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>City P&L</h3>
      <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
        Total P&L and win rate per city across all settled trades.
      </p>
      <div style={{ display: 'grid', gap: 8 }}>
        {cityData.map(c => {
          const barPct = (Math.abs(c.pnl) / maxAbsPnl) * 100;
          const isPos = c.pnl >= 0;
          const winRate = c.total > 0 ? (c.wins / c.total) * 100 : 0;
          return (
            <div key={c.city}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                <span style={{ fontWeight: 600 }}>{normCity(c.city)}</span>
                <span style={{ fontFamily: 'ui-monospace, monospace', color: isPos ? '#16a34a' : '#ef4444' }}>
                  {isPos ? '+' : ''}${c.pnl.toFixed(2)}&nbsp;
                  <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>
                    {winRate.toFixed(0)}% ({c.wins}W/{c.total - c.wins}L)
                  </span>
                </span>
              </div>
              <div style={{ height: 6, background: 'var(--bg-muted)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{
                  width: barPct + '%', height: '100%',
                  background: isPos ? '#16a34a' : '#ef4444',
                }} />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// MarketTypeSplitCard — win rate and P&L split by market type.
// Above/below threshold tickers contain '-T' before the threshold value.
// Between tickers contain '-B' before the low end of the range.
// ---------------------------------------------------------------------------
function MarketTypeSplitCard() {
  const M = useContext(DataContext);

  const { threshold, between } = useMemo(() => {
    const t = { wins: 0, total: 0, pnl: 0 };
    const b = { wins: 0, total: 0, pnl: 0 };
    (M.closedTrades || []).forEach(trade => {
      // Between tickers have '-B' immediately before a digit (e.g., -B70.5)
      // Above/below tickers use '-T' before the threshold digit (e.g., -T74)
      const isBetween = trade.ticker && /-B\d/.test(trade.ticker);
      const bucket = isBetween ? b : t;
      bucket.total += 1;
      bucket.pnl += trade.pnl || 0;
      if ((trade.pnl || 0) > 0) bucket.wins += 1;
    });
    return { threshold: t, between: b };
  }, [M.closedTrades]);

  if (threshold.total === 0 && between.total === 0) {
    return (
      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Market type split</h3>
        <p style={{ color: 'var(--text-faint)', fontSize: 13, fontStyle: 'italic' }}>No closed trades yet.</p>
      </section>
    );
  }

  const types = [
    { label: 'Above / Below threshold', key: 'threshold', data: threshold, color: '#3b82f6' },
    { label: 'Between range', key: 'between', data: between, color: '#8b5cf6' },
  ];

  return (
    <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Market type split</h3>
      <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
        Above/below = single-threshold markets (-T). Between = range markets (-B). Performance differs: between markets have higher model uncertainty.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {types.map(({ label, key, data, color }) => {
          const winRate = data.total > 0 ? (data.wins / data.total) * 100 : null;
          return (
            <div key={key} style={{ padding: '16px', background: 'var(--bg-subtle)', borderRadius: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 12, color }}>{label}</div>
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--text-faint)', marginBottom: 2 }}>Trades</div>
                  <div style={{ fontSize: 20, fontWeight: 700 }}>{data.total}</div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--text-faint)', marginBottom: 2 }}>Win rate</div>
                  <div style={{ fontSize: 20, fontWeight: 700 }}>
                    {winRate != null ? winRate.toFixed(0) + '%' : '—'}
                  </div>
                  {data.total > 0 && (
                    <div style={{ fontSize: 10, color: 'var(--text-faint)' }}>{data.wins}W / {data.total - data.wins}L</div>
                  )}
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--text-faint)', marginBottom: 2 }}>P&L</div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: data.pnl >= 0 ? '#16a34a' : '#ef4444' }}>
                    {data.total > 0 ? (data.pnl >= 0 ? '+' : '') + '$' + data.pnl.toFixed(2) : '—'}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// SameDayPerfCard — same-day (days_out=0, METAR-locked) trades vs multi-day
// ensemble trades, side by side. Re-enabled Jun 2 but had no dedicated view.
// ---------------------------------------------------------------------------
function SameDayPerfCard() {
  const M = useContext(DataContext);

  const sameDayTrades = (M.closedTrades || []).filter(t => t.days_out === 0);
  // null days_out means an old multi-day trade placed before the field was stored
  const multiDayTrades = (M.closedTrades || []).filter(t => t.days_out !== 0);

  if (sameDayTrades.length === 0) {
    return (
      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Same-day performance</h3>
        <p style={{ color: 'var(--text-faint)', fontSize: 13, fontStyle: 'italic' }}>No settled same-day trades yet.</p>
      </section>
    );
  }

  function calcStats(trades) {
    const wins = trades.filter(t => t.pnl > 0).length;
    const totalPnl = trades.reduce((s, t) => s + (t.pnl || 0), 0);
    const withEdge = trades.filter(t => t.net_edge != null);
    const avgEdge = withEdge.length > 0
      ? withEdge.reduce((s, t) => s + t.net_edge, 0) / withEdge.length
      : null;
    return { count: trades.length, wins, losses: trades.length - wins, totalPnl, avgEdge };
  }

  const sd = calcStats(sameDayTrades);
  const md = calcStats(multiDayTrades);

  const types = [
    { label: 'Same-day (METAR)', color: '#3b82f6', d: sd },
    { label: 'Multi-day (ensemble)', color: '#8b5cf6', d: md },
  ];

  return (
    <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Same-day performance</h3>
      <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
        METAR-locked same-day trades (days_out=0) vs multi-day ensemble trades. Avg edge compares only trades with edge data.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {types.map(({ label, color, d }) => {
          const winRate = d.count > 0 ? ((d.wins / d.count) * 100).toFixed(0) + '%' : '—';
          const pnlStr = d.count > 0 ? (d.totalPnl >= 0 ? '+' : '') + '$' + d.totalPnl.toFixed(2) : '—';
          const edgeStr = d.avgEdge != null ? (d.avgEdge * 100).toFixed(1) + '%' : '—';
          return (
            <div key={label} style={{ padding: '16px', background: 'var(--bg-subtle)', borderRadius: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 12, color }}>{label}</div>
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--text-faint)', marginBottom: 2 }}>Trades</div>
                  <div style={{ fontSize: 20, fontWeight: 700 }}>{d.count}</div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--text-faint)', marginBottom: 2 }}>Win rate</div>
                  <div style={{ fontSize: 20, fontWeight: 700 }}>{winRate}</div>
                  {d.count > 0 && <div style={{ fontSize: 10, color: 'var(--text-faint)' }}>{d.wins}W / {d.losses}L</div>}
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--text-faint)', marginBottom: 2 }}>P&L</div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: d.count > 0 ? (d.totalPnl >= 0 ? '#16a34a' : '#ef4444') : 'var(--text)' }}>
                    {pnlStr}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--text-faint)', marginBottom: 2 }}>Avg edge</div>
                  <div style={{ fontSize: 20, fontWeight: 700 }}>{edgeStr}</div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// Bucket definitions for the edge histogram — 5% intervals starting at 15%.
// Kept module-level so they aren't re-created on each render.
const EDGE_BUCKETS = [
  { label: '<15%',   min: -Infinity, max: 0.15   },
  { label: '15–20%', min: 0.15,      max: 0.20   },
  { label: '20–25%', min: 0.20,      max: 0.25   },
  { label: '25–30%', min: 0.25,      max: 0.30   },
  { label: '30–35%', min: 0.30,      max: 0.35   },
  { label: '35%+',   min: 0.35,      max: Infinity },
];

// ---------------------------------------------------------------------------
// EdgeHistogram — horizontal bar chart of net_edge distribution across closed
// trades. Buckets at 5% intervals; green for high-conviction (≥25%) buckets.
// ---------------------------------------------------------------------------
function EdgeHistogram() {
  const M = useContext(DataContext);

  const bucketCounts = useMemo(() => {
    const trades = (M.closedTrades || []).filter(t => t.net_edge != null);
    if (trades.length === 0) return null;
    return EDGE_BUCKETS.map(b => ({
      label: b.label,
      min: b.min,
      count: trades.filter(t => t.net_edge >= b.min && t.net_edge < b.max).length,
    }));
  }, [M.closedTrades]);

  if (!bucketCounts) {
    return (
      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Edge distribution</h3>
        <p style={{ color: 'var(--text-faint)', fontSize: 13, fontStyle: 'italic' }}>No trades with edge data yet.</p>
      </section>
    );
  }

  const maxCount = Math.max(1, ...bucketCounts.map(b => b.count));

  return (
    <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Edge distribution</h3>
      <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
        Distribution of net_edge across closed trades. Green bars (≥25%) are the high-conviction range.
      </p>
      <div style={{ display: 'grid', gap: 8 }}>
        {bucketCounts.map(b => {
          const barPct = (b.count / maxCount) * 100;
          // Buckets with min >= 0.25 are the high-conviction range → green
          const color = b.min >= 0.25 ? '#16a34a' : '#3b82f6';
          return (
            <div key={b.label} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ width: 54, fontSize: 11, fontWeight: 500, color: 'var(--text-muted)', flexShrink: 0, textAlign: 'right' }}>
                {b.label}
              </span>
              <div style={{ flex: 1, height: 20, background: 'var(--bg-muted)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{ width: barPct + '%', height: '100%', background: color, borderRadius: 4 }} />
              </div>
              <span style={{ fontSize: 11, fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)', minWidth: 24, flexShrink: 0 }}>
                {b.count}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// AnalyticsTab — empty-state banner when post-wipe data is absent
// ---------------------------------------------------------------------------
export default function AnalyticsTab() {
  const M = useContext(DataContext);
  const isEmpty = M.stats.brier == null || M.stats.settled_count < 5;

  // Chart state
  const [minEdgeThreshold, setMinEdgeThreshold] = useState(15.0);

  return (
    <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
      <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Analytics</h1>
      <p style={{ margin: '0 0 16px', color: 'var(--text-muted)', fontSize: 13 }}>
        Performance, P&amp;L attribution, model comparison, calibration.
      </p>

      {isEmpty && (
        <div style={{
          padding: '14px 18px', borderRadius: 10, marginBottom: 18,
          background: 'rgba(234,179,8,0.08)', border: '1px solid rgba(234,179,8,0.3)',
          color: '#92400e', fontSize: 13, lineHeight: 1.5,
        }}>
          📊 <strong>Demo values shown</strong> — real analytics will appear after enough settled trades accumulate. Brier, AUC, and attribution are all computed from outcomes; there aren't enough yet.
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
        <StatCard label="Total P&L" tooltip="Cumulative P&L across all settled trades."
          value={M.stats.month_pnl != null ? (M.stats.month_pnl >= 0 ? '+' : '') + '$' + Number(M.stats.month_pnl).toFixed(2) : '—'}
          sub={M.stats.settled_count + ' settled trades'} />
        <StatCard label="Win rate" tooltip="% of settled trades that were profitable."
          value={M.stats.win_rate != null ? (Number(M.stats.win_rate) * 100).toFixed(1) + '%' : '—'} />
        <StatCard label="AUC" tooltip="Area under ROC curve. 0.5 = random, 1.0 = perfect. Above 0.70 is solid."
          value={M.auc != null ? Number(M.auc).toFixed(3) : '—'} sub="ROC area" />
        <StatCard label="Avg price improve" tooltip="Avg cents better than displayed ask on fills."
          value={M.priceImprovement?.total_trades > 0 ? '+' + Number(M.priceImprovement.avg_improvement_cents).toFixed(2) + '¢' : '—'}
          sub={M.priceImprovement?.total_trades > 0 ? Number(M.priceImprovement.positive_pct).toFixed(0) + '% positive' : 'No real fills yet'} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, marginBottom: 18 }}>
        <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px' }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Brier by model source</h3>
          <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
            Per-source Brier score based on dominant blend model at prediction time.
          </p>
          {M.brierBySource && Object.keys(M.brierBySource).length > 0 ? (
            Object.entries(M.brierBySource)
              .sort((a, b) => a[1].brier - b[1].brier)
              .map(([src, val]) => {
                const b = Number(val.brier);
                const color = b < 0.20 ? '#16a34a' : b < 0.30 ? '#ca8a04' : '#ef4444';
                const barW = Math.max(0, Math.min(100, ((0.35 - b) / 0.35) * 100));
                return (
                  <div key={src} style={{ marginBottom: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                      <span style={{ fontWeight: 600 }}>{src.toUpperCase()}</span>
                      <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, fontWeight: 700, color }}>
                        {b.toFixed(3)} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>n={val.n}</span>
                      </span>
                    </div>
                    <div style={{ height: 6, background: 'var(--bg-muted)', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{ width: barW + '%', height: '100%', background: color }} />
                    </div>
                  </div>
                );
              })
          ) : (
            <p style={{ color: 'var(--text-faint)', fontSize: 12, fontStyle: 'italic' }}>
              No data yet — requires settled trades with blend source metadata.
            </p>
          )}
        </section>

        <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px' }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Brier by days out</h3>
          <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
            Accuracy degrades with horizon. 1–2 days out is strongest.
          </p>
          {Object.entries(M.brierByDays || {}).map(([day, brier]) => {
            const b = brier != null ? Number(brier) : null;
            const color = b == null ? '#8b949e' : b < 0.20 ? '#16a34a' : b < 0.30 ? '#ca8a04' : '#ef4444';
            const barW = b != null ? Math.max(0, Math.min(100, ((0.35 - b) / 0.35) * 100)) : 0;
            // Backend returns string bucket keys ('same_day', '1-2d') rather than integer keys,
            // so we map them to readable labels instead of blindly appending "days out".
            const dayLabel = day === 'same_day' ? 'Same Day'
              : day === '1-2d' ? '1-2 Days'
              : `${day} day${day !== '1' ? 's' : ''} out`;
            return (
              <div key={day} style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                  <span style={{ fontWeight: 600 }}>{dayLabel}</span>
                  <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, fontWeight: 700, color }}>{b != null ? b.toFixed(3) : '—'}</span>
                </div>
                <div style={{ height: 6, background: 'var(--bg-muted)', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{ width: barW + '%', height: '100%', background: color }} />
                </div>
              </div>
            );
          })}
        </section>
      </div>

      {/* Brier score trend — show empty-state card rather than silently rendering nothing */}
      {Array.isArray(M.brierHistory) && M.brierHistory.length > 1 ? (
        <BrierTrendChart hist={M.brierHistory} />
      ) : (
        <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Weekly Brier trend</h3>
          <p style={{ color: 'var(--text-faint)', fontSize: 13, fontStyle: 'italic' }}>No weekly history yet — needs 2+ weeks of settled data.</p>
        </section>
      )}

      {/* Charts */}
      <EquityCurveChart />
      <MinEdgeBacktestChart threshold={minEdgeThreshold} onThresholdChange={setMinEdgeThreshold} />
      <ForecastHeatmapChart />
      {/* City P&L alongside the Brier heatmap — financial view of the same cities */}
      <CityPnLChart />
      <CalendarPnLChart />
      {/* Market type split — between vs threshold performance comparison */}
      <MarketTypeSplitCard />
      {/* Same-day METAR vs multi-day ensemble performance breakdown */}
      <SameDayPerfCard />
      {/* Net edge histogram — shows whether edge is concentrated or spread out */}
      <EdgeHistogram />

      {/* Calibration cards — same-day and multi-day side by side */}
      <SamedayCalibCard />
      <MultiDayCalibCard />

      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden' }}>
        <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)' }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>City calibration detail</h3>
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 12 }}>
              {['City', 'N', 'Brier', 'Bias'].map(h => (
                <th key={h} style={{ padding: '12px 16px', textAlign: h === 'City' ? 'left' : 'right', fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(M.cityCalibration || {}).map(([city, cal]) => (
              <tr key={city} style={{ borderBottom: '1px solid var(--bg-muted)' }}>
                <td style={{ padding: '12px 16px', fontWeight: 600 }}>{normCity(city)}</td>
                <td style={{ padding: '12px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>{cal.n ?? '—'}</td>
                <td style={{ padding: '12px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: (Number(cal.brier) || 1) < 0.20 ? '#16a34a' : '#ca8a04' }}>{cal.brier != null ? Number(cal.brier).toFixed(3) : '—'}</td>
                <td style={{ padding: '12px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)' }}>
                  {cal.bias != null ? (cal.bias >= 0 ? '+' : '') + Number(cal.bias).toFixed(3) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}
