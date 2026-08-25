import React, {
  useState, useMemo, useEffect, useRef, useContext, useCallback, Component, Suspense, lazy,
} from 'react';
import useData, { authHeader } from './useData.js';

// DataContext lives in its own file so tabs can import it without importing
// all of App.jsx. We re-export it here for any code that imports from App.jsx.
export { DataContext } from './DataContext.js';
import { DataContext } from './DataContext.js';

// React caches a rejected lazy() import forever and never retries it on its
// own (verified against React 18's lazyInitializer: it only re-invokes the
// ctor while _status === Uninitialized, and a rejection sets _status =
// Rejected permanently) -- opus review: this dashboard is meant to stay open
// for hours (that's the whole premise of item 1's polling fix), and a fresh
// deploy in the meantime deletes the previous build's hashed chunk files
// (vite.config.js's emptyOutDir). Without this, an operator who has the tab
// open across a deploy gets a permanently unrecoverable "Tab crashed" the
// first time they click a not-yet-visited tab, with no fix short of a full
// page reload. One retry (a short delay, catching a genuine transient
// network blip) before falling back to reload() (recovers the stale-chunk-
// hash case, which a same-URL retry can never fix on its own).
function lazyRetry(importer) {
  return lazy(() =>
    importer().catch(() =>
      new Promise((resolve) => setTimeout(resolve, 300)).then(() =>
        importer().catch(() => {
          window.location.reload();
          return new Promise(() => {}); // navigation is already underway
        })
      )
    )
  );
}

// Tab components — each in its own file under src/tabs/, lazy-loaded so
// visiting the dashboard and landing on Overview doesn't pay the bundle cost
// of all nine tabs up front (batch-47 item 4 — AnalyticsTab alone is 67 KB).
// Suspense's fallback (below, wherever <TabComponent /> renders) covers the
// one-time per-session fetch of whichever tab is opened first.
const OverviewTab  = lazyRetry(() => import('./tabs/OverviewTab.jsx'));
const PositionsTab = lazyRetry(() => import('./tabs/PositionsTab.jsx'));
const SignalsTab   = lazyRetry(() => import('./tabs/SignalsTab.jsx'));
const ForecastTab  = lazyRetry(() => import('./tabs/ForecastTab.jsx'));
const AnalyticsTab = lazyRetry(() => import('./tabs/AnalyticsTab.jsx'));
const ActivityTab  = lazyRetry(() => import('./tabs/ActivityTab.jsx'));
const RiskTab      = lazyRetry(() => import('./tabs/RiskTab.jsx'));
const TradesTab    = lazyRetry(() => import('./tabs/TradesTab.jsx'));
const SettingsTab  = lazyRetry(() => import('./tabs/SettingsTab.jsx'));

// Shared helpers used directly in App (CommandPalette uses normCity; Nav's
// kill switch and its DataContext-provided addToast/refresh use haltOrResume;
// TableSkeleton is the Suspense fallback for lazy-loaded tabs)
import { normCity, haltOrResume, TAB_LIST, tabForHotkey, TableSkeleton } from './shared.jsx';

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

// ---------------------------------------------------------------------------
// Toast — lightweight ephemeral notification system
// ---------------------------------------------------------------------------
function ToastContainer({ toasts }) {
  if (!toasts.length) return null;
  return (
    <div style={{
      position: 'fixed', bottom: 24, right: 24, zIndex: 1000,
      display: 'flex', flexDirection: 'column', gap: 8, pointerEvents: 'none',
    }}>
      {toasts.map(t => (
        <div key={t.id} style={{
          padding: '11px 18px', borderRadius: 10, fontSize: 13, fontWeight: 600,
          boxShadow: '0 4px 16px rgba(0,0,0,0.25)',
          background: t.type === 'error' ? '#ef4444' : t.type === 'warn' ? '#f59e0b' : '#16a34a',
          color: 'white', maxWidth: 340, lineHeight: 1.4,
        }}>{t.message}</div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------
const THEMES = {
  light: {
    '--bg-page': '#fafafa', '--bg-card': '#ffffff', '--bg-subtle': '#f8f9fb',
    '--bg-muted': '#f1f5f9', '--border': '#e7eaef',
    '--text': '#0f172a', '--text-muted': '#64748b', '--text-faint': '#94a3b8',
    // Semantic colours (batch-46 M-2): promoted out of hardcoded hex so
    // badges/fills/chart accents track theme instead of staying light-only.
    '--pos': '#16a34a', '--pos-fill': 'rgba(34,197,94,0.12)',
    '--neg': '#dc2626', '--neg-fill': 'rgba(239,68,68,0.12)',
    '--warn': '#92400e', '--warn-fill': 'rgba(234,179,8,0.12)',
    '--accent': '#2563eb', '--accent-fill': 'rgba(59,130,246,0.12)',
  },
  dark: {
    '--bg-page': '#0f1115', '--bg-card': '#181b22', '--bg-subtle': '#1e222a',
    '--bg-muted': '#2a2f3a', '--border': '#2e333d',
    '--text': '#eef0f5', '--text-muted': '#a3acb8', '--text-faint': '#737d8a',
    // --warn in particular can't reuse light's #92400e (near-black brown,
    // invisible on a dark card) -- each semantic colour needs its own
    // brighter dark-mode value tuned for contrast against --bg-card.
    '--pos': '#4ade80', '--pos-fill': 'rgba(74,222,128,0.16)',
    '--neg': '#f87171', '--neg-fill': 'rgba(248,113,113,0.16)',
    '--warn': '#fbbf24', '--warn-fill': 'rgba(251,191,36,0.16)',
    '--accent': '#60a5fa', '--accent-fill': 'rgba(96,165,250,0.16)',
  },
};
function applyTheme(t) {
  Object.entries(THEMES[t]).forEach(([k, v]) => document.documentElement.style.setProperty(k, v));
  // opus review LOW (batch-48 item 7 follow-up): index.html's pre-mount
  // script sets these same three direct style properties (not just the CSS
  // custom properties) so nothing paints unthemed before React mounts --
  // but that script only runs once, at load. Without mirroring it here, a
  // manual theme-toggle click after mount left backgroundColor/color/
  // colorScheme pinned at the LOAD-time theme forever, most visibly in
  // native form chrome (a <select>'s dropdown panel, scrollbars) that keeps
  // rendering the old scheme after the operator switches.
  document.documentElement.style.backgroundColor = THEMES[t]['--bg-page'];
  document.documentElement.style.color = THEMES[t]['--text'];
  document.documentElement.style.colorScheme = t;
}

// ---------------------------------------------------------------------------
// RefreshCountdown — owns its own 1s ticker and local state so it's the only
// thing that re-renders every second; everything else reads DataContext and
// only re-renders when the data it actually depends on changes (batch-43 H-2:
// this used to live in App's own state, forcing every context consumer —
// including the 67 KB AnalyticsTab chart computation — to re-render once a
// second just to animate this label).
// ---------------------------------------------------------------------------
function RefreshCountdown() {
  const M = useContext(DataContext);
  const [countdown, setCountdown] = useState(60);
  const intervalRef = useRef(null);

  // Reset to 60 and restart the ticker each time fresh data actually arrives
  useEffect(() => {
    setCountdown(60);
    if (intervalRef.current) clearInterval(intervalRef.current);
    intervalRef.current = setInterval(() => {
      setCountdown(prev => (prev <= 1 ? 60 : prev - 1));
    }, 1000);
    return () => clearInterval(intervalRef.current);
  }, [M.stats?.timestamp]);

  return (
    <button
      onClick={() => M?.refresh?.()}
      title="Click to refresh data now"
      style={{ fontSize: 11, color: 'var(--text-faint)', fontFamily: 'ui-monospace, monospace', background: 'none', border: 'none', cursor: 'pointer', padding: '4px 6px', borderRadius: 5 }}
    >
      ↻ {countdown}s
    </button>
  );
}

// ---------------------------------------------------------------------------
// Nav
// ---------------------------------------------------------------------------
function Nav({ active, onNavigate, theme, onToggleTheme, connected }) {
  const M = useContext(DataContext);
  const ks = M?.stats?.kill_switch;

  // Calculate badge counts for tabs that need attention indicators
  const badges = useMemo(() => {
    const agedPos = M.positions?.filter(p => p.age_h >= 24).length || 0;
    const overduePos = M.positions?.filter(p => p.expiry && p.expiry < new Date().toISOString().slice(0, 10)).length || 0;
    const opportunities = M.opportunities?.filter(o => o.edge_pct >= 10).length || 0;

    return {
      Positions: agedPos + overduePos > 0 ? { count: agedPos + overduePos, tone: 'amber' } : null,
      Signals: opportunities > 0 ? { count: opportunities, tone: 'blue' } : null,
      Risk: ks ? { icon: '!', tone: 'red' } : null,
    };
  }, [M.positions, M.opportunities, ks]);

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
          {TAB_LIST.map((tab) => (
            <button key={tab.id} onClick={() => onNavigate(tab.id)} style={{
              padding: '7px 13px', borderRadius: 7, border: 'none',
              color: active === tab.id ? 'var(--text)' : 'var(--text-muted)',
              background: active === tab.id ? 'var(--bg-muted)' : 'transparent',
              fontWeight: active === tab.id ? 600 : 500, cursor: 'pointer', fontFamily: 'inherit',
              display: 'inline-flex', alignItems: 'center', gap: 4,
            }}>
              {tab.id}
              {tab.hotkey && (
                <kbd style={{ fontSize: 9, opacity: 0.5, fontFamily: 'ui-monospace, monospace', lineHeight: 1 }}>{tab.hotkey}</kbd>
              )}
            </button>
          ))}
        </nav>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {/* Auto-refresh countdown — clicking triggers an immediate data refresh */}
        <RefreshCountdown />
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

        {/* Env badge — reads kalshi_env/is_live from /api/status */}
        <span style={{
          display: 'inline-flex', alignItems: 'center',
          padding: '4px 10px', borderRadius: 999,
          background: M.stats?.is_live ? 'rgba(239,68,68,0.12)' : 'rgba(34,197,94,0.12)',
          color: M.stats?.is_live ? '#ef4444' : '#16a34a',
          fontSize: 11, fontWeight: 600,
        }}>
          {M.stats?.is_live ? '● LIVE' : '◌ PAPER'}
        </span>
        {/* H4: EMOS not-trained quick-glance indicator */}
        {M.emosStatus && !M.emosStatus.trained && (
          <span style={{
            fontSize: 10, padding: '1px 5px', borderRadius: 3, fontWeight: 500,
            background: 'rgba(107,114,128,0.2)', color: 'var(--text-muted)',
          }} title="EMOS not trained — run py main.py emos-train">
            EMOS ✗
          </span>
        )}

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
          onClick={() => {
            if (!window.confirm('Engage kill switch? This halts all trading.')) return;
            haltOrResume('halt', { refresh: M.refresh, addToast: M.addToast });
          }}
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
// CommandPalette — Cmd+K search over tabs, positions, and signals
// ---------------------------------------------------------------------------
function CommandPalette({ onClose, onNavigate, positions, signals }) {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const allItems = useMemo(() => {
    const tabs = TAB_LIST.map(t => ({
      type: 'tab', label: t.id, action: () => onNavigate(t.id),
    }));
    const posItems = positions.slice(0, 5).map(p => ({
      type: 'position', label: `${p.ticker} · ${normCity(p.city)}`, sub: `${p.side.toUpperCase()} · ${(p.edge * 100).toFixed(1)}% edge`,
      action: () => { onNavigate('Positions'); onClose(); },
    }));
    const sigItems = signals.slice(0, 5).map(s => ({
      type: 'signal', label: `${s.ticker} · ${normCity(s.city)}`, sub: `${(s.edge_pct || 0).toFixed(1)}% edge`,
      action: () => { onNavigate('Signals'); onClose(); },
    }));
    return [...tabs, ...posItems, ...sigItems];
  }, [positions, signals, onNavigate, onClose]);

  const filtered = useMemo(() => {
    if (!query) return allItems;
    const q = query.toLowerCase();
    return allItems.filter(item => item.label.toLowerCase().includes(q) || item.sub?.toLowerCase().includes(q));
  }, [allItems, query]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex(i => Math.min(i + 1, filtered.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex(i => Math.max(i - 1, 0));
      } else if (e.key === 'Enter' && filtered[selectedIndex]) {
        e.preventDefault();
        filtered[selectedIndex].action();
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [filtered, selectedIndex]);

  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(15, 23, 42, 0.5)', zIndex: 2000,
      display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: 120,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 600, background: 'var(--bg-card)', borderRadius: 12, boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
        border: '1px solid var(--border)', overflow: 'hidden',
      }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)' }}>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search tabs, positions, signals..."
            style={{
              width: '100%', padding: '10px 0', border: 'none', outline: 'none',
              background: 'transparent', fontSize: 16, color: 'var(--text)', fontFamily: 'inherit',
            }}
          />
        </div>
        <div style={{ maxHeight: 400, overflowY: 'auto' }}>
          {filtered.map((item, i) => (
            <div
              key={i}
              onClick={item.action}
              style={{
                padding: '12px 20px', cursor: 'pointer',
                background: i === selectedIndex ? 'var(--bg-subtle)' : 'transparent',
                borderLeft: i === selectedIndex ? '3px solid #3b82f6' : '3px solid transparent',
              }}
            >
              <div style={{ fontSize: 14, fontWeight: 600 }}>{item.label}</div>
              {item.sub && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{item.sub}</div>}
            </div>
          ))}
          {filtered.length === 0 && (
            <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              No results found
            </div>
          )}
        </div>
        <div style={{ padding: '10px 20px', borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--text-faint)', display: 'flex', gap: 16 }}>
          <span>↑↓ Navigate</span>
          <span>↵ Select</span>
          <span>Esc Close</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab registry — maps each TAB_LIST id (shared.jsx) to its component. Kept
// separate from TAB_LIST itself so that shared, testable list has no
// component references (see shared.jsx's batch-47 item 3 comment).
// ---------------------------------------------------------------------------
const TAB_COMPONENTS = {
  Overview:  OverviewTab,
  Positions: PositionsTab,
  Signals:   SignalsTab,
  Forecast:  ForecastTab,
  Analytics: AnalyticsTab,
  Activity:  ActivityTab,
  Risk:      RiskTab,
  Trades:    TradesTab,
  Settings:  SettingsTab,
};

// opus review: TAB_LIST (shared.jsx) and TAB_COMPONENTS above are two
// independent literals that must stay in sync by id — exactly the kind of
// drift item 3 exists to eliminate. Without this check, an id present in
// one but not the other resolves to `undefined`, and `TABS[activeTab] ||
// OverviewTab` below would silently reroute that tab's name (including its
// URL hash) to Overview instead of failing loudly. Both literals are static
// and colocated in this same file, so this throws at module load — the
// first time anyone runs or builds the app — never as a live production
// surprise.
TAB_LIST.forEach(t => {
  if (!TAB_COMPONENTS[t.id]) throw new Error(`TAB_LIST entry "${t.id}" has no matching TAB_COMPONENTS entry`);
});

const TABS = Object.fromEntries(TAB_LIST.map(t => [t.id, TAB_COMPONENTS[t.id]]));
const VALID_TABS = TAB_LIST.map(t => t.id);

// ---------------------------------------------------------------------------
// App — DataContext provider, theme, tab routing
// ---------------------------------------------------------------------------
export default function App() {
  // Initialize active tab from URL hash so deep links work
  const [activeTab, setActiveTab] = useState(() => {
    const hash = window.location.hash.slice(1);
    return VALID_TABS.includes(hash) ? hash : 'Overview';
  });
  // batch-48 item 7: mirrors index.html's inline pre-mount script's fallback
  // (stored preference, else prefers-color-scheme) so this state never
  // disagrees with the CSS vars that script already applied before mount --
  // an initial 'light' default here would fight a dark-mode OS user's synced
  // vars the instant this component's own theme useEffect below runs.
  const [theme, setTheme] = useState(() => {
    const stored = localStorage.getItem('kalshi-theme');
    if (stored) return stored;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  });
  const [connected, setConnected] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [cronState, setCronState] = useState({ status: 'idle', log: [], exitCode: null });
  const [toasts, setToasts] = useState([]);
  const cronPollRef = useRef(null);

  useEffect(() => {
    applyTheme(theme);
    localStorage.setItem('kalshi-theme', theme);
  }, [theme]);

  // batch-48 item 6: Date.now() gave two toasts fired within the same
  // millisecond the same id, so the first one's removal timeout matched
  // (and removed) both. A monotonic ref counter can't collide regardless of
  // firing rate.
  const toastIdRef = useRef(0);
  const addToast = useCallback((message, type = 'success', duration = 4000) => {
    const id = ++toastIdRef.current;
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), duration);
  }, []);

  const data = useData(setConnected);

  // batch-47 item 1 deliberately does NOT visibility-gate this poll (unlike
  // useData.js's three gated loops): it only runs while a scan the operator
  // just triggered is actively executing (bounded, not indefinite background
  // waste), and its completion fires a Notification API call specifically so
  // the operator is alerted even after switching away from the tab — gating
  // it would delay that notification until they return, defeating its
  // purpose. Confirmed with the user (2026-08-24).
  const startCronPoll = useCallback(() => {
    if (cronPollRef.current) clearInterval(cronPollRef.current);
    cronPollRef.current = setInterval(() => {
      fetch('/api/cron-status', { headers: authHeader() })
        .then(r => r.ok ? r.json() : null)
        .then(d => {
          if (!d) return;
          const status = d.running ? 'running' : (d.exit_code === 0 ? 'done' : 'error');
          setCronState({ status, log: d.log || [], exitCode: d.exit_code });
          if (!d.running) {
            clearInterval(cronPollRef.current);
            cronPollRef.current = null;
            data.refresh();
            const msg = d.exit_code === 0 ? 'Cron scan complete — signals updated.' : 'Cron scan finished with errors.';
            addToast(msg, d.exit_code === 0 ? 'success' : 'error');
            if ('Notification' in window && Notification.permission === 'granted') {
              new Notification('Kalshi scan complete', { body: msg, icon: '/favicon.ico' });
            }
          }
        })
        .catch(() => {});
    }, 3000);
  }, [data.refresh, addToast]);

  const handleRunCron = useCallback(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
    setCronState({ status: 'running', log: ['Starting scan…'], exitCode: null });
    fetch('/api/run_cron', { method: 'POST', headers: authHeader() })
      .then(r => r.json())
      .then(d => {
        if (d.error) {
          setCronState({ status: 'error', log: [d.error], exitCode: 1 });
        } else {
          startCronPoll();
        }
      })
      .catch(() => setCronState({ status: 'error', log: ['Request failed — is the server running?'], exitCode: 1 }));
  }, [startCronPoll]);

  const handleCancelCron = useCallback(() => {
    fetch('/api/cancel-cron', { method: 'POST', headers: authHeader() })
      .then(() => {
        if (cronPollRef.current) { clearInterval(cronPollRef.current); cronPollRef.current = null; }
        setCronState(prev => ({ ...prev, status: 'cancelled', log: [...prev.log, '— cancelled by user —'] }));
      })
      .catch(() => {});
  }, []);

  // Check if a cron is already running on mount (e.g. started before page load)
  useEffect(() => {
    fetch('/api/cron-status', { headers: authHeader() })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.running) {
          setCronState({ status: 'running', log: d.log || [], exitCode: null });
          startCronPoll();
        }
      })
      .catch(() => {});
  }, [startCronPoll]);

  useEffect(() => () => {
    if (cronPollRef.current) clearInterval(cronPollRef.current);
  }, []);

  // Sync URL hash to active tab so back/forward work
  useEffect(() => {
    window.location.hash = activeTab;
  }, [activeTab]);

  // Listen for hash changes (browser back/forward)
  useEffect(() => {
    function handleHashChange() {
      const hash = window.location.hash.slice(1);
      if (VALID_TABS.includes(hash)) setActiveTab(hash);
    }
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  // Global keyboard shortcuts: Esc, Cmd+K, digit keys 1-8
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape') {
        setCommandPaletteOpen(false);
        document.dispatchEvent(new CustomEvent('kalshi:escape'));
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCommandPaletteOpen(true);
      }
      // Only the bare-digit tab-navigation shortcut needs to back off of a
      // field the operator is actively typing into (order qty, close-price,
      // alert threshold, override duration, log search, ...) -- Escape and
      // Cmd+K above stay live everywhere (including the command palette's
      // own autoFocused search input, which has no other Escape handler of
      // its own -- opus review batch-42 H-3: an earlier version of this
      // guard sat above both those branches and silently broke the
      // palette's own "Esc Close" hint).
      const t = e.target;
      const tag = t?.tagName;
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || t?.isContentEditable) return;
      if (!e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) {
        const tabId = tabForHotkey(e.key);
        if (tabId) setActiveTab(tabId);
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  const TabComponent = TABS[activeTab] || OverviewTab;

  // Memoized so a re-render that doesn't touch data/cronState/the handlers
  // (e.g. a theme or tab change) hands consumers back the same value
  // reference instead of a brand-new object literal every time (batch-43
  // H-2, part 2 of 2). `data` and the handlers are now stable references
  // themselves (useData.js memoizes its return value; the handlers above
  // are useCallback-wrapped), so this actually holds across such renders.
  const contextValue = useMemo(
    () => ({ ...data, cronState, handleRunCron, handleCancelCron, addToast }),
    [data, cronState, handleRunCron, handleCancelCron, addToast]
  );

  return (
    <DataContext.Provider value={contextValue}>
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
        <ToastContainer toasts={toasts} />
        {commandPaletteOpen && (
          <CommandPalette
            onClose={() => setCommandPaletteOpen(false)}
            onNavigate={(tab) => { setActiveTab(tab); setCommandPaletteOpen(false); }}
            positions={data.positions}
            signals={data.opportunities}
          />
        )}
        <ErrorBoundary key={activeTab}>
          <Suspense fallback={
            // opus review: every tab's own root <main> uses this exact
            // margin/padding (maxWidth varies 1000-1360 across tabs; 1360 is
            // the majority) -- without matching it here, the skeleton sat
            // flush against Nav and ~28px wider on each side than the real
            // content that replaces it, visibly snapping into place on load.
            <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
              <TableSkeleton />
            </main>
          }>
            <TabComponent />
          </Suspense>
        </ErrorBoundary>
      </div>
    </DataContext.Provider>
  );
}
