import React, {
  useState, useMemo, useEffect, useRef, useContext, Component,
} from 'react';
import useData, { authHeader } from './useData.js';

// DataContext lives in its own file so tabs can import it without importing
// all of App.jsx. We re-export it here for any code that imports from App.jsx.
export { DataContext } from './DataContext.js';
import { DataContext } from './DataContext.js';

// Tab components — each in its own file under src/tabs/
import OverviewTab  from './tabs/OverviewTab.jsx';
import PositionsTab from './tabs/PositionsTab.jsx';
import SignalsTab   from './tabs/SignalsTab.jsx';
import ForecastTab  from './tabs/ForecastTab.jsx';
import AnalyticsTab from './tabs/AnalyticsTab.jsx';
import ActivityTab  from './tabs/ActivityTab.jsx';
import RiskTab      from './tabs/RiskTab.jsx';
import TradesTab    from './tabs/TradesTab.jsx';
import SettingsTab  from './tabs/SettingsTab.jsx';

// Shared helpers used directly in App (Nav uses normCity / authHeader)
import { normCity } from './shared.jsx';

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
// Nav
// ---------------------------------------------------------------------------
function Nav({ active, onNavigate, theme, onToggleTheme, connected, refreshCountdown }) {
  const TAB_NAMES = ['Overview', 'Positions', 'Signals', 'Forecast', 'Analytics', 'Activity', 'Risk', 'Trades', 'Settings'];
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
          {TAB_NAMES.map((tab, i) => (
            <button key={tab} onClick={() => onNavigate(tab)} style={{
              padding: '7px 13px', borderRadius: 7, border: 'none',
              color: active === tab ? 'var(--text)' : 'var(--text-muted)',
              background: active === tab ? 'var(--bg-muted)' : 'transparent',
              fontWeight: active === tab ? 600 : 500, cursor: 'pointer', fontFamily: 'inherit',
              display: 'inline-flex', alignItems: 'center', gap: 4,
            }}>
              {tab}
              {i < 8 && (
                <kbd style={{ fontSize: 9, opacity: 0.5, fontFamily: 'ui-monospace, monospace', lineHeight: 1 }}>{i + 1}</kbd>
              )}
            </button>
          ))}
        </nav>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {/* Auto-refresh countdown — clicking triggers an immediate data refresh */}
        {refreshCountdown != null && (
          <button
            onClick={() => M?.refresh?.()}
            title="Click to refresh data now"
            style={{ fontSize: 11, color: 'var(--text-faint)', fontFamily: 'ui-monospace, monospace', background: 'none', border: 'none', cursor: 'pointer', padding: '4px 6px', borderRadius: 5 }}
          >
            ↻ {refreshCountdown}s
          </button>
        )}
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
    const tabs = ['Overview', 'Positions', 'Signals', 'Forecast', 'Analytics', 'Activity', 'Risk', 'Trades', 'Settings'].map(t => ({
      type: 'tab', label: t, action: () => onNavigate(t),
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
// Tab registry — maps tab name to component
// ---------------------------------------------------------------------------
const TABS = {
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

const VALID_TABS = Object.keys(TABS);

// ---------------------------------------------------------------------------
// App — DataContext provider, theme, tab routing
// ---------------------------------------------------------------------------
export default function App() {
  // Initialize active tab from URL hash so deep links work
  const [activeTab, setActiveTab] = useState(() => {
    const hash = window.location.hash.slice(1);
    return VALID_TABS.includes(hash) ? hash : 'Overview';
  });
  const [theme, setTheme] = useState(() => localStorage.getItem('kalshi-theme') || 'light');
  const [connected, setConnected] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [cronState, setCronState] = useState({ status: 'idle', log: [], exitCode: null });
  const [toasts, setToasts] = useState([]);
  const [refreshCountdown, setRefreshCountdown] = useState(60);
  const cronPollRef = useRef(null);
  const countdownRef = useRef(null);

  useEffect(() => {
    applyTheme(theme);
    localStorage.setItem('kalshi-theme', theme);
  }, [theme]);

  function addToast(message, type = 'success', duration = 4000) {
    const id = Date.now();
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), duration);
  }

  const data = useData(setConnected);

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
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => {
    if (cronPollRef.current) clearInterval(cronPollRef.current);
    if (countdownRef.current) clearInterval(countdownRef.current);
  }, []);

  // Auto-refresh countdown resets to 60 each time data arrives
  useEffect(() => {
    setRefreshCountdown(60);
    if (countdownRef.current) clearInterval(countdownRef.current);
    countdownRef.current = setInterval(() => {
      setRefreshCountdown(prev => prev <= 1 ? 60 : prev - 1);
    }, 1000);
    return () => clearInterval(countdownRef.current);
  }, [data.stats?.timestamp]);

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
      if (!e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) {
        const tabs = ['Overview', 'Positions', 'Signals', 'Forecast', 'Analytics', 'Activity', 'Risk', 'Trades'];
        const num = parseInt(e.key, 10);
        if (num >= 1 && num <= tabs.length) setActiveTab(tabs[num - 1]);
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  function startCronPoll() {
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
  }

  function handleRunCron() {
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
  }

  function handleCancelCron() {
    fetch('/api/cancel-cron', { method: 'POST', headers: authHeader() })
      .then(() => {
        if (cronPollRef.current) { clearInterval(cronPollRef.current); cronPollRef.current = null; }
        setCronState(prev => ({ ...prev, status: 'cancelled', log: [...prev.log, '— cancelled by user —'] }));
      })
      .catch(() => {});
  }

  const TabComponent = TABS[activeTab] || OverviewTab;

  return (
    <DataContext.Provider value={{ ...data, cronState, handleRunCron, handleCancelCron }}>
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
          refreshCountdown={refreshCountdown}
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
          <TabComponent />
        </ErrorBoundary>
      </div>
    </DataContext.Provider>
  );
}
