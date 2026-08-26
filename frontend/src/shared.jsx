import React, { useState, useEffect, useRef } from 'react';
import { authHeader, timeoutSignal, API_TIMEOUT_MS } from './useData.js';

// ---------------------------------------------------------------------------
// City display-name normalization  (backend uses CamelCase keys)
// ---------------------------------------------------------------------------
export const CITY_NAMES = {
  SanFrancisco: 'San Francisco',
  NYC: 'New York',
  OklahomaCity: 'Oklahoma City',
  SanAntonio: 'San Antonio',
  Washington: 'Washington DC',
};

// Convert a camelCase city key to a human-readable display name.
export const normCity = (c) => CITY_NAMES[c] || c;

// net_edge is stored as a ratio and can exceed 1.0, so cap display at ">100%".
export const fmtEdge = (e) => (e >= 1 ? '>100%' : `+${(e * 100).toFixed(1)}%`);

// fmtSigned — sign + colour for any signed value already in display units
// (percent points, dollars, etc). Unlike fmtEdge (which assumes its input is
// always >= 0), this derives BOTH the leading sign and the colour from the
// value's actual magnitude, so a negative value never renders with a
// hardcoded '+' and green -- the exact H-4 bug (batch-42).
export function fmtSigned(value, decimals = 1, suffix = '%') {
  return {
    text: `${value >= 0 ? '+' : ''}${value.toFixed(decimals)}${suffix}`,
    color: value >= 0 ? '#16a34a' : '#ef4444',
  };
}

// Build a direct Kalshi market URL so users can jump to the market page.
// The series is the ticker prefix before the first hyphen (e.g. kxhighny from KXHIGHNY-26JUL04-T72).
export function kalshiMarketUrl(ticker) {
  if (!ticker) return null;
  const series = ticker.split('-')[0].toLowerCase();
  return `https://kalshi.com/markets/${series}/${ticker.toUpperCase()}`;
}

// ---------------------------------------------------------------------------
// outcomeBadge — derive badge style from settled trade outcome field
// ---------------------------------------------------------------------------
export function outcomeBadge(outcome, pnl) {
  if (outcome === 'yes')        return { bg: 'rgba(34,197,94,0.12)',  color: '#16a34a',        label: 'YES' };
  if (outcome === 'no')         return { bg: 'rgba(239,68,68,0.12)',  color: '#ef4444',        label: 'NO' };
  if (outcome === 'early_exit') {
    if (pnl > 0)  return { bg: 'rgba(34,197,94,0.10)',  color: '#16a34a', label: 'EARLY EXIT' };
    if (pnl < 0)  return { bg: 'rgba(239,68,68,0.10)',  color: '#ef4444', label: 'EARLY EXIT' };
    return               { bg: 'rgba(148,163,184,0.15)', color: '#64748b', label: 'EARLY EXIT' };
  }
  return                        { bg: 'rgba(148,163,184,0.10)', color: 'var(--text-faint)', label: outcome?.toUpperCase() || '—' };
}

// ---------------------------------------------------------------------------
// InfoIcon — small (i) button that shows a tooltip on hover/click
// ---------------------------------------------------------------------------
export function InfoIcon({ tip }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);
  return (
    <span ref={ref} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
      style={{ position: 'relative', display: 'inline-block', marginLeft: 5, verticalAlign: 'middle' }}>
      <button type="button" onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }}
        style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 16, height: 16, borderRadius: '50%', border: 'none', padding: 0,
          background: open ? '#3b82f6' : 'var(--bg-muted)',
          color: open ? '#fff' : 'var(--text-muted)',
          fontSize: 10, fontWeight: 700, cursor: 'pointer', lineHeight: 1, fontStyle: 'italic',
        }}>i</button>
      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 6px)', left: '50%', transform: 'translateX(-50%)',
          zIndex: 100, width: 240, padding: '10px 12px',
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 8, boxShadow: '0 8px 24px rgba(0,0,0,0.18)',
          color: 'var(--text)', fontSize: 12, fontWeight: 400, lineHeight: 1.45,
          textAlign: 'left', whiteSpace: 'normal',
        }}>{tip}</div>
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// StatCard — KPI tile with label, large value, optional delta and subtitle
// ---------------------------------------------------------------------------
export function StatCard({ label, value, delta, deltaTone, sub, tooltip }) {
  return (
    <div style={{
      background: 'var(--bg-card)', border: '1px solid var(--border)',
      borderRadius: 14, padding: '18px 20px',
    }}>
      <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 500, marginBottom: 6 }}>
        {label}{tooltip && <InfoIcon tip={tooltip} />}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
        <div style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-0.02em' }}>{value}</div>
        {delta && (
          <div style={{
            fontSize: 13, fontWeight: 600,
            color: deltaTone === 'pos' ? '#16a34a' : deltaTone === 'neg' ? '#ef4444' : 'var(--text-muted)',
          }}>{delta}</div>
        )}
      </div>
      {sub && <div style={{ marginTop: 6, color: 'var(--text-faint)', fontSize: 11 }}>{sub}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TableSkeleton — animated loading placeholder for tables
// ---------------------------------------------------------------------------
// batch-48 item 10: the `@keyframes pulse` <style> block used to be rendered
// inside TableSkeleton's own JSX, so every mounted instance injected its own
// copy into the page. Hoisted to a single lazy, idempotent injection instead
// -- guarded by `typeof document` so importing this module in a non-DOM test
// environment (this repo's vitest suite runs plain functions with no jsdom)
// never touches `document` at all, and by the module-level flag so a second
// TableSkeleton instance (or re-render) is a no-op rather than a second
// <style> tag.
let pulseKeyframesInjected = false;
function ensurePulseKeyframes() {
  if (pulseKeyframesInjected || typeof document === 'undefined') return;
  const style = document.createElement('style');
  style.textContent = '@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }';
  document.head.appendChild(style);
  pulseKeyframesInjected = true;
}

export function TableSkeleton({ rows = 5, columns = 8 }) {
  ensurePulseKeyframes();
  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden' }}>
      <div style={{ padding: '11px 16px', background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', gap: 16 }}>
          {Array.from({ length: columns }).map((_, i) => (
            <div key={i} style={{ width: 80, height: 10, background: 'var(--bg-muted)', borderRadius: 4, animation: 'pulse 1.5s ease-in-out infinite' }} />
          ))}
        </div>
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} style={{ padding: '14px 16px', borderBottom: '1px solid var(--bg-muted)', display: 'flex', gap: 16 }}>
          {Array.from({ length: columns }).map((_, j) => (
            <div key={j} style={{ width: j === 0 ? 120 : 80, height: 12, background: 'var(--bg-muted)', borderRadius: 4, animation: 'pulse 1.5s ease-in-out infinite', animationDelay: `${i * 0.1}s` }} />
          ))}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// BalanceSparkline — SVG chart of /api/balance_history [{ts, balance, event}]
// ---------------------------------------------------------------------------
export function BalanceSparkline({ hist }) {
  const [hoverIdx, setHoverIdx] = useState(null);

  if (!hist || hist.length < 2) return null;

  const W = 900, H = 120, PAD = { top: 12, right: 16, bottom: 24, left: 56 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const balances = hist.map(p => p.balance);
  const minB = Math.min(...balances);
  const maxB = Math.max(...balances);
  const rangeB = maxB - minB || 1;

  const xs = hist.map((_, i) => PAD.left + (i / (hist.length - 1)) * innerW);
  const ys = hist.map(p => PAD.top + (1 - (p.balance - minB) / rangeB) * innerH);

  const linePts = xs.map((x, i) => `${x},${ys[i]}`).join(' ');
  const areaPts = [
    `${xs[0]},${PAD.top + innerH}`,
    ...xs.map((x, i) => `${x},${ys[i]}`),
    `${xs[xs.length - 1]},${PAD.top + innerH}`,
  ].join(' ');

  const events = hist.filter(p => p.event);
  const lastBalance = balances[balances.length - 1];

  const handleMouseMove = (e) => {
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const mouseX = (e.clientX - rect.left) * (W / rect.width);
    const innerX = mouseX - PAD.left;
    const idx = Math.round((innerX / innerW) * (hist.length - 1));
    setHoverIdx(Math.max(0, Math.min(hist.length - 1, idx)));
  };

  // Tooltip box: flip to left side when near right edge
  const tip = hoverIdx !== null ? (() => {
    const x = xs[hoverIdx];
    const y = ys[hoverIdx];
    const pt = hist[hoverIdx];
    const label = pt?.ts
      ? new Date(pt.ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      : '';
    const value = `$${Number(pt.balance).toFixed(2)}`;
    const tipW = 90, tipH = 32, tipPad = 8;
    const flipX = x + tipW + tipPad > W - PAD.right;
    const tx = flipX ? x - tipW - tipPad : x + tipPad;
    const ty = Math.max(PAD.top, Math.min(y - tipH / 2, PAD.top + innerH - tipH));
    return { x, y, tx, ty, tipW, tipH, label, value, isEvent: !!pt?.event };
  })() : null;

  return (
    <section style={{
      background: 'var(--bg-card)', border: '1px solid var(--border)',
      borderRadius: 14, padding: '20px', marginBottom: 18,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Balance history</h3>
        <span style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'ui-monospace, monospace' }}>
          ${Number(lastBalance).toFixed(2)} current
        </span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible', cursor: 'crosshair' }}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverIdx(null)}
      >
        <defs>
          <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.01" />
          </linearGradient>
        </defs>
        {/* Filled area */}
        <polygon points={areaPts} fill="url(#sparkGrad)" />
        {/* Line */}
        <polyline points={linePts} fill="none" stroke="#3b82f6" strokeWidth="2" strokeLinejoin="round" />
        {/* Event dots */}
        {events.map((p, i) => {
          const idx = hist.indexOf(p);
          return <circle key={i} cx={xs[idx]} cy={ys[idx]} r="4" fill="#f59e0b" stroke="var(--bg-card)" strokeWidth="1.5" />;
        })}
        {/* Current balance endpoint dot */}
        <circle cx={xs[xs.length - 1]} cy={ys[ys.length - 1]} r="4" fill="#3b82f6" stroke="var(--bg-card)" strokeWidth="2" />
        {/* Y-axis labels */}
        <text x={PAD.left - 6} y={PAD.top + 4} textAnchor="end" fontSize="10" fill="var(--text-faint)"
          fontFamily="ui-monospace, monospace">${Math.round(maxB)}</text>
        <text x={PAD.left - 6} y={PAD.top + innerH + 4} textAnchor="end" fontSize="10" fill="var(--text-faint)"
          fontFamily="ui-monospace, monospace">${Math.round(minB)}</text>
        {/* X-axis: first and last dates */}
        {hist[0]?.ts && (
          <text x={xs[0]} y={H - 4} textAnchor="start" fontSize="10" fill="var(--text-faint)">
            {new Date(hist[0].ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
          </text>
        )}
        {hist[hist.length - 1]?.ts && (
          <text x={xs[xs.length - 1]} y={H - 4} textAnchor="end" fontSize="10" fill="var(--text-faint)">
            {new Date(hist[hist.length - 1].ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
          </text>
        )}
        {/* Hover crosshair + tooltip */}
        {tip && (
          <>
            <line
              x1={tip.x} y1={PAD.top} x2={tip.x} y2={PAD.top + innerH}
              stroke="var(--text-faint)" strokeWidth="1" strokeDasharray="3,3"
            />
            <circle cx={tip.x} cy={tip.y} r="5"
              fill={tip.isEvent ? '#f59e0b' : '#3b82f6'} stroke="var(--bg-card)" strokeWidth="2"
            />
            <rect x={tip.tx} y={tip.ty} width={tip.tipW} height={tip.tipH} rx="5"
              fill="var(--bg-card)" stroke="var(--border)" strokeWidth="1"
              style={{ filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.15))' }}
            />
            <text x={tip.tx + tip.tipW / 2} y={tip.ty + 11} textAnchor="middle"
              fontSize="9" fill="var(--text-muted)" fontFamily="ui-monospace, monospace">
              {tip.label}
            </text>
            <text x={tip.tx + tip.tipW / 2} y={tip.ty + 24} textAnchor="middle"
              fontSize="11" fontWeight="600" fill="var(--text)" fontFamily="ui-monospace, monospace">
              {tip.value}
            </text>
          </>
        )}
        {/* Transparent overlay to ensure mouse events fire across full chart area */}
        <rect
          x={PAD.left} y={PAD.top} width={innerW} height={innerH}
          fill="transparent" style={{ pointerEvents: 'all' }}
        />
      </svg>
      {events.length > 0 && (
        <div style={{ fontSize: 10, color: 'var(--text-faint)', marginTop: 4 }}>
          <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: '#f59e0b', marginRight: 4, verticalAlign: 'middle' }} />
          Yellow dots = account events
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// SystemEventsCard — renders M.alerts as a timestamped feed
// ---------------------------------------------------------------------------
export function SystemEventsCard({ alerts }) {
  const items = Array.isArray(alerts) ? alerts.slice(0, 6) : [];

  function relTime(ts) {
    if (!ts) return '';
    const diffMs = Date.now() - new Date(ts);
    const mins = Math.round(diffMs / 60_000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.round(hrs / 24)}d ago`;
  }

  function badgeStyle(level) {
    // batch-46 M-2: was a solid light-mode-only hex fill (e.g. #fee2e2) paired
    // with dark text -- illegible once the surrounding page goes dark. Token
    // fills track the active theme instead.
    const styles = {
      error: { background: 'var(--neg-fill)', color: 'var(--neg)' },
      warn:  { background: 'var(--warn-fill)', color: 'var(--warn)' },
      info:  { background: 'var(--accent-fill)', color: 'var(--accent)' },
      good:  { background: 'var(--pos-fill)', color: 'var(--pos)' },
    };
    return styles[level] || styles.info;
  }

  return (
    <section style={{
      background: 'var(--bg-card)', border: '1px solid var(--border)',
      borderRadius: 14, padding: '20px',
    }}>
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 14 }}>System events</h3>
      {items.length === 0 ? (
        <div style={{ color: 'var(--text-faint)', fontSize: 13, padding: '8px 0' }}>No recent events.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {items.map((evt, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'flex-start', gap: 10,
              padding: '10px 12px', borderRadius: 8, background: 'var(--bg-subtle)',
            }}>
              <span style={{
                ...badgeStyle(evt.level),
                fontSize: 10, fontWeight: 700, padding: '2px 7px',
                borderRadius: 4, textTransform: 'uppercase', whiteSpace: 'nowrap', marginTop: 1,
              }}>
                {evt.level || 'info'}
              </span>
              <span style={{ fontSize: 13, flex: 1, lineHeight: 1.5 }}>{evt.text}</span>
              <span style={{ fontSize: 11, color: 'var(--text-faint)', whiteSpace: 'nowrap', marginTop: 2 }}>
                {relTime(evt.ts)}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// BrierTrendChart — interactive weekly Brier sparkline with hover tooltip
// ---------------------------------------------------------------------------
export function BrierTrendChart({ hist }) {
  const [hoveredIdx, setHoveredIdx] = useState(null);
  const svgRef = useRef(null);

  const W = 800, H = 100;
  const PAD = { top: 12, right: 8, bottom: 8, left: 8 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const briersArr = hist.map(h => h.brier);
  const minB = Math.max(0, Math.min(...briersArr) - 0.02);
  const maxB = Math.max(...briersArr) + 0.02;
  const range = maxB - minB || 0.01;

  const xs = hist.map((_, i) => PAD.left + (i / (hist.length - 1)) * innerW);
  const toY = b => PAD.top + (1 - (b - minB) / range) * innerH;
  const ys = hist.map(h => toY(h.brier));
  const targetY = toY(0.20);

  const pts = xs.map((x, i) => `${x},${ys[i]}`).join(' ');
  const areaPts = [
    `${xs[0]},${PAD.top + innerH}`,
    ...xs.map((x, i) => `${x},${ys[i]}`),
    `${xs[xs.length - 1]},${PAD.top + innerH}`,
  ].join(' ');

  const trend = briersArr[briersArr.length - 1] - briersArr[0];
  const hovered = hoveredIdx != null ? hist[hoveredIdx] : null;

  // Hit-area: wide invisible rects over each point column
  const colW = hist.length > 1 ? innerW / (hist.length - 1) : innerW;

  return (
    <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Brier score trend (weekly)</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          {hovered ? (
            <span style={{ fontSize: 13, fontFamily: 'ui-monospace, monospace', fontWeight: 700,
              color: hovered.brier <= 0.20 ? '#16a34a' : '#3b82f6' }}>
              {hovered.week}: <strong>{hovered.brier.toFixed(3)}</strong>
              {hovered.brier <= 0.20 && <span style={{ color: '#16a34a', marginLeft: 6, fontSize: 11 }}>✓ target</span>}
            </span>
          ) : (
            <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>Hover a point to inspect</span>
          )}
          <span style={{ fontSize: 12, color: trend < 0 ? '#16a34a' : '#ef4444', fontWeight: 600, fontFamily: 'ui-monospace, monospace' }}>
            {trend < 0 ? '▼' : '▲'} {Math.abs(trend * 100).toFixed(1)}pts over {hist.length}w
          </span>
        </div>
      </div>

      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible', cursor: 'crosshair' }}
        onMouseLeave={() => setHoveredIdx(null)}>
        <defs>
          <linearGradient id="brierGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.15" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.01" />
          </linearGradient>
        </defs>

        {/* Fill area */}
        <polygon points={areaPts} fill="url(#brierGrad)" />

        {/* Target line */}
        {targetY >= PAD.top && targetY <= PAD.top + innerH && (
          <line x1={PAD.left} y1={targetY} x2={W - PAD.right} y2={targetY}
            stroke="#16a34a" strokeWidth="1" strokeDasharray="5,4" opacity="0.6" />
        )}

        {/* Crosshair for hovered point */}
        {hoveredIdx != null && (
          <line x1={xs[hoveredIdx]} y1={PAD.top} x2={xs[hoveredIdx]} y2={PAD.top + innerH}
            stroke="var(--text-faint)" strokeWidth="1" strokeDasharray="3,3" opacity="0.5" />
        )}

        {/* Sparkline */}
        <polyline points={pts} fill="none" stroke="#3b82f6" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />

        {/* Data points */}
        {hist.map((h, i) => {
          const isHov = hoveredIdx === i;
          const color = h.brier <= 0.20 ? '#16a34a' : '#3b82f6';
          return (
            <g key={i}>
              <circle cx={xs[i]} cy={ys[i]} r={isHov ? 6 : 4}
                fill={color} stroke="var(--bg-card)" strokeWidth={isHov ? 2.5 : 1.5}
                style={{ transition: 'r 0.1s' }} />
              {/* Wide invisible hit area */}
              <rect
                x={xs[i] - colW / 2} y={PAD.top}
                width={colW} height={innerH}
                fill="transparent"
                onMouseEnter={() => setHoveredIdx(i)}
              />
            </g>
          );
        })}
      </svg>

      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-faint)', marginTop: 4 }}>
        <span>{hist[0]?.week}</span>
        <span style={{ color: '#16a34a' }}>— target 0.20</span>
        <span>{hist[hist.length - 1]?.week}</span>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// sideAwareEntryPrice — the ask-side price to PAY for opp's recommended
// side. opp (a signals-cache entry) stores yes_bid/yes_ask/market_prob in
// YES-space regardless of the recommended side -- web_app.py's own display
// code proves this by flipping when rendering a NO signal. Returns
// side-space (NO pays 1 - yes_bid, the no_ask; YES pays yes_ask), matching
// web_app.py's WA-inversion comment's documented contract: "entry_price is
// the price PAID for the requested SIDE" -- the same convention
// order_executor.py's fill logic and web_app.py's own SignalsTab Kelly-qty
// display already use. Falls back to the market_prob mid (flipped for NO)
// when a live yes_bid/yes_ask quote isn't present. Exported (pure, no
// React) so it's unit-testable directly; shared by buildPaperOrderBody and
// every SignalsTab surface that estimates a default quantity or cost, so
// they all price a NO signal the same way.
// ---------------------------------------------------------------------------
export function sideAwareEntryPrice(opp) {
  const isNo = (opp.side || 'yes').toLowerCase() === 'no';
  const yesBid = opp.yes_bid != null ? Number(opp.yes_bid) : null;
  const yesAsk = opp.yes_ask != null ? Number(opp.yes_ask) : null;
  const askSidePrice = isNo
    ? (yesBid > 0 ? 1 - yesBid : null)
    : (yesAsk > 0 ? yesAsk : null);
  const midFallback = opp.market_prob != null
    ? (isNo ? 1 - opp.market_prob / 100 : opp.market_prob / 100)
    : 0.5;
  return askSidePrice != null && askSidePrice > 0 ? askSidePrice : midFallback;
}

// ---------------------------------------------------------------------------
// buildPaperOrderBody — /api/paper-order request body for a signals-tab
// Approve action. Exported (pure, no React) so it's unit-testable directly.
//
// entry_price uses sideAwareEntryPrice (see above).
//
// entry_prob is deliberately left in YES-space, UNFLIPPED -- unlike
// entry_price, every server-side consumer of the stored field (tracker's
// Brier/calibration scoring, order_executor's model-reversal exit shift,
// paper.py's pnl_attribution win_prob) treats entry_prob as YES-space, same
// as the bot's own order_executor.py call sites (entry_prob=a["forecast_prob"]).
// The /api/paper-order route converts it to side-space internally for its
// own Kelly-cap check only -- see web_app.py's api_paper_order.
// ---------------------------------------------------------------------------
export function buildPaperOrderBody(opp, qty) {
  const entryPrice = sideAwareEntryPrice(opp);
  const entryProb = opp.forecast_prob != null ? opp.forecast_prob / 100 : null;
  return {
    ticker:      opp.ticker,
    side:        (opp.side || 'yes').toLowerCase(),
    quantity:    qty,
    entry_price: entryPrice,
    entry_prob:  entryProb,
    // Prefer the raw ratio the signals cache already serves (net_edge,
    // 6dp — trade_cycle.py's signals_cache_entries) over re-dividing the
    // 1dp-rounded edge_pct display field, which loses precision on the
    // stored edge (opus review, 2026-08-09). edge_pct/100 kept as fallback
    // for entries without the raw field (e.g. mock data).
    net_edge:    opp.net_edge != null ? opp.net_edge
                 : (opp.edge_pct != null ? opp.edge_pct / 100 : null),
    city:        opp.city || null,
    target_date: opp.target_date || opp.expiry || null,
    days_out:    opp.days_out ?? null,
  };
}

// ---------------------------------------------------------------------------
// summarizeBulkResults — count real successes/failures from a
// Promise.allSettled array, for any bulk action that fires N independent
// requests (bulk-approve, bulk-close). A request that rejected outright
// (network failure) and one that resolved but the response body carries an
// {error} field both count as failed -- neither should be folded into an
// unconditional "done" toast. getError extracts the error indicator from a
// fulfilled result's value; defaults to the response body's own .error
// field, override it when the settled value wraps the response (e.g.
// {opp, d} pairs that need context for placedSet bookkeeping).
// ---------------------------------------------------------------------------
export function summarizeBulkResults(settledResults, getError = (v) => v?.error) {
  let succeeded = 0;
  let failed = 0;
  for (const r of settledResults) {
    if (r.status === 'fulfilled' && !getError(r.value)) succeeded++;
    else failed++;
  }
  return { succeeded, failed, total: settledResults.length };
}

// ---------------------------------------------------------------------------
// effectiveSelection — intersect a selection Set against the keys currently
// visible under a filter, WITHOUT mutating the selection itself. Used
// everywhere a bulk-selection count/checkbox/action-target is displayed or
// acted on, so a filter that narrows the table can't make the "N selected"
// count or a bulk action's target set claim more than what's actually
// visible -- while a selection made before filtering survives and reappears
// if the filter widens again, instead of being silently dropped forever.
// ---------------------------------------------------------------------------
export function effectiveSelection(selectedIds, visibleKeys) {
  const visible = visibleKeys instanceof Set ? visibleKeys : new Set(visibleKeys);
  const next = new Set();
  for (const id of selectedIds) if (visible.has(id)) next.add(id);
  return next;
}

// ---------------------------------------------------------------------------
// gradGateStatus — audit-M-11 (opus review MEDIUM-6): OverviewTab's
// graduation-gate progress bars used `grad.current.toFixed(3)` and
// `complete: grad.brier <= grad.brier_target` directly in JSX, untestable
// without component-render infra. Extracted so the null-brier fix (a real
// "not enough trades yet" answer, now that mapStats no longer falls back to
// MOCK's baked-in 0.151) is independently mutation-testable: `null <= 0.2`
// coerces null to 0 and evaluates true in JS, which would silently paint
// the gate green on missing data if `noData`/`complete` weren't guarded
// explicitly.
// ---------------------------------------------------------------------------
export function gradGateStatus(current, target, invert) {
  const noData = current == null;
  const complete = !noData && (invert ? current <= target : current >= target);
  // For an inverted (lower-is-better) gate the scale runs from a 0.25
  // "baseline" down to the target (e.g. 0.20), so the bar hits 100% exactly
  // when the gate clears, rather than only at impossible perfect
  // prediction (Brier=0).
  const pct = noData ? 0 : invert
    ? Math.min(100, Math.max(0, (0.25 - current) / (0.25 - target) * 100))
    : Math.min(100, Math.max(0, (current / target) * 100));
  return { noData, complete, pct };
}

// ---------------------------------------------------------------------------
// batch-47 item 2: unguarded cost/qty and balance/starting_balance divisions
// rendered NaN%/Infinity% directly into KPI cards -- p.qty===0 (data anomaly)
// and starting_balance===0 (plausible on a fresh install before any funding
// record exists) are both real denominators-of-zero, not fetch failures, so
// they can't be caught upstream in useData.js's mappers. Also independently
// flagged pre-port by audit/POST_MERGE_REVIEW.md's L-17 sweep (App.jsx's old
// divide-by-qty NaN) -- same bug. All three call sites now route through
// these guarded functions (opus review caught PositionsTab's detail-panel
// copy still computing the raw formula inline -- see positionUnrealizedPnl's
// call sites for the full list).
// ---------------------------------------------------------------------------

// A position with qty===0 contributes nothing rather than poisoning the
// whole aggregate into NaN -- one anomalous row shouldn't blank every other
// position's real unrealized P&L. `Number(p.qty)` (not a bare truthy check)
// so a qty arriving as the string "0" is caught the same way as a numeric
// 0 -- matches balanceDeltaPct's coercion below (opus review: the two were
// inconsistent).
export function sumUnrealizedPnl(positions) {
  return (positions || []).reduce((sum, p) => {
    if (!Number(p.qty)) return sum;
    const entryPerCt = p.cost / p.qty;
    return sum + (p.mark - entryPerCt) * p.qty;
  }, 0);
}

// Per-row version for PositionsTab — returns null (render "—") instead of
// NaN for a qty===0 row, rather than silently zeroing it into the table.
export function positionUnrealizedPnl(p) {
  if (!Number(p.qty)) return null;
  return (p.mark - p.cost / p.qty) * p.qty;
}

// Returns null (render "—") instead of NaN/Infinity when starting_balance
// is 0 -- a plausible real value before any funding record exists, not a
// fetch-failure case mapStats already guards.
export function balanceDeltaPct(balance, startingBalance) {
  const b = Number(balance);
  const s = Number(startingBalance);
  if (!s) return null;
  return (b - s) / s;
}

// ---------------------------------------------------------------------------
// batch-47 item 3: single source of truth for tab metadata. Previously
// TAB_NAMES (App.jsx's Nav), CommandPalette's own tab list, the global
// keydown handler's digit-shortcut list, and the TABS routing registry were
// four independently hand-written copies that had already drifted -- Settings
// was excluded from digit hotkeys by two unrelated mechanisms (Nav's `i < 8`
// badge bound, and the keydown handler's separately-truncated array), so a
// future edit to either one in isolation would silently reintroduce the
// inconsistency. Confirmed with the user (2026-08-24): Settings' current
// hotkey-less behavior is intentional, not an oversight -- kept as `hotkey:
// null` rather than extended to a 9th digit. No component references here
// (App.jsx maps `id` to its tab component) so this stays importable from
// shared.jsx without pulling every tab file into a circular import.
// ---------------------------------------------------------------------------
export const TAB_LIST = [
  { id: 'Overview',  hotkey: '1' },
  { id: 'Positions', hotkey: '2' },
  { id: 'Signals',   hotkey: '3' },
  { id: 'Forecast',  hotkey: '4' },
  { id: 'Analytics', hotkey: '5' },
  { id: 'Activity',  hotkey: '6' },
  { id: 'Risk',      hotkey: '7' },
  { id: 'Trades',    hotkey: '8' },
  { id: 'Settings',  hotkey: null },
];

// Pure lookup so the keydown handler's digit->tab mapping is unit-testable
// without mounting App.jsx (this repo has no jsdom/component-render harness).
export function tabForHotkey(key) {
  const tab = TAB_LIST.find(t => t.hotkey === key);
  return tab ? tab.id : null;
}

// ---------------------------------------------------------------------------
// brierAlertTier — batch-45 M-4: OverviewTab's alert banner and RiskTab's
// BrierAlertCard each independently computed "consecutive weeks above 0.22"
// over the same brierHistory and then labeled the identical state with
// different severity words (e.g. one week read "warning" on one tab and
// "ALERT" on the other) -- an operator switching tabs saw the label change
// with no change in the underlying state. Single source of truth for both:
// P10.3 is formally 2+ consecutive weeks above threshold ('alert'); 1 week
// is a softer early heads-up ('warning').
// ---------------------------------------------------------------------------
export function brierAlertTier(brierHistory, threshold = 0.22) {
  const recent = (brierHistory || []).slice(-6);
  let weeks = 0;
  for (let i = recent.length - 1; i >= 0; i--) {
    if (recent[i].brier > threshold) weeks++;
    else break;
  }
  const tier = weeks >= 2 ? 'alert' : weeks === 1 ? 'warning' : 'clear';
  const label = tier === 'alert' ? 'Alert' : tier === 'warning' ? 'Warning' : 'Clear';
  return { weeks, tier, label };
}

// ---------------------------------------------------------------------------
// Request timeouts for every fetch outside useData.js (batch-84 item 3;
// backlog.txt "EVERY OTHER RAW fetch() IN THE FRONTEND STILL HAS NO REQUEST
// TIMEOUT").
//
// batch-80 gave useData.js's apiFetch a budget; these 14 call sites --
// App.jsx's cron controls, this file's halt/resume, and the Analytics /
// Positions / Settings / Signals tabs -- were not its to own and kept
// fetch()'s default of "never". A hung backend leaves an operator-clicked
// button pinned on "Closing 3 positions..." or "Generating…" with no
// timeout ever clearing it, and leaves the 3s cron poll stacking requests
// for as long as the hang lasts.
//
// Reuses batch-80's timeoutSignal (AbortSignal.timeout with an
// AbortController fallback for engines below Chrome 103 / Firefox 100 /
// Safari 16) rather than inventing a second mechanism, and reuses its
// API_TIMEOUT_MS as the default: an operator click can land inside the same
// 23-request poll burst and queue behind the browser's ~6-connection cap on
// this HTTP/1.1 backend, so the budget has to cover queueing, not just
// server time.
// ---------------------------------------------------------------------------

// The 3s cron-status poll (App.jsx's startCronPoll). Bounded ABOVE by its own
// interval for exactly the reason batch-80 gave SCAN_VERSION_TIMEOUT_MS the
// same treatment: a budget at or past the interval lets requests stack, which
// is the accumulation this change exists to stop. web_app.py's
// api_cron_status reads the cron lock file (via cron._is_cron_running, which
// can also run a psutil PID-reuse check) and ANSI-strips the last 200 lines
// of the web log, plus one subprocess.poll() -- all local and fast, so the
// whole budget is slack for queueing rather than for server time.
//
// This is the ONLY budget below the shared default. Every other site here
// takes API_TIMEOUT_MS: an earlier draft also gave /api/weekly-report a
// 120s budget on the grounds that it renders a PDF inside the request and
// "can run to minutes", which opus review MEDIUM-2 disproved --
// pdf_report.generate_weekly_report's _collect_data does only local
// JSON/SQLite reads (paper.get_performance/get_balance/get_all_trades/
// fear_greed_index, tracker.brier_score_rolling_with_n) and _generate_pdf is
// fpdf2 text output with no matplotlib and no HTTP anywhere in the module.
// Sub-second in practice, so the default covers it and a second constant
// justified by a claim that is not true is worse than no constant.
export const CRON_POLL_TIMEOUT_MS = 2_500;

/**
 * Add a timeout signal to a fetch options object.
 *
 * Returns a NEW object; any `signal` already present is replaced (no call
 * site passes one today, and silently keeping a caller's signal would mean
 * the timeout quietly did nothing).
 */
export function withTimeout(options = {}, ms = API_TIMEOUT_MS) {
  return { ...options, signal: timeoutSignal(ms) };
}

/**
 * Did this rejection come from our own timeout rather than the network?
 *
 * BOTH names matter. AbortSignal.timeout() rejects with a TimeoutError, but
 * timeoutSignal's fallback path for older engines aborts an AbortController,
 * which rejects with an AbortError. Testing only for TimeoutError would make
 * every timeout on an older browser render as a flat "Request failed" -- the
 * same shape as batch-80's freshness-banner bug, where one helper returned
 * null for two states the caller then had to tell apart.
 *
 * KNOWINGLY FOLDED IN (opus review LOW-2): accepting AbortError also claims
 * a BROWSER-initiated abort as a timeout. Nothing in this app constructs an
 * AbortController other than timeoutSignal's fallback, and React StrictMode's
 * double-effect does not abort fetches -- but Firefox rejects an in-flight
 * fetch with AbortError when the user presses Esc or navigates away, where
 * Chrome gives TypeError. Esc is a live key here (PositionsTab's
 * kalshi:escape listener), so an operator who cancels a POST on Firefox is
 * told it "timed out".
 *
 * Left as-is deliberately rather than narrowed. The only wrong word is
 * "Timed out"; everything that follows it stays exactly right -- the request
 * WAS dispatched, the order may well have landed, and refreshing before
 * retrying is the correct advice. An operator who just pressed Esc has the
 * context to read past the label, whereas narrowing this to TimeoutError
 * alone would silently drop a real timeout on any engine below Chrome 103
 * back to "Request failed". Making the two genuinely distinguishable means
 * giving timeoutSignal's fallback an explicit abort reason, which lives in
 * useData.js -- not a file this change owns; filed as a backlog follow-up.
 */
export function isTimeoutError(err) {
  return !!err && (err.name === 'TimeoutError' || err.name === 'AbortError');
}

/**
 * Failure copy for an operator-initiated action, honest about what a timeout
 * does and does not tell us.
 *
 * An aborted POST says nothing about whether the server ran it: /api/paper-
 * order may have placed the order, /api/close-position may have closed the
 * trade. check_position_limits has no already-open-on-this-ticker guard, so
 * a blind re-click after a timeout can genuinely double-place. `outcome`
 * names what may have happened; a plain network failure keeps the original
 * wording, which is what it has always meant.
 *
 * The copy says "Refresh before retrying" rather than the handler calling
 * M.refresh() itself, which opus review LOW-3 raised as the more helpful
 * option. Deliberate: a timeout means the backend is already slow or hung,
 * and M.refresh() fires useData's 23-request burst straight into it -- most
 * of which would then time out too, at 30s each, while the operator watches
 * a dashboard degrade instead of getting an answer. The refresh button is
 * right there, and after a timeout the operator is better placed than this
 * catch block to judge when the backend is worth asking again.
 */
export function actionFailureMessage(err, outcome) {
  return isTimeoutError(err)
    ? `✗ Timed out — ${outcome}. Refresh before retrying.`
    : '✗ Request failed';
}

/**
 * How many of a Promise.allSettled batch were rejected BY A TIMEOUT.
 *
 * summarizeBulkResults folds every rejection into one `failed` count, so a
 * bulk close or bulk approve would otherwise report "✗ 3 failed" for three
 * orders that may all have gone through. Counting them separately is what
 * lets the toast say so.
 */
export function countTimeouts(results) {
  return (results || []).filter(
    r => r && r.status === 'rejected' && isTimeoutError(r.reason)
  ).length;
}

/**
 * The toast for a bulk action, with timeouts held apart from real failures.
 *
 * Extracted (opus review MEDIUM-3) because the arithmetic that USES
 * countTimeouts is the part that carries the honest-copy decision, and it
 * was sitting inline in two components this repo has no render tests for --
 * so reverting `if (timedOut > 0)` to a dead condition left the whole suite
 * green while restoring "✗ 3 failed" for three orders that may all have
 * landed. One implementation, unit-tested, called by both tabs.
 *
 * `failed` is summarizeBulkResults' count, which includes the timeouts;
 * they are subtracted out here so a caller cannot forget to. The Math.max
 * is belt-and-braces -- both counts are derived from the same array, so
 * failed >= timedOut is already an invariant.
 *
 * successPhrase/skippedPhrase are functions rather than words because the
 * two tabs' existing copy differs in word order ("✓ Closed 3" vs "✓ 3
 * placed"), and this extraction is not the place to change either.
 *
 * Zero successes print nothing (opus review INFO-3): SignalsTab previously
 * led with an unconditional "✓ 0 placed", so a batch where every order
 * timed out would have opened with a green check.
 */
export function bulkOutcomeMessage(counts, options) {
  const { succeeded = 0, failed = 0, timedOut = 0, skipped = 0 } = counts || {};
  const {
    successPhrase,
    timeoutOutcome,
    skippedPhrase,
    emptyMessage,
    sep = ' — ',
  } = options || {};
  const hardFailed = Math.max(0, failed - timedOut);
  const parts = [];
  if (succeeded > 0) parts.push(successPhrase(succeeded));
  if (hardFailed > 0) parts.push(`✗ ${hardFailed} failed`);
  if (timedOut > 0) parts.push(`${timedOut} timed out — ${timeoutOutcome}; refresh`);
  if (skipped > 0 && skippedPhrase) parts.push(skippedPhrase(skipped));
  return parts.length ? parts.join(sep) : emptyMessage;
}

// ---------------------------------------------------------------------------
// haltOrResume — batch-45 audit-M-8: five near-identical inline handlers
// (App.jsx's Nav kill switch, RiskTab's kill switch, and SettingsTab's inline
// resume + bottom Halt/Resume pair) each fired `fetch('/api/halt'|'/api/resume', ...)`
// with no `.then`/`.catch` at all -- a real server-side failure (the routes
// have a genuine 500 path) was silent, and the halt-status badge just never
// flipped, with nothing telling the operator to fall back to the documented
// `py main.py kill` / `py main.py resume`. One shared implementation so the
// five call sites can't drift back out of sync with each other the way the
// inline-resume-vs-bottom-pair split already had (bottom pair also omitted
// the M.refresh() the inline button made -- see M-8 frontend-doc item).
// `refresh`/`addToast` are passed in rather than imported so this stays a
// pure, directly-testable function -- DataContext is a live React context,
// not something a plain unit test can construct.
// ---------------------------------------------------------------------------
export function haltOrResume(action, { refresh, addToast }) {
  // opus review MEDIUM (batch-45): an unrecognized `action` must never
  // silently fall through to the 'resume' branch -- that would POST
  // /api/resume (un-halting live trading) behind a dialog that told the
  // operator they were engaging the kill switch. Explicit allowlist, not a
  // binary ternary, so a future third action/typo fails loud instead of
  // resolving to the unsafe direction.
  if (action !== 'halt' && action !== 'resume') {
    throw new Error(`haltOrResume: unknown action "${action}" (expected 'halt' or 'resume')`);
  }
  // opus review LOW (batch-45): if addToast/refresh are ever missing (a
  // future call site regression), fail visibly via console.error instead of
  // throwing inside .then -- an uncaught throw there would hit .catch, which
  // calls addToast again, throws again, and produces an unhandled rejection
  // with the halt/resume outcome never surfaced to the operator at all --
  // silently recreating the exact bug this helper exists to fix.
  if (typeof refresh !== 'function' || typeof addToast !== 'function') {
    console.error('haltOrResume: refresh/addToast not wired up', { refresh, addToast });
    return Promise.resolve();
  }
  const endpoint = action === 'halt' ? '/api/halt' : '/api/resume';
  const failMsg = action === 'halt'
    ? 'Halt FAILED — use py main.py kill'
    : 'Resume FAILED — use py main.py resume';
  // batch-84 item 3: a timeout keeps its own wording rather than borrowing
  // failMsg's. "Halt FAILED" is a definite statement, and after an abort we
  // do not know that -- the kill switch may already be engaged. The manual
  // fallback command is still named, because it is also how the operator
  // CHECKS, and both routes are idempotent so running it after a timeout
  // that did land is harmless.
  const timeoutMsg = action === 'halt'
    ? 'Halt timed out — it may have applied; confirm with py main.py kill'
    : 'Resume timed out — it may have applied; confirm with py main.py resume';
  return fetch(endpoint, withTimeout({ method: 'POST', headers: authHeader() }))
    .then(r => r.ok ? refresh() : addToast(failMsg, 'error'))
    .catch(e => addToast(isTimeoutError(e) ? timeoutMsg : failMsg, 'error'));
}

// ---------------------------------------------------------------------------
// Signal dismissal (batch-45 M-7) — SignalsTab's Reject/Reject All used to
// just show a toast and return with nothing persisted, so the row reappeared
// identically on the next scan. oppKey is the composite ticker+target_date
// key SignalsTab uses to identify an opp across both placedSet (has this
// order already been submitted?) and rejectedMap (has this signal been
// dismissed?) -- originally hand-duplicated as five near-identical inline
// template strings in SignalsTab.jsx before this extraction. pruneExpired
// drops rejectedMap entries whose TTL (set at dismiss time) has passed, so a
// dismissal survives a same-day re-scan without hiding a signal forever.
// Both extracted as pure functions so the key shape and expiry logic are
// unit-testable without React/localStorage render infra.
// ---------------------------------------------------------------------------
export function oppKey(opp) {
  return `${opp.ticker}|${opp.target_date || opp.expiry || ''}`;
}

export function pruneExpired(map, now = Date.now()) {
  return Object.fromEntries(Object.entries(map).filter(([, exp]) => exp > now));
}

// ---------------------------------------------------------------------------
// filterRejected — opus review MEDIUM (batch-45): the original SignalsTab
// implementation excluded an opp by checking `rejectedMap[key] == null`
// (presence), not validity. Since pruneExpired only ran once in a useState
// lazy initializer, an entry never actually left rejectedMap during a long-
// open session (this is a kiosk-style dashboard with a 60s poll) -- the 24h
// TTL was dead code and a dismissal hid a ticker+date forever, not for 24h.
// This checks the SAME expiry value against `now` at call time instead of
// presence, so a stale entry stops suppressing its row the moment it expires
// -- correct even if the state itself never gets pruned. Extracted (rather
// than left inline in the component's `filtered` useMemo) so this exact
// exclusion logic is unit-testable without React render infra.
// ---------------------------------------------------------------------------
export function filterRejected(opportunities, rejectedMap, now = Date.now()) {
  return opportunities.filter(o => {
    const exp = rejectedMap[oppKey(o)];
    return exp == null || exp <= now;
  });
}

// ---------------------------------------------------------------------------
// resolveByKey — batch-48 item 11 (audit F-M4): find the CURRENT object
// matching `key` in `items`, via caller-supplied `keyFn`. Used to re-derive a
// pending-confirmation object fresh on every render (SignalsTab's
// pendingApprovalKey -> live opportunity) instead of trusting whatever
// object was captured at the moment a confirm dialog was opened -- if a poll
// lands while the dialog is still open, the next call with the refreshed
// `items` list returns the object carrying the CURRENT quote, not the stale
// one. Generalizes the identity-based lookup PositionsTab.jsx already uses
// inline (selectedId + `M.positions.find(p => rowKey(p) === selectedId)`)
// into a shared, independently-testable helper. Returns null both when `key`
// itself is null (nothing pending) and when `key` no longer matches anything
// in `items` (the referenced item aged out of the live data).
// ---------------------------------------------------------------------------
export function resolveByKey(items, key, keyFn) {
  if (key == null) return null;
  return items.find(item => keyFn(item) === key) ?? null;
}

// ---------------------------------------------------------------------------
// heatStatus — batch-48 item 3: RiskTab derived a display string via
// `.toFixed(0)` and then compared THAT STRING directly against 80/60 (`>`
// coerces it back to a number, so it happened to work -- but a future
// refactor touching either side has nothing stopping it from comparing two
// strings lexicographically instead, e.g. "9" > "80" is true). Keeps the
// real number the comparisons need separate from the display-only string.
// ---------------------------------------------------------------------------
export function heatStatus(totalCost, balance) {
  const pct = balance > 0 ? (totalCost / balance) * 100 : 0;
  return {
    pct,
    label: pct.toFixed(0) + '%',
    deltaTone: pct > 80 ? 'neg' : pct > 60 ? undefined : 'pos',
    sub: pct > 80 ? 'Over limit — halting' : 'Within 80% limit',
  };
}

// ---------------------------------------------------------------------------
// validateOverrideDuration — batch-45 M-8: the duration input's `min="5"`
// (and `max="480"`) only constrain the spinner UI, not what a cleared/typed/
// pasted value submits (unary `+` coerces an empty string to 0). Extracted
// so the actual floor/ceiling check is unit-testable -- an opus review
// mutation-tested the inline version of this check (reverted to `if
// (false)`) and the full `npm test` suite still passed, proving nothing
// exercised it. Mirrors the server's own bounds (web_app.py api_override_set:
// rejects non-positive, clamps to 1440) so the operator sees a rejection
// client-side instead of a silently-clamped/differently-worded server value.
// ---------------------------------------------------------------------------
export function validateOverrideDuration(raw, { min = 5, max = 480 } = {}) {
  const duration = Number(raw);
  if (!Number.isFinite(duration)) {
    return { valid: false, duration: null, error: `Duration must be at least ${min} minutes.` };
  }
  if (duration < min) {
    return { valid: false, duration: null, error: `Duration must be at least ${min} minutes.` };
  }
  if (duration > max) {
    return { valid: false, duration: null, error: `Duration must be at most ${max} minutes.` };
  }
  return { valid: true, duration, error: null };
}

// ---------------------------------------------------------------------------
// summarizeTradeOutcomes — batch-45 M-6: TradesTab's header read
// `{filtered.length} settled · {wins} wins · {losses} losses`, but wins/
// losses were computed from the full unfiltered M.closedTrades while the
// leading count respected the active filter -- filtering to one city made
// the three numbers stop adding up (an `other = filtered.length - wins -
// losses` derived from that mismatch could even go negative). Must be
// called with the SAME rows as the count it's paired with.
// ---------------------------------------------------------------------------
export function summarizeTradeOutcomes(rows) {
  const wins = rows.filter(t => t.pnl > 0).length;
  const losses = rows.filter(t => t.pnl != null && t.pnl < 0).length;
  const other = rows.length - wins - losses;
  return { wins, losses, other };
}

// ---------------------------------------------------------------------------
// Feed freshness — batch-61 item 3 (backlog L30717).
//
// useData.js's per-endpoint merges are deliberately keep-last-known-good
// (`if (anomalyStatus) next.anomalyStatus = anomalyStatus`), so a *failing*
// endpoint leaves its previous value sitting in state indefinitely with
// nothing marking it as no longer live. For a display-only feed that is a
// reasonable anti-flicker default; for a SAFETY MONITOR it inverts the
// meaning of the card -- RiskTab's anomaly card rendered the same grey
// INACTIVE state for "healthy and quiet" and for "/api/anomaly-status has
// been unreachable for an hour," i.e. it read most reassuring in exactly
// the case it should alarm.
//
// The fix is a per-endpoint `fetchedAt` timestamp (useData.js's
// `next.fetchedAt` map, written only on a SUCCESSFUL fetch) plus this pure
// predicate over it. Kept here rather than inline in the component because
// frontend/ has no jsdom/RTL -- components aren't render-testable, so the
// decision itself has to live somewhere unit-testable (same reason as
// gradGateStatus/heatStatus/resolveByKey above).
//
// WHAT THE MARKER DOES AND DOES NOT MEAN (opus review F12): `fetchedAt` is
// stamped at MERGE time and means only "this endpoint answered". It is not
// a claim that the reading is current -- a slow-but-successful response, or
// a backend serving a stale computation with HTTP 200, both read fresh.
// That is the right guarantee for "is the monitor reachable?", and it is
// what the banner's "last successful update" wording says. batch-63's
// order-action gate reuses this primitive and should not read more into it.
//
// Three states, deliberately NOT two: 'pending' (never fetched successfully
// -- what is on screen is mockData) is distinct from 'stale' (was live, has
// since gone quiet) even though both are `stale: true`, so a consumer can
// word them differently and style them differently. Callers that only need
// "may I trust this?" read `.stale` and ignore `.state`.
//
// `since` is the "we started watching at" reference (see useFeedClock).
// Two jobs, both from opus review:
//   - F3: the main poll is visibility-gated, so a backgrounded tab makes no
//     attempts at all. Without `since`, returning from a 5-minute alt-tab
//     painted a full-width "the safety monitor is not responding" banner
//     that vanished ~300ms later when the catch-up fetch landed -- many
//     times a day, on the one banner this entry exists to make credible.
//     Resetting `since` on becoming visible restarts the tolerance window,
//     so only time we were actually able to poll counts against the feed.
//   - F4: with no `since`, 'pending' was a trap state -- an endpoint that
//     NEVER answers (route 404s on an older backend, a proxy blocking the
//     path) showed "hasn't loaded yet, wait a moment" forever while mock
//     numbers sat under it. Aging from `since` lets a never-answering feed
//     escalate to 'stale' with `ageMs: null`, which the card words as "has
//     not responded since this page loaded".
// Wall-clock elapsed is still what trips the threshold, so a backend that
// HANGS (accepting the connection but never answering, e.g. handler threads
// blocked on a sqlite lock) still alarms -- that path never resolves a
// fetch, so an attempt-counting design would never fire (opus review F1).
//
// Default maxAgeMs is 3x the 60s main poll: two consecutive misses are
// tolerated (a slow response or one dropped request should not alarm), the
// third trips it.
//
// Clock handling (opus review F6): a BACKWARD step reads fresh rather than
// letting an NTP correction fabricate an outage. A FORWARD step can briefly
// fabricate one, self-correcting within one poll (<=60s). Both are accepted
// rather than switching to performance.now(): `fetchedAt` is deliberately a
// wall-clock epoch so the banner can say when the last good reading was, and
// so batch-63 can compare it against timestamps from elsewhere.
// ---------------------------------------------------------------------------
export const FEED_STALE_MS = 180_000;
// Ceiling on how much tolerance the `since` credit can ever buy. Without it,
// an operator alt-tabbing every couple of minutes resets the window forever
// and a genuinely dead feed never alarms (opus review F1, round 2). Past this
// TRUE age a feed is stale no matter how little of that time we were able to
// poll through -- at 12 minutes the reading is not worth standing behind
// either way.
export const FEED_HARD_STALE_MS = FEED_STALE_MS * 4;

export function feedFreshness(fetchedAt, { now, maxAgeMs, since, hardMaxAgeMs } = {}) {
  // The options bag is validated the same way `fetchedAt` is (opus review
  // F9): a caller passing a null/NaN `now` or `maxAgeMs` used to make every
  // comparison NaN, which reports a healthy feed -- a caller bug silently
  // failing OPEN on a safety monitor. Fall back to the defaults instead.
  const nowMs = Number.isFinite(now) ? now : Date.now();
  const maxAge = Number.isFinite(maxAgeMs) && maxAgeMs >= 0 ? maxAgeMs : FEED_STALE_MS;
  const sinceMs = Number.isFinite(since) ? since : null;
  const hardMax =
    Number.isFinite(hardMaxAgeMs) && hardMaxAgeMs >= 0
      ? hardMaxAgeMs
      : Math.max(maxAge, FEED_HARD_STALE_MS);

  const hasStamp = Number.isFinite(fetchedAt);
  const ageMs = hasStamp ? nowMs - fetchedAt : null;

  // Age is measured from the last success, or -- when there has never been
  // one -- from when we started watching. `Math.max` so a `since` newer than
  // the last success (tab just became visible) restarts the tolerance window
  // rather than instantly alarming on time we could not poll through.
  const ref = hasStamp ? (sinceMs != null ? Math.max(fetchedAt, sinceMs) : fetchedAt) : sinceMs;

  if (ref == null) return { state: 'pending', stale: true, ageMs: null, suppressedBySince: false };
  if (nowMs - ref > maxAge) {
    return { state: 'stale', stale: true, ageMs, suppressedBySince: false };
  }
  // The hard ceiling ignores `since` entirely: repeated hidden->visible
  // transitions must not be able to defer an alarm indefinitely.
  if (hasStamp && ageMs > hardMax) {
    return { state: 'stale', stale: true, ageMs, suppressedBySince: false };
  }
  return hasStamp
    ? {
        state: 'fresh',
        stale: false,
        ageMs,
        // TRUE: this feed is only reading fresh because `since` restarted the
        // window -- its real age already exceeds maxAgeMs. Exposed so a
        // consumer (batch-63's order-action gate) can tell "genuinely fresh"
        // from "not yet alarming"; a UI pairing a green badge with
        // formatFeedAge(ageMs) would otherwise read self-contradictory
        // (opus review F4).
        suppressedBySince: ageMs > maxAge,
      }
    : { state: 'pending', stale: true, ageMs: null, suppressedBySince: false };
}

// Coarse human label for feedFreshness().ageMs. Deliberately coarse: this
// annotates an "unavailable" badge, where "4 min ago" is the whole message
// and second-level precision would just churn the DOM every render. Returns
// null for the null ageMs a never-answered feed reports, so a safety banner
// can never render "NaN min ago".
export function formatFeedAge(ageMs) {
  if (!Number.isFinite(ageMs) || ageMs < 0) return null;
  const mins = Math.floor(ageMs / 60_000);
  if (mins < 1) return 'less than a minute ago';
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  return hours === 1 ? '1 hr ago' : `${hours} hrs ago`;
}

// ---------------------------------------------------------------------------
// ORDER-ACTION QUOTE FRESHNESS (batch-63 item 3)
// ---------------------------------------------------------------------------
// Approve / Close submit a PRICE (buildPaperOrderBody's entry_price,
// /api/close-position's exit_price). Nothing on either path checked how old
// the quote behind that price was. batch-47's visibility-gated polling made
// that materially worse: polling stops entirely while the tab is
// backgrounded, so an operator returning to a long-backgrounded tab can
// click Approve/Close against arbitrarily old quotes, before the catch-up
// fetch (~22 concurrent requests, not instant) resolves.
//
// WHY THIS IS TIGHTER THAN FEED_STALE_MS, DELIBERATELY. batch-61 set
// FEED_STALE_MS = 180s for a DISPLAY banner, where a false alarm is
// expensive (an operator learns to ignore a badge that cries wolf) and the
// cost of being 30s late to say "feed down" is near zero. An order confirm
// inverts both: an unnecessary "this quote is 95s old" line costs the
// operator one extra glance, while a missed stale quote books a real
// mispriced trade into the ledger, balance, drawdown tier and graduation
// P&L. So the order gate is half the banner's tolerance.
//
// It is DERIVED from FEED_STALE_MS rather than written as its own 90_000 so
// the divergence is structural and visible: retune the banner and this
// follows, instead of the dashboard quietly ending up with two unrelated
// magic numbers that disagree about what "stale" means.
export const ORDER_STALE_MS = FEED_STALE_MS / 2;

// SCAN_STALE_MS -- the age at which the SIGNALS SCAN behind an Approve price
// is worth flagging. A completely different quantity from ORDER_STALE_MS, and
// round-2 opus review (H1) caught the first version of batch-63 reusing the
// 90s order threshold for it, which made the Approve warning fire on every
// single click no matter how healthy everything was.
//
// The scan is produced by cron, which runs every THREE HOURS, and
// /api/live_signals serves its cache for up to four (MAX_SIGNALS_CACHE_AGE_
// SECS). "Signal prices are somewhat old" is therefore the normal, correct
// state -- gating it at 90 seconds is off by ~60x against the field being
// measured, and a notice that is always present is a notice nobody reads.
// Worse, it is the same component and wording as the Close-path notice,
// which DOES fire meaningfully, so crying wolf here would corrode that one.
//
// 90 minutes is not a new number: it is the threshold SignalsTab's own
// "Last scan" header chip has always used to turn amber. Reusing it means
// the confirm dialog says "out of date" exactly when the header already
// says so, instead of the two disagreeing on screen at the same time.
export const SCAN_STALE_MS = 90 * 60_000;

// orderQuoteStaleness — feedFreshness() specialized for an order action.
//
// One deliberate behavioral difference from the banner: a reading that is
// only "fresh" because the `since` visibility credit restarted the tolerance
// window counts as STALE here. That credit exists so a polling gap we could
// not have polled through does not fabricate a feed-down alarm -- a fair
// rule for "is the backend alive", and the wrong rule for "is this price
// current", because the price really is that old either way. feedFreshness
// exposes exactly that distinction as `suppressedBySince` (batch-61 added it
// naming this consumer); this is the consumer.
//
// Returns { stale, ageMs, label }. `ageMs`/`label` are null when the feed has
// never answered, which is a distinct case from "answered a while ago" and
// the caller's copy needs to say so -- see staleQuoteWarning.
export function orderQuoteStaleness(fetchedAt, opts) {
  // `opts || {}`, not a `= {}` default: the default only fires on `undefined`,
  // so a caller passing an explicit `null` used to throw a TypeError -- during
  // RENDER, at the top of both tab components, which the ErrorBoundary would
  // turn into a blank tab. staleQuoteWarning was already hardened this way
  // (opus review F9); this matches it.
  const { now, maxAgeMs, since } = opts || {};
  const maxAge =
    Number.isFinite(maxAgeMs) && maxAgeMs >= 0 ? maxAgeMs : ORDER_STALE_MS;
  // hardMaxAgeMs is deliberately not passed: feedFreshness defaults it to
  // max(maxAge, FEED_HARD_STALE_MS) = 720s, and every input where that
  // ceiling would change the answer is already stale via `suppressedBySince`
  // below -- i.e. it is inert here (opus review F8, verified by sweep). If
  // the OR is ever weakened, that dormant 720s ceiling silently becomes the
  // real gate, so change the two together.
  const f = feedFreshness(fetchedAt, { now, maxAgeMs: maxAge, since });
  // A stamp in the FUTURE means the client clock stepped backwards, so the
  // age is not merely large, it is meaningless. feedFreshness deliberately
  // reads that as fresh (an NTP correction must not fabricate a feed-down
  // alarm on a banner) -- but for an ORDER gate that is failing open on a
  // quote of genuinely unknown age, and one backward step would silence all
  // four actions at once until every stamp caught up. `label` is already
  // null here (formatFeedAge rejects a negative age), so the caller renders
  // the same "no trustworthy age" wording a never-answered feed gets.
  const clockStepped = f.ageMs != null && f.ageMs < 0;
  return {
    stale: f.stale || f.suppressedBySince || clockStepped,
    // NULL, not the negative value (round-2 opus review L2). A stepped clock
    // means the age is unknowable, and worstStaleness ranks an unknown age
    // above every known one -- passing the raw negative through made it rank
    // BELOW them instead, so a genuinely unknowable source lost to a merely
    // old one and the notice named the wrong age.
    ageMs: clockStepped ? null : f.ageMs,
    label: clockStepped ? null : formatFeedAge(f.ageMs),
  };
}

// parseFeedTimestamp -- an ISO timestamp from the backend to epoch ms, or
// null. Appends 'Z' when the string carries no timezone, so a naive UTC
// timestamp is not read as local time (which makes the age NEGATIVE in US
// timezones). Extracted from SignalsTab's "Last scan" header, which had this
// inline: the order gate now measures the same age, and two copies of a
// timezone fix is exactly how the two end up disagreeing.
export function parseFeedTimestamp(ts) {
  if (typeof ts !== 'string' || !ts) return null;
  // Matches a trailing +HH:MM / -HHMM offset as well as 'Z' (round-2 opus
  // review I7). The `includes('+')` heuristic this replaces -- carried over
  // verbatim from the inline version -- appended a second 'Z' to a NEGATIVE
  // offset like "...T10:00:00-05:00", making it unparseable. Not reachable
  // from this backend (it emits 'Z' or naive UTC), but the function is now
  // shared by the order gate and the header chip.
  const utc = /(?:Z|[+-]\d{2}:?\d{2})$/.test(ts) ? ts : ts + 'Z';
  const ms = new Date(utc).getTime();
  return Number.isFinite(ms) ? ms : null;
}

// worstStaleness -- combine several staleness readings into the one worth
// warning about (opus review F3).
//
// An order action can be stale for more than one INDEPENDENT reason, and the
// dashboard's own fetch age is only one of them: /api/live_signals happily
// serves a signals_cache.json up to 4 HOURS old with a 200, so the poll can
// be seconds fresh while the price behind it is hours old. feedFreshness's
// own docstring warns that `fetchedAt` means only "this endpoint answered".
//
// An UNKNOWN age (ageMs null -- never answered, or a stepped clock) outranks
// any known age: knowing nothing is worse than knowing it is old.
export function worstStaleness(...parts) {
  const rank = p => (Number.isFinite(p.ageMs) ? p.ageMs : Infinity);
  let worst = null;
  for (const p of parts) {
    if (!p || !p.stale) continue;
    if (worst === null || rank(p) > rank(worst)) worst = p;
  }
  return worst || { stale: false, ageMs: null, label: null };
}

// ---------------------------------------------------------------------------
// staleFeedState / StaleFeedBanner — batch-80 item 1 (backlog "useData.js's
// apiFetch has no request timeout, so a HUNG backend freezes the whole
// dashboard silently instead of degrading").
//
// Adding the timeout in useData.js is what makes a hang degrade like an
// error rather than stall. This pair is what makes the degraded state
// VISIBLE. The two failure modes are otherwise indistinguishable from the
// operator's chair, because both end in "keep the last known value": every
// branch of fetchAll's merge is deliberately null-tolerant, so a dead
// backend renders pixel-for-pixel like a healthy one whose numbers have not
// moved.
//
// STALE-WITH-A-MARKER, not an error state that blanks the values. This
// follows the precedent RiskTab's anomaly card set in batch-61, where opus
// review F2 rejected withholding a last-known reading during an outage: a
// safety surface must not become LESS informative because its feed died. An
// operator reading a kill switch or a drawdown tier is better served by the
// last real value, plainly labelled as not live, than by a dash.
//
// Lives here, beside worstStaleness and staleQuoteWarning, so OverviewTab
// and RiskTab cannot word the same condition differently -- the same
// reasoning staleQuoteWarning gives for its four order surfaces. Split into
// a pure part and a render part because frontend/ has no jsdom or RTL: the
// component cannot be exercised by a test, but staleFeedState can, and it
// holds all of the decision-making.
//
// `keys` comes from useData.js (OVERVIEW_FEED_KEYS / RISK_FEED_KEYS), which
// is also where the keys are produced, so a test can check the two agree.
export function staleFeedState(fetchedAt, keys, clock) {
  const opts = { now: clock?.now, since: clock?.visibleSince };
  const parts = (Array.isArray(keys) ? keys : []).map(k =>
    feedFreshness(fetchedAt?.[k], opts));
  const worst = worstStaleness(...parts);

  // `anyEscalated` is computed across EVERY member, not read off the pool
  // winner (round-2 opus review H1). worstStaleness ranks an unknown age as
  // Infinity -- "knowing nothing is worse than knowing it is old" -- so a
  // member that has never answered ALWAYS wins the pool, and its 'pending'
  // state was then driving the banner's tone for the whole tab. Measured:
  // two feeds 13 minutes dead alongside one that never answered reported
  // {state:'pending'}, i.e. a calm grey "waiting" over two dead safety
  // feeds. The ranking is right for choosing WHICH age to show; it is the
  // wrong input for deciding whether to alarm.
  const nowMs = Number.isFinite(clock?.now) ? clock.now : Date.now();
  // Second half of the same finding: with no stamp, feedFreshness measures
  // from `since`, and nothing caps that -- so a total hang from page load
  // reverts from amber to grey on every alt-tab, forever. The page-load
  // anchor is immune to that reset, so once we have been watching longer
  // than the hard ceiling and something is still not answering, it alarms
  // and stays alarmed.
  const watchedLongerThanCeiling =
    Number.isFinite(clock?.pageLoad) && nowMs - clock.pageLoad > FEED_HARD_STALE_MS;
  const anyEscalated =
    parts.some(p => p.stale && p.state === 'stale') ||
    (watchedLongerThanCeiling && parts.some(p => p.stale));

  return { ...worst, anyEscalated };
}

// staleBannerCopy — the amber-vs-grey decision and its wording, as a pure
// function.
//
// Split out (opus review round 1, H1) because leaving the decision inside
// the component made it unprovable: frontend/ has no jsdom or RTL, so
// reintroducing the original `formatFeedAge(feed.ageMs) == null` bug left
// all 293 tests green. A wrong decision that no test can reach is the same
// failure mode this whole item exists to remove from the dashboard, so the
// decision moved to where a test can hold it and the component kept only
// the style application.
export function staleBannerCopy(feed) {
  if (!feed || !feed.stale) return null;
  // Keyed on state, NOT on a null ageMs. feedFreshness returns ageMs null
  // for BOTH 'pending' (nothing has answered, but we have not been watching
  // long enough to care) and an escalated 'stale' (never answered, now past
  // maxAgeMs from `since`) -- and worstStaleness ranks a null age as
  // Infinity, so a single never-answered feed always wins the pool. Reading
  // that null as "pending" therefore both suppressed the alarm forever on a
  // backend that hung at page load AND masked genuinely stale siblings
  // behind a calm "waiting" message.
  if (!feed.anyEscalated) {
    return { tone: 'pending', headline: 'Waiting for the first response from the backend…' };
  }
  // formatFeedAge is now only the "never render NaN min ago" backstop.
  // It returns a phrase already ending in "ago", so the suffix is stripped
  // rather than pairing it with "for".
  const age = formatFeedAge(feed.ageMs);
  // "Some data has stopped updating", not "the backend is not responding":
  // one endpoint answering 500 while the other 22 are healthy stops its own
  // feed stamping, and asserting the backend is down sends the operator to
  // check the wrong thing.
  return {
    tone: 'alert',
    headline: age
      ? `⚠ Some data has stopped updating — no successful refresh for ${age.replace(/ ago$/, '')}.`
      : '⚠ Some data has stopped updating — no successful refresh since this page loaded.',
  };
}

export function StaleFeedBanner({ feed, style }) {
  // GREY IS KEYED ON state === 'pending', NOT ON A NULL ageMs.
  //
  // The first version of this used `formatFeedAge(feed.ageMs) == null` as its
  // pending test, and that was wrong in a way that re-introduced the exact
  // trap batch-61's opus review F4 had already closed one layer down.
  // feedFreshness returns a null ageMs for TWO different states: 'pending'
  // (nothing has answered yet, but we have not been watching long enough to
  // care) and an escalated 'stale' (a feed that has never answered and has
  // now aged past maxAgeMs from `since`). Collapsing both into the neutral
  // grey branch meant a backend that hung at page load stayed on a calm
  // "waiting…" forever, over MOCK's fabricated balance and positions.
  //
  // Worse, worstStaleness ranks a null ageMs as Infinity -- "knowing nothing
  // is worse than knowing it is old" -- so a single never-answered feed
  // always WINS the pool. Two feeds two hours dead alongside one that never
  // answered therefore also rendered as "waiting". Verified against the real
  // primitives before fixing:
  //   feedFreshness(undefined, {now, since: now - 600_000})
  //     -> {state:'stale', stale:true, ageMs:null}
  //
  // Grey for genuinely-pending is still the right call -- it fires on every
  // reload for the few hundred ms before the first poll lands, and an amber
  // flash there is the alarm fatigue RiskTab's anomaly banner avoided for the
  // same reason (opus review F5, batch-61). Only the TEST for it was wrong.
  // One guard, not two (round-2 opus review L1). staleBannerCopy returns
  // null for a fresh feed, and destructuring that null would throw DURING
  // RENDER -- which App's ErrorBoundary turns into a blank Risk or Overview
  // tab, the worst possible outcome for the surface this exists to protect.
  const copy = staleBannerCopy(feed);
  if (!copy) return null;
  const alert = copy.tone === 'alert';
  return (
    <div style={{
      padding: '10px 16px', borderRadius: 9,
      background: alert ? 'rgba(202,138,4,0.07)' : 'var(--bg-subtle)',
      border: '1px solid ' + (alert ? 'rgba(202,138,4,0.35)' : 'var(--border)'),
      color: alert ? 'var(--warn)' : 'var(--text-muted)',
      fontSize: 13, fontWeight: 600,
      ...style,
    }} role="status">
      {copy.headline}
      {alert && (
        <span style={{ fontWeight: 400 }}>
          {' '}These are the last known values, not live.
        </span>
      )}
    </div>
  );
}

// staleQuoteWarning — the single wording for all four order actions, so
// Approve, bulk Approve, Close and bulk Close cannot describe the same
// condition differently. Returns null when there is nothing to warn about,
// so a caller can render `{msg && <Banner>{msg}</Banner>}`.
//
// Phrased number-agnostically (and with a PLURAL `noun` at the call sites)
// because two of the four surfaces are bulk actions covering many rows, and
// one of them (bulk Close) has no confirm modal at all — the notice sits in
// the selection bar next to the button, where singular copy would be wrong.
//
// SOFT WARN, NOT A BLOCK, on purpose: this is a paper dashboard, and a hard
// disable would trap an operator who needs to act on a stale quote -- the
// same trap batch-63 item 1 exists to undo on the close path. The age is
// named so the decision is informed rather than removed. Revisit toward a
// hard block if live trading is ever enabled from this surface.
export function staleQuoteWarning(staleness, noun = 'prices') {
  if (!staleness || !staleness.stale) return null;
  // A CACHED quote is stale for a reason that has nothing to do with age
  // (round-2 opus review M2). Reusing the age wording produced "Last
  // refreshed less than a minute ago -- mark prices may be out of date" in
  // exactly the scenario the flag exists for (dashboard polling happily,
  // Kalshi unreachable), which reads as reassurance and invites the click
  // it is trying to prevent. Say what actually happened instead.
  if (staleness.reason === 'cached') {
    return `Live quote unavailable — ${noun} came from a cached snapshot.`;
  }
  return staleness.label
    ? `Last refreshed ${staleness.label} — ${noun} may be out of date.`
    : `Not refreshed since the page loaded — ${noun} may be out of date.`;
}

// StaleQuoteNotice — the one rendering of staleQuoteWarning(), so all four
// order actions look identical as well as read identically. Presentational
// only; the decision itself lives in the two pure functions above, which is
// where the tests are (frontend/ has no jsdom/RTL, so a component cannot be
// unit-tested here — keep logic out of it).
export function StaleQuoteNotice({ staleness, noun, id }) {
  const msg = staleQuoteWarning(staleness, noun);
  if (!msg) return null;
  // role="status" alone is not enough inside a dialog (opus review F10): a
  // live region inserted with its content already present is not reliably
  // announced, so the two approve dialogs also point aria-describedby at
  // this `id` when a warning is showing.
  return (
    <p role="status" id={id} style={{
      margin: '0 0 14px', padding: '8px 12px', borderRadius: 8,
      border: '1px solid #f59e0b', background: 'rgba(245, 158, 11, 0.10)',
      color: '#f59e0b', fontSize: 12, lineHeight: 1.45,
    }}>
      ⚠ {msg}
    </p>
  );
}

// alarmSafeFlag — how a boolean safety reading should degrade when its feed
// goes stale (batch-61 item 3, opus review F2).
//
// The asymmetry is the point. A reassuring reading (`false` = "no anomaly
// detected") must NOT survive its feed dying -- that is the entire L30717
// bug, and it collapses to `undefined` so the consumer's existing "unknown"
// branch handles it. An ALARMING reading (`true`) DOES survive: a last-known
// alarm is still the loudest true thing we know, and letting an outage
// downgrade a red "Fail" to a grey "Unknown" would make the display get less
// alarming as a direct result of losing visibility -- strictly worse than
// the bug being fixed. This mirrors the anomaly card's badge precedence
// (HALT/ANOMALY outrank STATUS UNAVAILABLE; NORMAL/INACTIVE do not).
//
// Returns true | false | undefined, so callers can keep a three-state
// (pass / fail / unknown) rendering rather than inventing a fourth.
export function alarmSafeFlag(value, stale) {
  // ANY truthy reading is an alarm, normalized to `true`. `=== true` alone
  // would withhold a truthy non-boolean (1, "yes") on staleness -- the exact
  // opposite of the documented asymmetry. Reachable in principle: the backend
  // bool()-coerces anomaly_detected but NOT the sibling should_halt, and
  // mapAnomalyStatus passes both through raw, so nothing enforces the
  // invariant this relied on (opus review F5).
  if (value) return true;
  if (value === false && !stale) return false;
  // Everything else -- a withheld reassurance, or an already-unknown null /
  // undefined -- collapses to undefined, so the return really is the three
  // values a caller's pass/fail/unknown rendering expects.
  return undefined;
}

// useFeedClock — the ticking half of the above. feedFreshness() is pure and
// evaluated during render, so on its own a feed only becomes visibly stale
// if something else happens to re-render the card.
//
// opus review F1 (round 1, the severe one): every re-render source dies in
// exactly the failure mode this feature exists to surface. Renders come from
// fetchAll's setData, handleSSEEvent, and fetchWeatherAlerts. apiFetch has
// no timeout, so a backend that HANGS rather than dies never settles
// Promise.allSettled, never calls setData, and never re-renders -- while
// /api/stream's generator blocks inside _build_stream_data() so no SSE
// message and no SSE error fires either. The card would sit on its last
// computed value ('fresh', green NORMAL) indefinitely. The interval below is
// the independent heartbeat that makes staleness observable without
// depending on any request completing.
//
// THE CLOCK IS A MODULE-LEVEL SINGLETON, NOT PER-COMPONENT STATE (opus
// review F1, round 2). App renders tabs as `<ErrorBoundary key={activeTab}>`,
// so RiskTab and KillSwitchCriteriaCard fully unmount and remount on every
// tab switch. A `useState(() => Date.now())` therefore reset `visibleSince`
// to "now" on each visit -- and since the polling that produces `fetchedAt`
// lives in App/useData and keeps running across tab switches, that threw
// away evidence actually collected, with no polling gap to justify it. The
// measured effect: a dead feed read `fresh` at a real age of 751s and
// climbing when the operator revisited Risk every 150s, i.e. the card showed
// green NORMAL and the kill-switch checklist showed a green "Anomaly clear"
// for the first 3 minutes of EVERY visit -- reinstating the exact L30717
// blind spot on the more dangerous surface, precisely while the operator is
// reading the checklist to decide whether to lift the kill switch.
//
// Hoisting the state out of React fixes that (page load is genuinely when we
// started watching, and a remount is not a new page load) and, as a side
// effect, collapses the two mounted consumers onto ONE interval and ONE
// listener instead of one each.
// `pageLoad` is set once and NEVER written again -- deliberately unlike
// `visibleSince`, which _onFeedClockVisible resets on every hidden->visible
// transition. feedFreshness's FEED_HARD_STALE_MS ceiling is gated behind
// `hasStamp`, so a feed that has NEVER answered gets an uncapped `since`
// credit: an operator alt-tabbing more often than FEED_STALE_MS keeps
// restarting its tolerance window and it never escalates past 'pending'.
// That is exactly the "repeated alt-tabbing must not defer an alarm
// indefinitely" case the ceiling exists for, on the one path it cannot
// reach. staleFeedState uses this anchor to close it (round-2 opus review).
const _feedClock = {
  now: Date.now(),
  visibleSince: Date.now(),
  pageLoad: Date.now(),
};
const _feedClockSubscribers = new Set();
let _feedClockTimer = null;
let _feedClockTickMs = null;

function _publishFeedClock() {
  // A NEW object each publish: subscribers store it in useState, which bails
  // out of a re-render on Object.is equality.
  const snapshot = { ..._feedClock };
  for (const notify of _feedClockSubscribers) notify(snapshot);
}

function _onFeedClockVisible() {
  if (typeof document !== 'undefined' && document.hidden) return;
  // Only a real hidden -> visible transition moves visibleSince. See
  // feedFreshness's `since` note for why, and for the hard ceiling that
  // stops repeated alt-tabbing from suppressing an alarm forever.
  _feedClock.now = Date.now();
  _feedClock.visibleSince = Date.now();
  _publishFeedClock();
}

function _startFeedClock(tickMs) {
  // KNOWN, DELIBERATE LIMITATION (opus review F13): the FIRST subscriber's
  // tickMs wins for the lifetime of the timer -- a later subscriber asking
  // for a shorter interval silently gets the incumbent's. Latent today
  // (every consumer uses the default, and only one tab is mounted at a
  // time), and left alone rather than "fixed" blind, since a restart path
  // is untestable here (no jsdom/RTL). It is called out because it is a
  // trap: do NOT try to tighten a consumer's resolution by passing a
  // smaller tickMs -- it may do nothing. batch-63's order gate deliberately
  // measures its age with Date.now() at render instead, for this reason.
  if (_feedClockTimer !== null) return;
  _feedClockTickMs = tickMs;
  _feedClockTimer = setInterval(() => {
    _feedClock.now = Date.now();
    _publishFeedClock();
  }, tickMs);
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', _onFeedClockVisible);
  }
}

function _stopFeedClock() {
  if (_feedClockSubscribers.size > 0 || _feedClockTimer === null) return;
  clearInterval(_feedClockTimer);
  _feedClockTimer = null;
  _feedClockTickMs = null;
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', _onFeedClockVisible);
  }
}

export function useFeedClock(tickMs = FEED_STALE_MS / 3) {
  // Guarded like feedFreshness's options bag (opus review F6): an unvalidated
  // tickMs of 0/NaN becomes setInterval(fn, 0), i.e. a re-render of the whole
  // Risk tab every tick. Same class of caller bug, same fail-closed answer.
  const safeTick = Number.isFinite(tickMs) && tickMs >= 1000 ? tickMs : FEED_STALE_MS / 3;
  const [clock, setClock] = useState(_feedClock);
  useEffect(() => {
    _feedClockSubscribers.add(setClock);
    // Was the clock actually STOPPED before this mount? If so, nothing has
    // been advancing `visibleSince` either (_stopFeedClock removes the
    // visibilitychange listener), so the whole gap is time we could not have
    // polled through and the `since` credit should cover it -- see below.
    const wasStopped = _feedClockTimer === null;
    _startFeedClock(safeTick);
    // REFRESH, then adopt (opus review F1, batch-63). Adopting alone was not
    // enough: App renders tabs as `<ErrorBoundary key={activeTab}>`, so when
    // the last feed-clock consumer unmounts, _stopFeedClock clears both the
    // interval AND the visibilitychange listener -- from that moment nothing
    // writes `_feedClock.now` and it is frozen at whatever it was, while
    // useData's polling keeps running and keeps advancing `fetchedAt`. On
    // returning to the tab, mounting adopted that frozen `now` and every
    // consumer read the feed as fresh until the first tick up to a full
    // interval later. That reinstated the exact blind spot the singleton was
    // introduced to close (batch-61's own note above), on RiskTab's
    // kill-switch checklist as well as batch-63's order gates.
    _feedClock.now = Date.now();
    // ...and `visibleSince` with it, but ONLY across a genuine stopped gap
    // and only when the page is actually visible (round-2 opus review L1).
    // Refreshing `now` alone left the pair inconsistent: `now` jumped
    // forward while `visibleSince` stayed at its pre-background value, so
    // feedFreshness's `since` credit -- which exists precisely so a
    // visibility gap cannot fabricate a feed-down alarm -- was unavailable
    // at the one moment it is needed, flashing a false "monitor not
    // responding" amber on RiskTab for the first poll after returning.
    // Gating on `wasStopped` keeps batch-61's fix intact: a remount while
    // the clock is still running must NOT reset the window, which is the
    // bug that let a dead feed read fresh at 751s.
    if (wasStopped && !(typeof document !== 'undefined' && document.hidden)) {
      _feedClock.visibleSince = _feedClock.now;
    }
    setClock({ ..._feedClock });
    return () => {
      _feedClockSubscribers.delete(setClock);
      _stopFeedClock();
    };
  }, [safeTick]);
  return clock;
}

// Test seam: reset the singleton between unit tests. Not used by app code.
export function __resetFeedClockForTests(now = Date.now()) {
  _feedClock.now = now;
  _feedClock.visibleSince = now;
  _feedClockSubscribers.clear();
  if (_feedClockTimer !== null) {
    clearInterval(_feedClockTimer);
    _feedClockTimer = null;
    _feedClockTickMs = null;
  }
}
