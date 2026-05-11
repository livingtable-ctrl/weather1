import React, {
  useState, useMemo, useEffect, useRef, useContext, createContext, Component,
} from 'react';

// ---------------------------------------------------------------------------
// Error boundary — catches render crashes and shows the error instead of
// a white screen so we can diagnose tab-specific issues
// ---------------------------------------------------------------------------
class ErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(e) { return { error: e }; }
  render() {
    if (this.state.error) {
      return (
        <main style={{ maxWidth: 800, margin: '60px auto', padding: '0 28px' }}>
          <div style={{ padding: '20px 24px', borderRadius: 12, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)' }}>
            <p style={{ margin: 0, fontWeight: 700, color: '#ef4444', fontSize: 15 }}>Tab crashed — JS error</p>
            <pre style={{ margin: '12px 0 0', fontSize: 12, whiteSpace: 'pre-wrap', color: 'var(--text-muted)', fontFamily: 'ui-monospace, monospace' }}>
              {this.state.error?.message}
              {'\n\n'}
              {this.state.error?.stack}
            </pre>
            <button onClick={() => this.setState({ error: null })}
              style={{ marginTop: 14, padding: '7px 14px', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text)', cursor: 'pointer', fontSize: 13 }}>
              Dismiss
            </button>
          </div>
        </main>
      );
    }
    return this.props.children;
  }
}
import MOCK from './mockData.js';
import useData, { authHeader } from './useData.js';

// ---------------------------------------------------------------------------
// City display-name normalization  (backend uses CamelCase keys)
// ---------------------------------------------------------------------------
const CITY_NAMES = {
  SanFrancisco: 'San Francisco',
  NYC: 'New York',
  OklahomaCity: 'Oklahoma City',
  SanAntonio: 'San Antonio',
  Washington: 'Washington DC',
};
const normCity = (c) => CITY_NAMES[c] || c;

// net_edge is stored as a ratio and can exceed 1.0
const fmtEdge = (e) => (e >= 1 ? '>100%' : `+${(e * 100).toFixed(1)}%`);

// ---------------------------------------------------------------------------
// DataContext — exported so useData.js (Task 3) can plug in live data
// ---------------------------------------------------------------------------
export const DataContext = createContext(null);

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------
const THEMES = {
  light: {
    '--bg-page': '#fafafa', '--bg-card': '#ffffff', '--bg-subtle': '#f8f9fb',
    '--bg-muted': '#f1f5f9', '--border': '#e7eaef',
    '--text': '#0f172a', '--text-muted': '#64748b', '--text-faint': '#94a3b8',
  },
  dark: {
    '--bg-page': '#0f1115', '--bg-card': '#181b22', '--bg-subtle': '#1e222a',
    '--bg-muted': '#2a2f3a', '--border': '#2e333d',
    '--text': '#eef0f5', '--text-muted': '#a3acb8', '--text-faint': '#737d8a',
  },
};
function applyTheme(t) {
  Object.entries(THEMES[t]).forEach(([k, v]) => document.documentElement.style.setProperty(k, v));
}

// ---------------------------------------------------------------------------
// Shared: Nav
// ---------------------------------------------------------------------------
function Nav({ active, onNavigate, theme, onToggleTheme, connected }) {
  const TABS = ['Overview', 'Positions', 'Signals', 'Forecast', 'Analytics', 'Risk', 'Trades', 'Settings'];
  const M = useContext(DataContext);
  const ks = M?.stats?.kill_switch;

  return (
    <header style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '16px 28px', borderBottom: '1px solid var(--border)',
      background: 'var(--bg-card)', position: 'sticky', top: 0, zIndex: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 28 }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 26, height: 26, borderRadius: 7,
            background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
            display: 'grid', placeItems: 'center', color: 'white', fontWeight: 700, fontSize: 12,
          }}>K</div>
          <div style={{ fontWeight: 600, fontSize: 14 }}>Kalshi Weather</div>
        </div>
        {/* Tab nav */}
        <nav style={{ display: 'flex', gap: 3, fontSize: 13 }}>
          {TABS.map(tab => (
            <button key={tab} onClick={() => onNavigate(tab)} style={{
              padding: '7px 13px', borderRadius: 7, border: 'none',
              color: active === tab ? 'var(--text)' : 'var(--text-muted)',
              background: active === tab ? 'var(--bg-muted)' : 'transparent',
              fontWeight: active === tab ? 600 : 500, cursor: 'pointer', fontFamily: 'inherit',
            }}>{tab}</button>
          ))}
        </nav>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {/* SSE live indicator */}
        <span title={connected ? 'Live stream connected' : 'Stream disconnected'} style={{
          display: 'inline-flex', alignItems: 'center', gap: 5,
          padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600,
          background: connected ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.10)',
          color: connected ? '#16a34a' : '#ef4444',
        }}>
          <span style={{
            width: 6, height: 6, borderRadius: '50%',
            background: connected ? '#16a34a' : '#ef4444',
            boxShadow: connected ? '0 0 0 2px rgba(34,197,94,0.3)' : 'none',
            display: 'inline-block',
          }} />
          {connected ? 'Live' : 'Offline'}
        </span>

        {/* Env badge */}
        <span style={{
          display: 'inline-flex', alignItems: 'center',
          padding: '4px 10px', borderRadius: 999,
          background: 'rgba(234,179,8,0.12)', color: '#ca8a04',
          fontSize: 11, fontWeight: 600,
        }}>Demo · Paper</span>

        {/* Override */}
        <button onClick={() => onNavigate('Settings')} style={{
          padding: '7px 13px', borderRadius: 7, border: '1px solid var(--border)',
          background: 'var(--bg-card)', color: 'var(--text-muted)', fontWeight: 500, fontSize: 12, cursor: 'pointer',
        }}>Override</button>

        {/* Theme toggle */}
        <button onClick={onToggleTheme} title="Toggle theme" style={{
          padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border)',
          background: 'var(--bg-card)', color: 'var(--text)', fontSize: 14, cursor: 'pointer',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 32, height: 30,
        }}>{theme === 'dark' ? '☀' : '☾'}</button>

        {/* Kill switch */}
        <button
          onClick={() => { if (window.confirm('Engage kill switch? This halts all trading.')) fetch('/api/halt', { method: 'POST', headers: authHeader() }); }}
          style={{
            padding: '7px 13px', borderRadius: 7,
            border: ks ? '1px solid #ef4444' : '1px solid var(--border)',
            background: ks ? 'rgba(239,68,68,0.1)' : 'var(--bg-card)',
            color: ks ? '#ef4444' : 'var(--text)', fontWeight: 500, fontSize: 12, cursor: 'pointer',
          }}>
          {ks ? '⛔ Halted' : 'Kill switch'}
        </button>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------------
// Shared: InfoIcon tooltip
// ---------------------------------------------------------------------------
function InfoIcon({ tip }) {
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
// Shared: StatCard
// ---------------------------------------------------------------------------
function StatCard({ label, value, delta, deltaTone, sub, tooltip }) {
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
// BalanceSparkline  — Fix 5
// Inline SVG chart of /api/balance_history  [{ts, balance, event}]
// ---------------------------------------------------------------------------
function BalanceSparkline({ hist }) {
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

  // Mark event points (non-null event field)
  const events = hist.filter(p => p.event);
  const lastBalance = balances[balances.length - 1];

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
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}>
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
// SystemEventsCard  — Fix 4
// Renders M.alerts from /api/system-events as a timestamped feed
// ---------------------------------------------------------------------------
function SystemEventsCard({ alerts }) {
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
              <span style={{ fontSize: 13, flex: 1, lineHeight: 1.5 }}>{evt.message || evt.msg || JSON.stringify(evt)}</span>
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
// OverviewTab
// ---------------------------------------------------------------------------
function OverviewTab() {
  const M = useContext(DataContext);
  const s = M.stats;
  const grad = s.graduation;
  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
  const pnlToday = s.today_pnl;
  const pnlKnown = pnlToday != null;

  return (
    <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
      <div style={{ marginBottom: 18 }}>
        <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 500, marginBottom: 3 }}>{today}</div>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, letterSpacing: '-0.025em', fontFamily: "'Source Serif 4', Georgia, serif" }}>
          {!pnlKnown
            ? <>{s.open_count} positions open{grad.ready ? ' — graduation gate cleared.' : '.'}</>
            : pnlToday >= 0
              ? <>Up <span style={{ color: '#16a34a' }}>+${Number(pnlToday).toFixed(2)}</span> today — {s.open_count} positions open{grad.ready ? ', graduation gate cleared.' : '.'}</>
              : <>Down <span style={{ color: '#ef4444' }}>-${Math.abs(Number(pnlToday)).toFixed(2)}</span> today — {s.open_count} positions open.</>
          }
        </h1>
      </div>

      {/* KPI row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
        <StatCard label="Paper balance" tooltip="Simulated cash balance in the paper-trading sandbox. No real money."
          value={'$' + Number(s.balance).toFixed(2)}
          delta={(s.balance >= s.starting_balance ? '+' : '') + ((Number(s.balance) - Number(s.starting_balance)) / Number(s.starting_balance) * 100).toFixed(1) + '%'}
          deltaTone={s.balance >= s.starting_balance ? 'pos' : 'neg'}
          sub={'from $' + Number(s.starting_balance).toFixed(2) + ' start'} />
        <StatCard label="Open positions" tooltip="Active contracts that haven't expired or been closed yet."
          value={s.open_count} sub={s.settled_count + ' settled so far'} />
        <StatCard label="Win rate" tooltip="% of settled trades that were profitable."
          value={s.win_rate != null ? (s.win_rate * 100).toFixed(1) + '%' : '—'} />
        <StatCard label="Brier score" tooltip="Forecast quality (0=perfect, 0.25=random). Lower is better. Target ≤0.20."
          value={s.brier != null ? Number(s.brier).toFixed(3) : '—'}
          deltaTone="pos" sub="target ≤0.20" />
      </div>

      {/* Graduation gates */}
      <section style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 14, padding: '20px', marginBottom: 18,
      }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Graduation progress</h3>
        <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 16, lineHeight: 1.4 }}>
          Three gates to go live: 30+ trades, $50+ P&L, Brier ≤0.20.{' '}
          {grad.ready ? '✓ All gates cleared!' : 'Keep building track record…'}
        </p>
        <div style={{ display: 'grid', gap: 14 }}>
          {[
            { label: 'Trades',  current: grad.trades_done, target: grad.trades_target, unit: '',  invert: false, complete: grad.trades_done >= grad.trades_target },
            { label: 'P&L',    current: grad.total_pnl,   target: grad.pnl_target,    unit: '$', invert: false, complete: grad.total_pnl >= grad.pnl_target },
            { label: 'Brier',  current: grad.brier,       target: grad.brier_target,  unit: '',  invert: true,  complete: grad.brier <= grad.brier_target },
          ].map((g) => {
            const pct = g.invert
              ? Math.min(100, Math.max(0, (1 - g.current / 0.25) * 100))
              : Math.min(100, (g.current / g.target) * 100);
            return (
              <div key={g.label}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                  <span style={{ fontWeight: 600 }}>{g.label}</span>
                  <span style={{ fontFamily: 'ui-monospace, monospace', color: g.complete ? '#16a34a' : 'var(--text-muted)' }}>
                    {g.unit}{g.invert ? g.current.toFixed(3) : (g.unit === '$' ? g.current.toFixed(2) : Math.round(g.current))}/{g.unit}{g.target}
                  </span>
                </div>
                <div style={{ height: 8, background: 'var(--bg-muted)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ width: pct + '%', height: '100%', background: g.complete ? '#16a34a' : '#3b82f6', transition: 'width 0.4s' }} />
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Fear/Greed + Data sources */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 12, marginBottom: 18 }}>
        <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px' }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Fear / Greed</h3>
          <div style={{ textAlign: 'center', padding: '20px 0' }}>
            <div style={{ fontSize: 48, fontWeight: 700, color: s.fear_greed >= 65 ? '#16a34a' : s.fear_greed >= 40 ? '#ca8a04' : '#ef4444' }}>
              {s.fear_greed}
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 8 }}>{s.fear_greed_label}</div>
          </div>
          <div style={{ padding: '10px 12px', borderRadius: 8, background: 'var(--bg-muted)', fontSize: 11, color: 'var(--text-muted)' }}>
            Market sentiment based on volume, spread, and price action.
          </div>
        </section>

        <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px' }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 14 }}>Data sources</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 9 }}>
            {M.circuitBreakers.map((cb) => {
              const isOpen = cb.state === 'open';
              return (
                <div key={cb.key} style={{
                  padding: '9px 11px', borderRadius: 8, background: 'var(--bg-subtle)',
                  border: '1px solid ' + (isOpen ? '#ef4444' : 'var(--border)'),
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: isOpen ? '#ef4444' : '#16a34a', display: 'inline-block' }} />
                    <span style={{ fontSize: 11, fontWeight: 600 }}>{cb.label}</span>
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-faint)', fontFamily: 'ui-monospace, monospace' }}>
                    {isOpen ? `Retry ${cb.retry_in_s}s` : cb.latency_ms != null ? `${cb.latency_ms}ms` : 'OK'}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>

      {/* Summary cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
        {[
          { title: 'Open Positions',    count: M.positions.length,         desc: 'View all with detail' },
          { title: 'Top Opportunities', count: M.opportunities.length,     desc: 'Signals with edge' },
          { title: 'Closed Trades',     count: M.closedTrades.length,      desc: 'History & P&L' },
          { title: 'Forecast Quality',  count: Object.keys(M.cityBrier).length, desc: 'Cities tracked' },
        ].map((card) => (
          <section key={card.title} style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 14, padding: '18px 20px',
          }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>{card.title}</h3>
            <div style={{ fontSize: 24, fontWeight: 700, color: '#3b82f6', marginBottom: 6 }}>{card.count}</div>
            <div style={{ color: 'var(--text-faint)', fontSize: 12 }}>{card.desc}</div>
          </section>
        ))}
      </div>

      {/* Balance history sparkline — Fix 5 */}
      <BalanceSparkline hist={M.balanceHist} />

      {/* System events feed — Fix 4 */}
      <SystemEventsCard alerts={M.alerts} />
    </main>
  );
}

// ---------------------------------------------------------------------------
// PositionsTab
// ---------------------------------------------------------------------------
function PositionsTab() {
  const M = useContext(DataContext);
  const [filter, setFilter] = useState('');
  const [sortKey, setSortKey] = useState('edge');
  const [selectedPos, setSelectedPos] = useState(null);

  const filtered = useMemo(() => {
    const f = filter.toLowerCase();
    const rows = M.positions.filter(p =>
      !f || normCity(p.city).toLowerCase().includes(f) || p.ticker.toLowerCase().includes(f)
    );
    return [...rows].sort((a, b) =>
      sortKey === 'edge' ? b.edge - a.edge : sortKey === 'cost' ? b.cost - a.cost : a.age_h - b.age_h
    );
  }, [filter, sortKey, M.positions]);

  return (
    <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 18 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em' }}>Open Positions</h1>
          <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
            {M.positions.length} positions · ${M.positions.reduce((a, p) => a + p.cost, 0).toFixed(2)} deployed
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <input placeholder="Filter by city or ticker…" value={filter} onChange={e => setFilter(e.target.value)}
            style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 13, width: 240, outline: 'none', color: 'var(--text)' }} />
          <select value={sortKey} onChange={e => setSortKey(e.target.value)}
            style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 13, cursor: 'pointer', color: 'var(--text)' }}>
            <option value="edge">Sort by Edge</option>
            <option value="cost">Sort by Cost</option>
            <option value="age">Sort by Age</option>
          </select>
        </div>
      </div>

      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 12 }}>
              {['Ticker', 'City', 'Side', 'Cost', 'Qty', 'Mark', 'Fcst', 'Edge', 'Model', 'Expiry', 'Age'].map((h, i) => (
                <th key={h} style={{ padding: '12px 16px', textAlign: i >= 3 && i <= 7 ? 'right' : 'left', fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((p, i) => (
              <tr key={i} onClick={() => setSelectedPos(selectedPos === p ? null : p)} style={{
                borderBottom: '1px solid var(--bg-muted)', cursor: 'pointer',
                background: selectedPos === p ? 'var(--bg-subtle)' : 'transparent',
              }}>
                <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#3b82f6' }}>{p.ticker}</td>
                <td style={{ padding: '14px 16px', fontWeight: 600 }}>{normCity(p.city)}</td>
                <td style={{ padding: '14px 16px' }}>
                  <span style={{
                    display: 'inline-block', padding: '2px 8px', borderRadius: 999,
                    background: p.side === 'yes' ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
                    color: p.side === 'yes' ? '#16a34a' : '#ef4444', fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                  }}>{p.side}</span>
                </td>
                <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>${p.cost.toFixed(2)}</td>
                <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>{p.qty}</td>
                <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)' }}>{p.mark.toFixed(2)}</td>
                <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>{p.fcst.toFixed(2)}</td>
                <td style={{ padding: '14px 16px', textAlign: 'right', color: '#16a34a', fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>+{(p.edge * 100).toFixed(1)}%</td>
                <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-muted)' }}>{p.model}</td>
                <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-muted)' }}>{p.expiry}</td>
                <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-faint)' }}>{p.age_h}h</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {selectedPos && (
        <section style={{ marginTop: 18, background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px 24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
            <div>
              <h3 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>{normCity(selectedPos.city)} · {selectedPos.ticker}</h3>
              <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
                Opened {selectedPos.age_h}h ago · {selectedPos.model} forecast · closes {selectedPos.expiry}
              </p>
            </div>
            <button onClick={() => setSelectedPos(null)} style={{ padding: '6px 12px', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 12, cursor: 'pointer', color: 'var(--text)' }}>Close</button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16 }}>
            {[
              { label: 'Side',           value: selectedPos.side.toUpperCase() },
              { label: 'Cost basis',     value: '$' + selectedPos.cost.toFixed(2) },
              { label: 'Quantity',       value: selectedPos.qty + ' contracts' },
              { label: 'Current mark',   value: selectedPos.mark.toFixed(2) },
              { label: 'Unrealized P&L', value: '+$' + ((selectedPos.mark - selectedPos.cost / selectedPos.qty) * selectedPos.qty).toFixed(2) },
            ].map((item) => (
              <div key={item.label}>
                <div style={{ color: 'var(--text-faint)', fontSize: 11, marginBottom: 4 }}>{item.label}</div>
                <div style={{ fontWeight: 600, fontSize: 15, fontFamily: 'ui-monospace, monospace' }}>{item.value}</div>
              </div>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// SignalsTab  — approve/reject per row, real-data-safe field names
// ---------------------------------------------------------------------------
function SignalsTab() {
  const M = useContext(DataContext);
  const [minEdge, setMinEdge] = useState(5);
  const [selectedOpp, setSelectedOpp] = useState(null);
  const [actionMsg, setActionMsg] = useState('');

  const filtered = useMemo(() =>
    M.opportunities.filter(o => o.edge_pct >= minEdge),
    [minEdge, M.opportunities]
  );

  function handleAction(opp, action) {
    if (action === 'reject') {
      setActionMsg(`✗ ${opp.ticker} rejected`);
      setTimeout(() => setActionMsg(''), 2500);
      return;
    }
    // approve → place a manual paper order at the current market price
    fetch('/api/paper-order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader() },
      body: JSON.stringify({
        ticker:      opp.ticker,
        side:        (opp.side || 'yes').toLowerCase(),
        quantity:    1,
        entry_price: opp.market_prob != null ? opp.market_prob / 100 : 0.5,
        entry_prob:  opp.forecast_prob != null ? opp.forecast_prob / 100 : null,
        net_edge:    opp.edge_pct != null ? opp.edge_pct / 100 : null,
        city:        opp.city || null,
        target_date: opp.expiry || null,
      }),
    })
      .then(r => r.json())
      .then(d => {
        setActionMsg(d.error ? `✗ ${d.error}` : `✓ ${opp.ticker} placed`);
        setTimeout(() => setActionMsg(''), 3000);
      })
      .catch(() => {
        setActionMsg(`✗ Request failed`);
        setTimeout(() => setActionMsg(''), 3000);
      });
  }

  return (
    <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 18 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em' }}>Signals</h1>
          <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
            {filtered.length} opportunities above {minEdge}% edge
          </p>
          <p style={{ margin: '6px 0 0', color: 'var(--text-muted)', fontSize: 12, maxWidth: 560, lineHeight: 1.5 }}>
            Each row is a market the bot would enter. Stars rank conviction. Click a row to expand; use Approve / Reject to act.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {actionMsg && (
            <span style={{ fontSize: 12, color: actionMsg.startsWith('✓') ? '#16a34a' : '#ef4444', fontWeight: 600 }}>{actionMsg}</span>
          )}
          <label style={{ fontSize: 13, color: 'var(--text-muted)' }}>Min edge:</label>
          <input type="range" min="0" max="30" step="1" value={minEdge} onChange={e => setMinEdge(+e.target.value)} style={{ width: 120 }} />
          <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'ui-monospace, monospace', minWidth: 40 }}>{minEdge}%</span>
        </div>
      </div>

      {/* Legend */}
      <section style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 12, padding: '12px 16px', marginBottom: 14,
        display: 'flex', flexWrap: 'wrap', gap: 20, alignItems: 'center', fontSize: 12,
      }}>
        <span style={{ color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', fontSize: 11 }}>Legend</span>
        {[
          { icon: '★★', color: '#16a34a', label: 'Strong signal', note: 'high edge & model agreement' },
          { icon: '★',  color: '#ca8a04', label: 'Moderate signal', note: '' },
          { icon: '⚠',  color: '#ca8a04', label: 'Near threshold', note: 'small temp swings flip outcome' },
          { icon: '↔',  color: 'var(--text-muted)', label: 'Hedge', note: 'opposite side of open position' },
        ].map(({ icon, color, label, note }) => (
          <span key={label} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ color, fontWeight: 700, fontSize: 13 }}>{icon}</span>
            <span>{label}</span>
            {note && <span style={{ color: 'var(--text-muted)' }}>· {note}</span>}
          </span>
        ))}
      </section>

      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden', marginBottom: 18 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 12 }}>
              {['★', 'Ticker', 'City', 'Side', 'Forecast', 'Market', 'Edge', 'Risk', 'Kelly $', 'Flags', 'Action'].map((h, i) => (
                <th key={h} style={{
                  padding: '12px 16px', fontWeight: 600, borderBottom: '1px solid var(--border)',
                  textAlign: [4, 5, 6, 8].includes(i) ? 'right' : 'left',
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((o, i) => {
              const side = o.side.toLowerCase();
              const stars = o.stars || '★';
              const starColor = stars.length >= 2 ? '#16a34a' : stars.length === 1 ? '#ca8a04' : 'var(--text-faint)';
              const kelly = o.kelly_dollars > 0 ? '$' + o.kelly_dollars.toFixed(2) : '—';
              return (
                <tr key={i} onClick={() => setSelectedOpp(selectedOpp === o ? null : o)} style={{
                  borderBottom: '1px solid var(--bg-muted)', cursor: 'pointer',
                  background: selectedOpp === o ? 'var(--bg-subtle)' : o.already_held ? 'rgba(59,130,246,0.04)' : 'transparent',
                }}>
                  <td style={{ padding: '12px 16px', color: starColor, letterSpacing: 1 }}>{stars}</td>
                  <td style={{ padding: '12px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#3b82f6' }}>
                    {o.ticker}
                  </td>
                  <td style={{ padding: '12px 16px', fontWeight: 600 }}>{normCity(o.city)}</td>
                  <td style={{ padding: '12px 16px' }}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 999,
                      background: side === 'yes' ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
                      color: side === 'yes' ? '#16a34a' : '#ef4444',
                      fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                    }}>{side}</span>
                  </td>
                  <td style={{ padding: '12px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)' }}>
                    {o.forecast_prob.toFixed(1)}%
                  </td>
                  <td style={{ padding: '12px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)' }}>
                    {o.market_prob.toFixed(1)}%
                  </td>
                  <td style={{ padding: '12px 16px', textAlign: 'right', color: '#16a34a', fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>
                    +{o.edge_pct.toFixed(1)}%
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 999, fontSize: 10, fontWeight: 600,
                      background: o.time_risk === 'LOW' ? 'rgba(34,197,94,0.12)' : o.time_risk === 'MEDIUM' ? 'rgba(234,179,8,0.12)' : 'rgba(239,68,68,0.12)',
                      color: o.time_risk === 'LOW' ? '#16a34a' : o.time_risk === 'MEDIUM' ? '#ca8a04' : '#ef4444',
                    }}>{o.time_risk}</span>
                  </td>
                  <td style={{ padding: '12px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)', fontSize: 12 }}>
                    {kelly}
                  </td>
                  <td style={{ padding: '12px 16px', fontSize: 13 }}>
                    {o.near_threshold && <span title="Near threshold" style={{ color: '#ca8a04' }}>⚠ </span>}
                    {o.is_hedge      && <span title="Hedges open position" style={{ color: 'var(--text-muted)' }}>↔ </span>}
                    {o.already_held  && <span title="Already held" style={{ color: '#3b82f6' }}>● </span>}
                    {!o.near_threshold && !o.is_hedge && !o.already_held && <span style={{ color: 'var(--text-faint)' }}>—</span>}
                  </td>
                  <td style={{ padding: '12px 16px' }} onClick={e => e.stopPropagation()}>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button onClick={() => handleAction(o, 'approve')} style={{
                        padding: '4px 10px', borderRadius: 6, border: '1px solid #16a34a',
                        background: 'rgba(34,197,94,0.08)', color: '#16a34a',
                        fontSize: 11, fontWeight: 600, cursor: 'pointer',
                      }}>✓</button>
                      <button onClick={() => handleAction(o, 'reject')} style={{
                        padding: '4px 10px', borderRadius: 6, border: '1px solid var(--border)',
                        background: 'transparent', color: 'var(--text-muted)',
                        fontSize: 11, fontWeight: 600, cursor: 'pointer',
                      }}>✗</button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      {selectedOpp && (
        <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px 24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
            <div>
              <h3 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>{normCity(selectedOpp.city)} · {selectedOpp.ticker}</h3>
              <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
                {selectedOpp.signal || selectedOpp.stars} · forecast {selectedOpp.forecast_prob.toFixed(1)}% vs market {selectedOpp.market_prob.toFixed(1)}%
              </p>
            </div>
            <button onClick={() => setSelectedOpp(null)} style={{ padding: '6px 12px', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 12, cursor: 'pointer', color: 'var(--text)' }}>Close</button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 16 }}>
            {[
              { label: 'Edge',         value: '+' + selectedOpp.edge_pct.toFixed(1) + '%' },
              { label: 'Forecast p',   value: selectedOpp.forecast_prob.toFixed(1) + '%' },
              { label: 'Market p',     value: selectedOpp.market_prob.toFixed(1) + '%' },
              { label: 'Kelly $',      value: selectedOpp.kelly_dollars > 0 ? '$' + selectedOpp.kelly_dollars.toFixed(2) : '—' },
            ].map(item => (
              <div key={item.label}>
                <div style={{ color: 'var(--text-faint)', fontSize: 11, marginBottom: 4 }}>{item.label}</div>
                <div style={{ fontWeight: 600, fontSize: 15, fontFamily: 'ui-monospace, monospace' }}>{item.value}</div>
              </div>
            ))}
          </div>
          <div style={{ padding: '14px 16px', borderRadius: 8, background: 'var(--bg-muted)', fontSize: 12 }}>
            <strong>Suggested action:</strong> Buy {selectedOpp.side.toUpperCase()} — forecast probability ({selectedOpp.forecast_prob.toFixed(1)}%) exceeds market ({selectedOpp.market_prob.toFixed(1)}%) by {selectedOpp.edge_pct.toFixed(1)} pts.
          </div>
        </section>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// ForecastTab
// ---------------------------------------------------------------------------
function ForecastTab() {
  const M = useContext(DataContext);
  return (
    <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
      <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Forecast</h1>
      <p style={{ margin: '0 0 24px', color: 'var(--text-muted)', fontSize: 13 }}>
        Today &amp; tomorrow forecasts, city calibration, model ensemble spread.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, marginBottom: 18 }}>
        {[['Today', M.todayForecasts], ['Tomorrow', M.tomorrowForecasts]].map(([label, data]) => (
          <section key={label} style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden' }}>
            <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)' }}>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>{label}</h3>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 11 }}>
                  {['City', 'High', 'Range', 'Precip', 'Models'].map(h => (
                    <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontWeight: 500, borderBottom: '1px solid var(--border)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(data).map(([city, f]) => {
                  const spread = f.high_range[1] - f.high_range[0];
                  return (
                    <tr key={city} style={{ borderBottom: '1px solid var(--bg-muted)' }}>
                      <td style={{ padding: '10px 14px', fontWeight: 600 }}>{normCity(city)}</td>
                      <td style={{ padding: '10px 14px', fontFamily: 'ui-monospace, monospace' }}>{f.high_f.toFixed(1)}°F</td>
                      <td style={{ padding: '10px 14px', fontFamily: 'ui-monospace, monospace', color: spread <= 2 ? '#16a34a' : spread <= 5 ? '#ca8a04' : '#ef4444' }}>
                        {f.high_range[0].toFixed(0)}–{f.high_range[1].toFixed(0)}°
                      </td>
                      <td style={{ padding: '10px 14px', color: f.precip_in > 0.01 ? '#ca8a04' : 'var(--text-faint)', fontSize: 11 }}>
                        {f.precip_in > 0.01 ? f.precip_in.toFixed(2) + '"' : 'Dry'}
                      </td>
                      <td style={{ padding: '10px 14px', color: f.models_used >= 3 ? '#16a34a' : '#ca8a04', fontSize: 11 }}>{f.models_used}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        ))}
      </div>

      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px' }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>City calibration · Brier score</h3>
        <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
          Lower = better. Target ≤0.20 per city. Accumulates after 10+ settled trades.
        </p>
        {Object.entries(M.cityBrier || {}).sort((a, b) => Number(a[1]) - Number(b[1])).map(([city, brier]) => {
          const b = brier != null ? Number(brier) : null;
          const color = b == null ? '#8b949e' : b < 0.20 ? '#16a34a' : b < 0.30 ? '#ca8a04' : '#ef4444';
          const pct = b != null ? Math.max(0, Math.min(100, ((0.25 - b) / 0.25) * 100)) : 0;
          return (
            <div key={city} style={{ marginBottom: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                <span style={{ fontWeight: 600 }}>{normCity(city)}</span>
                <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, fontWeight: 700, color }}>
                  {b != null ? b.toFixed(3) : '—'}
                </span>
              </div>
              <div style={{ height: 6, background: 'var(--bg-muted)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: pct + '%', height: '100%', background: color }} />
              </div>
            </div>
          );
        })}
      </section>
    </main>
  );
}

// ---------------------------------------------------------------------------
// AnalyticsTab  — empty-state banner when post-wipe data is absent
// ---------------------------------------------------------------------------
function AnalyticsTab() {
  const M = useContext(DataContext);
  const isEmpty = M.stats.brier == null || M.stats.settled_count < 5;

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
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 14 }}>P&L by model source</h3>
          {(M.modelAccuracy || []).map((m) => {
            const pnl = m.edge_realized * 800;
            const base = (M.modelAccuracy || []).reduce((a, x) => a + x.edge_realized * 800, 0);
            const pct = base > 0 ? (pnl / base) * 100 : 0;
            return (
              <div key={m.model} style={{ marginBottom: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                  <span style={{ fontWeight: 600 }}>{m.model}</span>
                  <span style={{ color: '#16a34a', fontFamily: 'ui-monospace, monospace', fontSize: 12, fontWeight: 600 }}>+${pnl.toFixed(2)}</span>
                </div>
                <div style={{ position: 'relative', height: 18, background: 'var(--bg-muted)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ position: 'absolute', inset: 0, width: pct + '%', background: '#3b82f6' }} />
                  <span style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', fontSize: 11, color: 'var(--text)', fontFamily: 'ui-monospace, monospace', fontWeight: 600 }}>{pct.toFixed(0)}%</span>
                </div>
              </div>
            );
          })}
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
            return (
              <div key={day} style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                  <span style={{ fontWeight: 600 }}>{day} day{day !== '1' ? 's' : ''} out</span>
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

// ---------------------------------------------------------------------------
// RiskTab
// ---------------------------------------------------------------------------
function RiskTab() {
  const M = useContext(DataContext);
  const totalCost = M.positions.reduce((a, p) => a + p.cost, 0);
  const balance = M.stats.balance;
  const heatPct = balance > 0 ? ((totalCost / balance) * 100).toFixed(0) : 0;

  return (
    <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
      <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Risk</h1>
      <p style={{ margin: '0 0 24px', color: 'var(--text-muted)', fontSize: 13 }}>
        Portfolio exposure, aged positions, correlated events, directional bias, expiry clustering.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
        <StatCard label="Portfolio heat" tooltip="% of capital deployed. Bot halts new trades above 80%."
          value={heatPct + '%'}
          deltaTone={heatPct > 80 ? 'neg' : heatPct > 60 ? undefined : 'pos'}
          sub={heatPct > 80 ? 'Over limit — halting' : 'Within 80% limit'} />
        <StatCard label="Aged positions" tooltip="Positions held >36 h. Ties up capital; may signal a stuck trade."
          value={M.agedPositions.length} sub=">36h old" />
        <StatCard label="Correlated events" tooltip="Multiple positions on related markets (same city / same day)."
          value={M.correlatedEvents.length} sub="Same-day clusters" />
        <StatCard label="Daily spend" tooltip="Total cost deployed today vs limit."
          value={'$' + (M.stats.daily_spend || 0).toFixed(2)}
          sub={'limit $' + (M.stats.max_daily_spend || '—')} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 18, marginBottom: 18 }}>
        <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px' }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 14 }}>Directional bias</h3>
          <div style={{ textAlign: 'center', padding: '20px 0' }}>
            <div style={{ fontSize: 48, fontWeight: 700, color: '#3b82f6' }}>
              {M.directionalBias.yes} / {M.directionalBias.no}
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 8 }}>YES / NO positions</div>
          </div>
          <div style={{ padding: '10px 12px', borderRadius: 8, background: 'var(--bg-muted)', fontSize: 11, color: 'var(--text-muted)' }}>
            {((M.directionalBias.yes / (M.directionalBias.yes + M.directionalBias.no)) * 100).toFixed(0)}% bullish bias
          </div>
        </section>

        <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px' }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Expiry clustering</h3>
          <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
            ≥3 positions on same date = concentration risk.
          </p>
          {M.expiryCluster.map((exp) => (
            <div key={exp.date} style={{ marginBottom: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                <span style={{ fontWeight: 600 }}>{exp.date}</span>
                <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, color: exp.count >= 4 ? '#ef4444' : exp.count >= 3 ? '#ca8a04' : 'var(--text-muted)' }}>
                  {exp.count} pos · ${exp.total_cost.toFixed(2)}
                </span>
              </div>
              <div style={{ height: 6, background: 'var(--bg-muted)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: (exp.count / 4) * 100 + '%', height: '100%', background: exp.count >= 4 ? '#ef4444' : exp.count >= 3 ? '#ca8a04' : '#3b82f6' }} />
              </div>
            </div>
          ))}
        </section>
      </div>

      {/* Kill switch */}
      <section style={{ background: 'var(--bg-card)', border: '1px solid #ef4444', borderRadius: 14, padding: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: '#ef4444', marginBottom: 4 }}>Kill switch</h3>
            <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.4 }}>
              Emergency stop: halt all new orders. Cannot be undone without manual resume.
            </p>
          </div>
          <button
            onClick={() => { if (window.confirm('Engage kill switch?')) fetch('/api/halt', { method: 'POST', headers: authHeader() }); }}
            style={{ padding: '10px 20px', borderRadius: 8, border: 'none', background: '#ef4444', color: 'white', fontWeight: 600, fontSize: 13, cursor: 'pointer' }}>
            Engage kill switch
          </button>
        </div>
      </section>
    </main>
  );
}

// ---------------------------------------------------------------------------
// TradesTab  — early_exit badge, net_edge cap, real trade shape
// ---------------------------------------------------------------------------
function outcomeBadge(outcome) {
  if (outcome === 'yes')        return { bg: 'rgba(34,197,94,0.12)',  color: '#16a34a',        label: 'YES' };
  if (outcome === 'no')         return { bg: 'rgba(239,68,68,0.12)',  color: '#ef4444',        label: 'NO' };
  if (outcome === 'early_exit') return { bg: 'rgba(148,163,184,0.15)', color: '#64748b',       label: 'EARLY EXIT' };
  return                               { bg: 'rgba(148,163,184,0.10)', color: 'var(--text-faint)', label: outcome?.toUpperCase() || '—' };
}

function TradesTab() {
  const M = useContext(DataContext);
  const [page, setPage] = useState(0);
  const [cityFilter, setCityFilter] = useState('');
  const [sideFilter, setSideFilter] = useState('');
  const PAGE_SIZE = 10;

  const cities = useMemo(() => [...new Set(M.closedTrades.map(t => t.city))].sort(), [M.closedTrades]);

  const filtered = useMemo(() =>
    M.closedTrades.filter(t => (!cityFilter || t.city === cityFilter) && (!sideFilter || t.side === sideFilter)),
    [cityFilter, sideFilter, M.closedTrades]
  );

  const paginated = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const wins = M.closedTrades.filter(t => t.pnl > 0).length;
  const losses = M.closedTrades.filter(t => t.pnl != null && t.pnl < 0).length;

  return (
    <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 18 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em' }}>Trade History</h1>
          <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
            {filtered.length} settled · {wins} wins · {losses} losses
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <select value={cityFilter} onChange={e => { setCityFilter(e.target.value); setPage(0); }}
            style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 13, cursor: 'pointer', color: 'var(--text)' }}>
            <option value="">All cities</option>
            {cities.map(c => <option key={c} value={c}>{normCity(c)}</option>)}
          </select>
          <select value={sideFilter} onChange={e => { setSideFilter(e.target.value); setPage(0); }}
            style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 13, cursor: 'pointer', color: 'var(--text)' }}>
            <option value="">All sides</option>
            <option value="yes">YES</option>
            <option value="no">NO</option>
          </select>
        </div>
      </div>

      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden', marginBottom: 18 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 12 }}>
              {['Ticker', 'City', 'Side', 'Entry', 'Net Edge', 'Outcome', 'P&L', 'Entered'].map((h, i) => (
                <th key={h} style={{ padding: '12px 16px', textAlign: [3, 4, 6].includes(i) ? 'right' : 'left', fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paginated.map((t, i) => {
              const badge = outcomeBadge(t.outcome);
              // net_edge may be stored as ratio (real data) or absent (mock)
              const netEdgeDisplay = t.net_edge != null ? fmtEdge(t.net_edge) : '—';
              return (
                <tr key={i} style={{ borderBottom: '1px solid var(--bg-muted)' }}>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#3b82f6' }}>{t.ticker}</td>
                  <td style={{ padding: '14px 16px', fontWeight: 600 }}>{normCity(t.city)}</td>
                  <td style={{ padding: '14px 16px' }}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 999,
                      background: t.side === 'yes' ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
                      color: t.side === 'yes' ? '#16a34a' : '#ef4444',
                      fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                    }}>{t.side}</span>
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>
                    {t.entry_price != null ? (t.entry_price * 100).toFixed(0) + '¢' : '—'}
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)', fontSize: 12 }}>
                    {netEdgeDisplay}
                  </td>
                  <td style={{ padding: '14px 16px' }}>
                    <span style={{ display: 'inline-block', padding: '2px 8px', borderRadius: 999, background: badge.bg, color: badge.color, fontSize: 10, fontWeight: 600 }}>
                      {badge.label}
                    </span>
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', fontWeight: 700, color: t.pnl == null ? 'var(--text-faint)' : t.pnl >= 0 ? '#16a34a' : '#ef4444' }}>
                    {t.pnl == null ? '—' : (t.pnl >= 0 ? '+' : '') + '$' + t.pnl.toFixed(2)}
                  </td>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-faint)' }}>
                    {t.entered_at ? new Date(t.entered_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      {totalPages > 1 && (
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
          {Array.from({ length: totalPages }, (_, i) => (
            <button key={i} onClick={() => setPage(i)} style={{
              padding: '6px 12px', borderRadius: 7, border: '1px solid var(--border)',
              background: page === i ? '#3b82f6' : 'var(--bg-card)',
              color: page === i ? 'white' : 'var(--text)', fontWeight: 500, fontSize: 12, cursor: 'pointer',
            }}>{i + 1}</button>
          ))}
        </div>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// SettingsTab  — config display, override panel, A/B tests
// ---------------------------------------------------------------------------
function SettingsTab() {
  const M = useContext(DataContext);
  const s = M.stats;
  const [overrideReason, setOverrideReason] = useState('');
  const [overrideDuration, setOverrideDuration] = useState(60);
  const [overrideMsg, setOverrideMsg] = useState('');

  // Config params — all read from /api/config (M.config); stats fallback for max_daily_spend
  const configRows = [
    { key: 'strategy',          label: 'Sizing strategy',     value: M.config?.strategy || s.strategy || '—' },
    { key: 'env',               label: 'Environment',         value: M.config?.env       || s.env       || '—' },
    { key: 'max_daily_spend',   label: 'Max daily spend',     value: (M.config?.max_daily_spend ?? s.max_daily_spend) != null ? '$' + (M.config?.max_daily_spend ?? s.max_daily_spend) : '—' },
    { key: 'min_edge',          label: 'Min edge threshold',  value: M.config?.min_edge != null ? (M.config.min_edge * 100).toFixed(1) + '%' : '—' },
    { key: 'strong_edge',       label: 'Strong edge',         value: M.config?.strong_edge != null ? (M.config.strong_edge * 100).toFixed(1) + '%' : '—' },
    { key: 'drawdown_halt_pct', label: 'Drawdown halt %',     value: M.config?.drawdown_halt_pct != null ? M.config.drawdown_halt_pct + '%' : '—' },
    { key: 'max_days_out',      label: 'Max days out',        value: M.config?.max_days_out != null ? M.config.max_days_out + ' days' : '—' },
  ];

  function handleSetOverride() {
    if (!overrideReason.trim()) { setOverrideMsg('Reason required.'); return; }
    fetch('/api/override', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader() },
      body: JSON.stringify({ reason: overrideReason.trim(), duration_minutes: overrideDuration }),
    })
      .then(r => r.json())
      .then(d => {
        setOverrideMsg(d.error ? `✗ ${d.error}` : `✓ Override set for ${overrideDuration} min`);
        setOverrideReason('');
        setTimeout(() => setOverrideMsg(''), 4000);
      })
      .catch(() => { setOverrideMsg('✗ Request failed'); setTimeout(() => setOverrideMsg(''), 3000); });
  }

  function handleClearOverride() {
    fetch('/api/override', {
      method: 'DELETE',
      headers: authHeader(),
    })
      .then(r => r.json())
      .then(d => {
        setOverrideMsg(d.error ? `✗ ${d.error}` : '✓ Override cleared');
        setTimeout(() => setOverrideMsg(''), 3000);
      })
      .catch(() => { setOverrideMsg('✗ Request failed'); setTimeout(() => setOverrideMsg(''), 3000); });
  }

  return (
    <main style={{ maxWidth: 1000, margin: '0 auto', padding: '24px 28px 40px' }}>
      <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Settings</h1>
      <p style={{ margin: '0 0 24px', color: 'var(--text-muted)', fontSize: 13 }}>
        Bot configuration, manual overrides, and A/B test status.
      </p>

      {/* Config */}
      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden', marginBottom: 18 }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Bot configuration</h3>
          <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>Live values from /api/config</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 }}>
          {configRows.map((row, i) => (
            <div key={row.key} style={{
              padding: '14px 20px', borderBottom: '1px solid var(--bg-muted)',
              borderRight: i % 2 === 0 ? '1px solid var(--bg-muted)' : 'none',
            }}>
              <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 4 }}>{row.label}</div>
              <div style={{ fontWeight: 600, fontFamily: 'ui-monospace, monospace', fontSize: 14 }}>{row.value}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Manual override */}
      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Manual override</h3>
        <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 16, lineHeight: 1.4 }}>
          Override the bot's trading gate for a fixed window. Use when you want to force-allow trades despite a drawdown halt or cooldown. Requires a reason for the audit log.
        </p>

        {s.override_until && (
          <div style={{ padding: '10px 14px', borderRadius: 8, background: 'rgba(234,179,8,0.08)', border: '1px solid rgba(234,179,8,0.3)', color: '#92400e', fontSize: 12, marginBottom: 14 }}>
            ⚠ Override active until {new Date(s.override_until).toLocaleTimeString()}
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 10, alignItems: 'end' }}>
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>Reason</label>
            <input value={overrideReason} onChange={e => setOverrideReason(e.target.value)}
              placeholder="e.g. Testing new edge threshold manually"
              style={{ width: '100%', padding: '9px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-subtle)', fontSize: 13, color: 'var(--text)', outline: 'none', boxSizing: 'border-box' }} />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>Duration (min)</label>
            <input type="number" min="5" max="480" value={overrideDuration} onChange={e => setOverrideDuration(+e.target.value)}
              style={{ width: 90, padding: '9px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-subtle)', fontSize: 13, color: 'var(--text)', outline: 'none' }} />
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={handleSetOverride} style={{ padding: '9px 18px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontWeight: 600, fontSize: 13, cursor: 'pointer' }}>Set override</button>
            <button onClick={handleClearOverride} style={{ padding: '9px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13, cursor: 'pointer' }}>Clear</button>
          </div>
        </div>
        {overrideMsg && <div style={{ marginTop: 10, fontSize: 12, color: '#16a34a' }}>{overrideMsg}</div>}
      </section>

      {/* A/B tests */}
      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>A/B tests</h3>
        <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
          Active experiments. Variant is assigned per-trade at entry time.
        </p>
        {M.abTests && M.abTests.length > 0 ? (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 12 }}>
                {['Test', 'Variant', 'Trades', 'Edge (realized)'].map(h => (
                  <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {M.abTests.map((t, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--bg-muted)' }}>
                  <td style={{ padding: '12px 14px', fontWeight: 600 }}>{t.name}</td>
                  <td style={{ padding: '12px 14px', fontFamily: 'ui-monospace, monospace' }}>{t.variant}</td>
                  <td style={{ padding: '12px 14px', fontFamily: 'ui-monospace, monospace' }}>{t.trades ?? 0}</td>
                  <td style={{ padding: '12px 14px', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)' }}>
                    {t.edge_realized != null ? (t.edge_realized * 100).toFixed(1) + '%' : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-faint)', fontSize: 13 }}>
            No A/B tests active
          </div>
        )}
      </section>

      {/* Kill switch */}
      <section style={{ background: 'var(--bg-card)', border: '1px solid #ef4444', borderRadius: 14, padding: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: '#ef4444', marginBottom: 4 }}>Kill switch</h3>
            <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: 12 }}>
              Halt all new orders immediately. Use the resume button or restart the bot to re-enable.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button onClick={() => { if (window.confirm('Engage kill switch?')) fetch('/api/halt', { method: 'POST', headers: authHeader() }); }}
              style={{ padding: '10px 20px', borderRadius: 8, border: 'none', background: '#ef4444', color: 'white', fontWeight: 600, fontSize: 13, cursor: 'pointer' }}>
              Halt
            </button>
            <button onClick={() => { if (window.confirm('Resume trading?')) fetch('/api/resume', { method: 'POST', headers: authHeader() }); }}
              style={{ padding: '10px 20px', borderRadius: 8, border: '1px solid #16a34a', background: 'transparent', color: '#16a34a', fontWeight: 600, fontSize: 13, cursor: 'pointer' }}>
              Resume
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}

// ---------------------------------------------------------------------------
// App  — DataContext provider, theme, tab routing
// Task 3 will replace `const data = MOCK` with `const data = useData()`
// ---------------------------------------------------------------------------
const TABS = {
  Overview: OverviewTab,
  Positions: PositionsTab,
  Signals: SignalsTab,
  Forecast: ForecastTab,
  Analytics: AnalyticsTab,
  Risk: RiskTab,
  Trades: TradesTab,
  Settings: SettingsTab,
};

export default function App() {
  const [activeTab, setActiveTab] = useState('Overview');
  const [theme, setTheme] = useState(() => localStorage.getItem('kalshi-theme') || 'light');
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    applyTheme(theme);
    localStorage.setItem('kalshi-theme', theme);
  }, [theme]);

  const data = useData(setConnected);

  const TabComponent = TABS[activeTab] || OverviewTab;

  return (
    <DataContext.Provider value={data}>
      <div style={{
        background: 'var(--bg-page)', color: 'var(--text)',
        fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        fontSize: 14, minHeight: '100vh',
      }}>
        <Nav
          active={activeTab}
          onNavigate={setActiveTab}
          theme={theme}
          onToggleTheme={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
          connected={connected}
        />
        <ErrorBoundary key={activeTab}>
          <TabComponent />
        </ErrorBoundary>
      </div>
    </DataContext.Provider>
  );
}
