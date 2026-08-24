import React, { useState, useEffect, useRef } from 'react';

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
export function TableSkeleton({ rows = 5, columns = 8 }) {
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
      <style>{`@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }`}</style>
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
          return <circle key={i} cx={xs[idx]} cy={ys[idx]} r="4" fill="#f59e0b" stroke="white" strokeWidth="1.5" />;
        })}
        {/* Current balance endpoint dot */}
        <circle cx={xs[xs.length - 1]} cy={ys[ys.length - 1]} r="4" fill="#3b82f6" stroke="white" strokeWidth="2" />
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
              fill={tip.isEvent ? '#f59e0b' : '#3b82f6'} stroke="white" strokeWidth="2"
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
    const styles = {
      error:   { background: '#fee2e2', color: '#dc2626' },
      warning: { background: '#fef9c3', color: '#ca8a04' },
      info:    { background: '#dbeafe', color: '#2563eb' },
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
              <span style={{ fontSize: 13, flex: 1, lineHeight: 1.5 }}>{evt.message || evt.msg || evt.text || JSON.stringify(evt)}</span>
              <span style={{ fontSize: 11, color: 'var(--text-faint)', whiteSpace: 'nowrap', marginTop: 2 }}>
                {relTime(evt.ts || evt.timestamp)}
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
                fill={color} stroke="white" strokeWidth={isHov ? 2.5 : 1.5}
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
