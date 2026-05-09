// Full multi-tab operator dashboard prototype — COMPREHENSIVE
// All data from reference files: dashboard.js, signals.js, analytics.js, risk.js, forecast.js, trades.js

const FullProto = (function () {
  const M = window.MOCK;
  const { useState, useMemo, useEffect, useRef } = React;

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

  function applyTheme(theme) {
    const vars = THEMES[theme];
    Object.keys(vars).forEach(k => document.documentElement.style.setProperty(k, vars[k]));
  }

  // -- Shared components --

  function Nav({ active, onNavigate, theme, onToggleTheme }) {
    const tabs = ['Overview', 'Positions', 'Signals', 'Forecast', 'Analytics', 'Risk', 'Trades'];
    return (
      <header style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '16px 28px', borderBottom: '1px solid var(--border)',
        background: 'var(--bg-card)', position: 'sticky', top: 0, zIndex: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 28 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 26, height: 26, borderRadius: 7,
              background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
              display: 'grid', placeItems: 'center', color: 'white', fontWeight: 700, fontSize: 12,
            }}>K</div>
            <div style={{ fontWeight: 600, fontSize: 14 }}>Kalshi Weather</div>
          </div>
          <nav style={{ display: 'flex', gap: 3, fontSize: 13 }}>
            {tabs.map(tab => (
              <button key={tab} onClick={() => onNavigate(tab)} style={{
                padding: '7px 13px', borderRadius: 7, border: 'none',
                color: active === tab ? 'var(--text)' : 'var(--text-muted)',
                background: active === tab ? 'var(--bg-muted)' : 'transparent',
                fontWeight: active === tab ? 600 : 500, cursor: 'pointer',
                fontFamily: 'inherit',
              }}>{tab}</button>
            ))}
          </nav>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 5,
            padding: '4px 10px', borderRadius: 999, background: 'rgba(234,179,8,0.12)', color: '#ca8a04',
            fontSize: 11, fontWeight: 600,
          }}>Demo · Paper</span>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 5,
            padding: '4px 10px', borderRadius: 999, background: 'rgba(34,197,94,0.12)', color: '#16a34a',
            fontSize: 11, fontWeight: 600,
          }}>● Live</span>
          <button onClick={onToggleTheme} title="Toggle theme" style={{
            padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border)',
            background: 'var(--bg-card)', color: 'var(--text)', fontSize: 14, cursor: 'pointer',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 32, height: 30,
          }}>{theme === 'dark' ? '☀' : '☾'}</button>
          <button style={{
            padding: '7px 13px', borderRadius: 7, border: '1px solid var(--border)',
            background: 'var(--bg-card)', color: 'var(--text)', fontWeight: 500, fontSize: 12, cursor: 'pointer',
          }}>Kill switch</button>
        </div>
      </header>
    );
  }

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
      <span
        ref={ref}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        style={{ position: 'relative', display: 'inline-block', marginLeft: 5, verticalAlign: 'middle' }}
      >
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }}
          aria-label="More info"
          style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 16, height: 16, borderRadius: '50%', border: 'none', padding: 0,
            background: open ? 'var(--accent, #3b82f6)' : 'var(--bg-muted)',
            color: open ? '#fff' : 'var(--text-muted)',
            fontSize: 10, fontWeight: 700, fontFamily: 'ui-sans-serif, system-ui',
            cursor: 'pointer', lineHeight: 1, fontStyle: 'italic',
            transition: 'background 0.15s, color 0.15s',
          }}
        >i</button>
        {open && (
          <div style={{
            position: 'absolute', top: 'calc(100% + 6px)', left: '50%', transform: 'translateX(-50%)',
            zIndex: 100, width: 240, padding: '10px 12px',
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 8, boxShadow: '0 8px 24px rgba(0,0,0,0.18)',
            color: 'var(--text)', fontSize: 12, fontWeight: 400, fontStyle: 'normal',
            lineHeight: 1.45, textAlign: 'left', whiteSpace: 'normal',
            fontFamily: 'ui-sans-serif, system-ui',
          }}>{tip}</div>
        )}
      </span>
    );
  }

  function StatCard({ label, value, delta, deltaTone, sub, tooltip }) {
    return (
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 14, padding: '18px 20px',
      }}>
        <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 500, marginBottom: 6 }}>
          {label}
          {tooltip && <InfoIcon tip={tooltip} />}
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <div style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text)' }}>
            {value}
          </div>
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

  // -- Overview tab (enhanced with Fear/Greed + Graduation) --

  function OverviewTab() {
    const s = M.stats;
    const grad = s.graduation;

    return (
      <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
        <div style={{ marginBottom: 18 }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 500, marginBottom: 3 }}>
            Wednesday, May 6 · Good morning
          </div>
          <h1 style={{
            margin: 0, fontSize: 28, fontWeight: 700, letterSpacing: '-0.025em',
            fontFamily: "'Source Serif 4', Georgia, serif",
          }}>
            Up <span style={{ color: '#16a34a' }}>+$127.40</span> today — eight positions open, graduation gate cleared.
          </h1>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
          <StatCard label="Paper balance" tooltip="Simulated cash balance in the paper-trading sandbox. No real money." value={'$' + s.balance.toFixed(2)} delta={'+' + ((s.balance - s.starting_balance) / s.starting_balance * 100).toFixed(1) + '%'} deltaTone="pos" sub={'from $' + s.starting_balance.toFixed(2) + ' start'} />
          <StatCard label="Open positions" tooltip="Active contracts that haven't expired or been closed yet." value={s.open_count} sub={s.settled_count + ' settled so far'} />
          <StatCard label="Win rate" tooltip="% of settled trades that were profitable. Above 55% with positive edge is healthy." value={(s.win_rate * 100).toFixed(1) + '%'} delta="+2.3 pts" deltaTone="pos" />
          <StatCard label="Brier score" tooltip="Forecast quality metric (0 = perfect, 0.25 = random coin flip). Lower is better. Below 0.20 means the model is well-calibrated." value={s.brier.toFixed(3)} delta="−0.012" deltaTone="pos" sub="target ≤0.20" />
        </div>

        {/* Graduation progress bars */}
        <section style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 14, padding: '20px', marginBottom: 18,
        }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Graduation progress</h3>
          <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 16, lineHeight: 1.4 }}>
            Three gates to go live: 30+ trades, $50+ P&L, Brier ≤0.20. {grad.ready ? '✓ Ready!' : 'Keep building track record…'}
          </p>
          <div style={{ display: 'grid', gap: 14 }}>
            {[
              { label: 'Trades', current: grad.trades_done, target: grad.trades_target, unit: '', complete: grad.trades_done >= grad.trades_target },
              { label: 'P&L', current: grad.total_pnl, target: grad.pnl_target, unit: '$', complete: grad.total_pnl >= grad.pnl_target },
              { label: 'Brier', current: grad.brier, target: grad.brier_target, unit: '', invert: true, complete: grad.brier <= grad.brier_target },
            ].map((g, i) => {
              const pct = g.invert
                ? Math.min(100, Math.max(0, (1 - g.current / 0.25) * 100))
                : Math.min(100, (g.current / g.target) * 100);
              return (
                <div key={i}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                    <span style={{ fontWeight: 600 }}>{g.label}</span>
                    <span style={{ fontFamily: 'ui-monospace, monospace', color: g.complete ? '#16a34a' : 'var(--text-muted)' }}>
                      {g.unit}{g.current.toFixed(g.unit === '$' ? 2 : g.invert ? 3 : 0)}/{g.unit}{g.target}
                    </span>
                  </div>
                  <div style={{ height: 8, background: 'var(--bg-muted)', borderRadius: 4, overflow: 'hidden' }}>
                    <div style={{
                      width: pct + '%', height: '100%',
                      background: g.complete ? '#16a34a' : '#3b82f6',
                    }} />
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* Fear/Greed gauge + Circuit breakers */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 12, marginBottom: 18 }}>
          <section style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 14, padding: '20px',
          }}>
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

          <section style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 14, padding: '20px',
          }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 14 }}>Data sources</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 9 }}>
              {M.circuitBreakers.map((cb, i) => {
                const isOpen = cb.state === 'open';
                return (
                  <div key={i} style={{
                    padding: '9px 11px', borderRadius: 8,
                    background: 'var(--bg-subtle)', border: '1px solid ' + (isOpen ? '#ef4444' : '#eef0f3'),
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                      <span style={{
                        width: 6, height: 6, borderRadius: '50%',
                        background: isOpen ? '#ef4444' : '#16a34a',
                      }} />
                      <span style={{ fontSize: 11, fontWeight: 600 }}>{cb.label}</span>
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text-faint)', fontFamily: 'ui-monospace, monospace' }}>
                      {isOpen ? `Retry ${cb.retry_in_s}s` : `${cb.latency_ms}ms`}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        </div>

        {/* Quick summary cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {[
            { title: 'Open Positions', count: M.positions.length, desc: 'View all with detail' },
            { title: 'Top Opportunities', count: M.opportunities.length, desc: 'Signals with edge ≥7%' },
            { title: 'Closed Trades', count: M.closedTrades.length, desc: 'History & P&L' },
            { title: 'Forecast Quality', count: Object.keys(M.cityBrier).length, desc: 'Cities tracked' },
          ].map((card, i) => (
            <section key={i} style={{
              background: 'var(--bg-card)', border: '1px solid var(--border)',
              borderRadius: 14, padding: '18px 20px', cursor: 'pointer',
            }}>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>{card.title}</h3>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#3b82f6', marginBottom: 6 }}>{card.count}</div>
              <div style={{ color: 'var(--text-faint)', fontSize: 12 }}>{card.desc}</div>
            </section>
          ))}
        </div>
      </main>
    );
  }

  // -- Positions tab (unchanged) --

  function PositionsTab() {
    const [filter, setFilter] = useState('');
    const [sortKey, setSortKey] = useState('edge');
    const [selectedPos, setSelectedPos] = useState(null);

    const filtered = useMemo(() => {
      const f = filter.toLowerCase();
      const rows = M.positions.filter(p => !f || p.city.toLowerCase().includes(f) || p.ticker.toLowerCase().includes(f));
      return [...rows].sort((a, b) => {
        if (sortKey === 'edge') return b.edge - a.edge;
        if (sortKey === 'cost') return b.cost - a.cost;
        if (sortKey === 'age') return a.age_h - b.age_h;
        return 0;
      });
    }, [filter, sortKey]);

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
            <input
              placeholder="Filter by city or ticker..."
              value={filter}
              onChange={e => setFilter(e.target.value)}
              style={{
                padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)',
                background: 'var(--bg-card)', fontSize: 13, width: 240, outline: 'none',
              }} />
            <select value={sortKey} onChange={e => setSortKey(e.target.value)} style={{
              padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)',
              background: 'var(--bg-card)', fontSize: 13, cursor: 'pointer',
            }}>
              <option value="edge">Sort by Edge</option>
              <option value="cost">Sort by Cost</option>
              <option value="age">Sort by Age</option>
            </select>
          </div>
        </div>

        <section style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 14, overflow: 'hidden',
        }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 12 }}>
                {['Ticker', 'City', 'Side', 'Cost', 'Qty', 'Mark', 'Fcst', 'Edge', 'Model', 'Expiry', 'Age'].map((h, i) => (
                  <th key={h} style={{
                    padding: '12px 16px', textAlign: i >= 3 && i <= 7 ? 'right' : 'left',
                    fontWeight: 600, borderBottom: '1px solid var(--border)',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((p, i) => (
                <tr key={i} onClick={() => setSelectedPos(p)} style={{
                  borderBottom: '1px solid var(--bg-muted)', cursor: 'pointer',
                  background: selectedPos === p ? 'var(--bg-subtle)' : 'transparent',
                }}>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#3b82f6' }}>
                    {p.ticker}
                  </td>
                  <td style={{ padding: '14px 16px', fontWeight: 600 }}>{p.city}</td>
                  <td style={{ padding: '14px 16px' }}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 999,
                      background: p.side === 'yes' ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
                      color: p.side === 'yes' ? '#16a34a' : '#ef4444',
                      fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                    }}>{p.side}</span>
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>${p.cost.toFixed(2)}</td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>{p.qty}</td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)' }}>{p.mark.toFixed(2)}</td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>{p.fcst.toFixed(2)}</td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', color: '#16a34a', fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>
                    +{(p.edge * 100).toFixed(1)}%
                  </td>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-muted)' }}>{p.model}</td>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-muted)' }}>{p.expiry}</td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-faint)' }}>{p.age_h}h</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {selectedPos && (
          <section style={{
            marginTop: 18, background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 14, padding: '20px 24px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>{selectedPos.city} · {selectedPos.ticker}</h3>
                <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
                  Opened {selectedPos.age_h}h ago · {selectedPos.model} forecast · closes {selectedPos.expiry}
                </p>
              </div>
              <button onClick={() => setSelectedPos(null)} style={{
                padding: '6px 12px', borderRadius: 7, border: '1px solid var(--border)',
                background: 'var(--bg-card)', fontSize: 12, cursor: 'pointer',
              }}>Close</button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16 }}>
              {[
                { label: 'Side', value: selectedPos.side.toUpperCase() },
                { label: 'Cost basis', value: '$' + selectedPos.cost.toFixed(2) },
                { label: 'Quantity', value: selectedPos.qty + ' contracts' },
                { label: 'Current mark', value: selectedPos.mark.toFixed(2) },
                { label: 'Unrealized P&L', value: '+$' + ((selectedPos.mark - selectedPos.cost / selectedPos.qty) * selectedPos.qty).toFixed(2) },
              ].map((item, i) => (
                <div key={i}>
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

  // -- Signals tab (with stars, Kelly $, flags) --

  function SignalsTab() {
    const [minEdge, setMinEdge] = useState(5);
    const [selectedOpp, setSelectedOpp] = useState(null);

    const filtered = useMemo(() => {
      return M.opportunities.filter(o => o.edge * 100 >= minEdge);
    }, [minEdge]);

    return (
      <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 18 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em' }}>Signals</h1>
            <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
              {filtered.length} opportunities above {minEdge}% edge · updated 2 min ago
            </p>
            <p style={{ margin: '6px 0 0', color: 'var(--text-muted)', fontSize: 12, maxWidth: 560, lineHeight: 1.5 }}>
              Each row is a market the bot would buy if you approved it now. Stars rank conviction; flags warn about specific risks. Click a row for the full forecast breakdown.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <label style={{ fontSize: 13, color: 'var(--text-muted)' }}>Min edge:</label>
            <input
              type="range"
              min="0"
              max="20"
              step="1"
              value={minEdge}
              onChange={e => setMinEdge(+e.target.value)}
              style={{ width: 120 }} />
            <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'ui-monospace, monospace', minWidth: 40 }}>
              {minEdge}%
            </span>
          </div>
        </div>

        {/* Flags legend */}
        <section style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 12, padding: '12px 16px', marginBottom: 14,
          display: 'flex', flexWrap: 'wrap', gap: 20, alignItems: 'center',
          fontSize: 12,
        }}>
          <span style={{ color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', fontSize: 11 }}>Flag legend</span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ color: '#16a34a', fontWeight: 700, fontSize: 13 }}>★★★</span>
            <span style={{ color: 'var(--text)' }}>High conviction</span>
            <span style={{ color: 'var(--text-muted)' }}>· edge ≥10% & strong model agreement</span>
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ color: '#ca8a04', fontWeight: 700, fontSize: 14 }}>⚠</span>
            <span style={{ color: 'var(--text)' }}>Near threshold</span>
            <span style={{ color: 'var(--text-muted)' }}>· forecast is close to the strike — small temp swings flip the outcome</span>
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ color: 'var(--text-muted)', fontWeight: 700, fontSize: 14 }}>↔</span>
            <span style={{ color: 'var(--text)' }}>Hedge</span>
            <span style={{ color: 'var(--text-muted)' }}>· takes the opposite side of an open position to lock in profit or cap loss if the forecast shifts</span>
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ color: 'var(--text-faint)', fontWeight: 700 }}>—</span>
            <span style={{ color: 'var(--text-muted)' }}>No flags</span>
          </span>
        </section>

        <section style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 14, overflow: 'hidden', marginBottom: 18,
        }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 12 }}>
                {['★', 'Ticker', 'City', 'Side', 'Edge', 'Risk', 'Kelly $', 'Flags'].map((h, i) => (
                  <th key={h} style={{
                    padding: '12px 16px', textAlign: i === 4 || i === 6 ? 'right' : 'left',
                    fontWeight: 600, borderBottom: '1px solid var(--border)',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((o, i) => (
                <tr key={i} onClick={() => setSelectedOpp(o)} style={{
                  borderBottom: '1px solid var(--bg-muted)', cursor: 'pointer',
                  background: selectedOpp === o ? 'var(--bg-subtle)' : 'transparent',
                }}>
                  <td style={{ padding: '14px 16px', color: o.stars === '★★★' ? '#16a34a' : o.stars === '★★' ? '#ca8a04' : 'var(--text-faint)', letterSpacing: '1px' }}>
                    {o.stars}
                  </td>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#3b82f6' }}>
                    {o.ticker.split('-')[0].replace('KX', '')}
                  </td>
                  <td style={{ padding: '14px 16px', fontWeight: 600 }}>{o.city}</td>
                  <td style={{ padding: '14px 16px' }}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 999,
                      background: o.side === 'yes' ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
                      color: o.side === 'yes' ? '#16a34a' : '#ef4444',
                      fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                    }}>{o.side}</span>
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', color: '#16a34a', fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>
                    +{(o.edge * 100).toFixed(1)}%
                  </td>
                  <td style={{ padding: '14px 16px' }}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 999, fontSize: 10, fontWeight: 600,
                      background: o.time_risk === 'LOW' ? 'rgba(34,197,94,0.12)' : o.time_risk === 'MEDIUM' ? 'rgba(234,179,8,0.12)' : 'rgba(239,68,68,0.12)',
                      color: o.time_risk === 'LOW' ? '#16a34a' : o.time_risk === 'MEDIUM' ? '#ca8a04' : '#ef4444',
                    }}>{o.time_risk}</span>
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)' }}>
                    ${o.kelly_dollars.toFixed(2)}
                  </td>
                  <td style={{ padding: '14px 16px', fontSize: 11 }}>
                    {o.near_threshold && <span title="Near threshold — flip risk" style={{ color: '#ca8a04' }}>⚠ </span>}
                    {o.is_hedge && <span title="Hedges existing position" style={{ color: 'var(--text-muted)' }}>↔ </span>}
                    {!o.near_threshold && !o.is_hedge && <span style={{ color: 'var(--text-faint)' }}>—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {selectedOpp && (
          <section style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 14, padding: '20px 24px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>{selectedOpp.city} · {selectedOpp.ticker.split('-')[0]}</h3>
                <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
                  {selectedOpp.stars} signal · {selectedOpp.model_agreement}% model agreement
                </p>
              </div>
              <button onClick={() => setSelectedOpp(null)} style={{
                padding: '6px 12px', borderRadius: 7, border: '1px solid var(--border)',
                background: 'var(--bg-card)', fontSize: 12, cursor: 'pointer',
              }}>Close</button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16, marginBottom: 20 }}>
              {M.modelAccuracy.map((m, i) => (
                <div key={i}>
                  <div style={{ color: 'var(--text-faint)', fontSize: 11, marginBottom: 4 }}>{m.model}</div>
                  <div style={{ fontWeight: 600, fontSize: 15, fontFamily: 'ui-monospace, monospace' }}>
                    {(selectedOpp.fcst + (Math.random() - 0.5) * 0.08).toFixed(2)}
                  </div>
                </div>
              ))}
            </div>
            <div style={{ padding: '14px 16px', borderRadius: 8, background: 'var(--bg-muted)', fontSize: 12 }}>
              <strong>Suggested action:</strong> Buy {selectedOpp.side.toUpperCase()} at {selectedOpp.yes_ask.toFixed(2)} with Kelly ${selectedOpp.kelly_dollars.toFixed(2)}
            </div>
          </section>
        )}
      </main>
    );
  }

  // -- Forecast tab (Today/Tomorrow + City heatmap) --

  function ForecastTab() {
    return (
      <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Forecast</h1>
        <p style={{ margin: '4px 0 0 0', color: 'var(--text-muted)', fontSize: 13, marginBottom: 24 }}>
          Today & tomorrow forecasts, city calibration, model ensemble spread.
        </p>

        {/* Today & Tomorrow forecast tables */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, marginBottom: 18 }}>
          {[['Today', M.todayForecasts], ['Tomorrow', M.tomorrowForecasts]].map(([label, data]) => (
            <section key={label} style={{
              background: 'var(--bg-card)', border: '1px solid var(--border)',
              borderRadius: 14, overflow: 'hidden',
            }}>
              <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)' }}>
                <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>{label} — {new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</h3>
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 11 }}>
                    {['City', 'High', 'Range', 'Precip', 'Models'].map(h => (
                      <th key={h} style={{
                        padding: '10px 14px', textAlign: 'left',
                        fontWeight: 500, borderBottom: '1px solid var(--border)',
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data).map(([city, f]) => {
                    const spread = f.high_range[1] - f.high_range[0];
                    return (
                      <tr key={city} style={{ borderBottom: '1px solid var(--bg-muted)' }}>
                        <td style={{ padding: '10px 14px', fontWeight: 600 }}>{city}</td>
                        <td style={{ padding: '10px 14px', fontFamily: 'ui-monospace, monospace' }}>{f.high_f.toFixed(1)}°F</td>
                        <td style={{ padding: '10px 14px', fontFamily: 'ui-monospace, monospace', color: spread <= 2 ? '#16a34a' : spread <= 5 ? '#ca8a04' : '#ef4444' }}>
                          {f.high_range[0].toFixed(0)}–{f.high_range[1].toFixed(0)}°
                        </td>
                        <td style={{ padding: '10px 14px', color: f.precip_in > 0.01 ? '#ca8a04' : 'var(--text-faint)', fontSize: 11 }}>
                          {f.precip_in > 0.01 ? f.precip_in.toFixed(2) + '"' : 'Dry'}
                        </td>
                        <td style={{ padding: '10px 14px', color: f.models_used >= 3 ? '#16a34a' : '#ca8a04', fontSize: 11 }}>
                          {f.models_used}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>
          ))}
        </div>

        {/* City Brier heatmap */}
        <section style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 14, padding: '20px',
        }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>City calibration · Brier score</h3>
          <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
            Lower = better. Target ≤0.20 for each city. Accumulates after 10+ settled trades per city.
          </p>
          {Object.entries(M.cityBrier).sort((a, b) => a[1] - b[1]).map(([city, brier], i) => {
            const pct = ((0.25 - brier) / 0.25) * 100;
            return (
              <div key={i} style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                  <span style={{ fontWeight: 600 }}>{city}</span>
                  <span style={{
                    fontFamily: 'ui-monospace, monospace', fontSize: 11,
                    color: brier < 0.20 ? '#16a34a' : brier < 0.30 ? '#ca8a04' : '#ef4444', fontWeight: 700,
                  }}>
                    {brier.toFixed(3)}
                  </span>
                </div>
                <div style={{ height: 6, background: 'var(--bg-muted)', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{
                    width: pct + '%', height: '100%',
                    background: brier < 0.20 ? '#16a34a' : brier < 0.30 ? '#ca8a04' : '#ef4444',
                  }} />
                </div>
              </div>
            );
          })}
        </section>
      </main>
    );
  }

  // -- Analytics tab (ROC, price improvement, city cal table) --

  function AnalyticsTab() {
    return (
      <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Analytics</h1>
        <p style={{ margin: '4px 0 0 0', color: 'var(--text-muted)', fontSize: 13, marginBottom: 24 }}>
          Backtest performance, P&L attribution, feature importance, model comparison.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
          <StatCard label="Total P&L" tooltip="Cumulative profit/loss across all settled trades since inception." value="+$127.40" delta="+12.7%" deltaTone="pos" sub="From 567 settled trades" />
          <StatCard label="Sharpe ratio" tooltip="Return per unit of risk. >1 is good, >2 is excellent. Annualized over 90 days." value="1.84" delta="+0.14" deltaTone="pos" sub="90-day rolling" />
          <StatCard label="AUC" tooltip="Area Under ROC Curve — measures forecast discrimination. 0.5 = random, 1.0 = perfect. Above 0.70 is solid." value={M.auc.toFixed(3)} sub="ROC area under curve" />
          <StatCard label="Avg price improve" tooltip="Average cents better than the displayed ask price you got on fills. Higher = better execution." value={'+' + M.priceImprovement.avg_improvement_cents.toFixed(2) + '¢'} sub={M.priceImprovement.positive_pct.toFixed(0) + '% positive fills'} />
        </div>

        {/* P&L attribution + Brier by days */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, marginBottom: 18 }}>
          <section style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 14, padding: '20px',
          }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 14 }}>P&L by model source</h3>
            {M.modelAccuracy.map((m, i) => {
              const pnl = m.edge_realized * 800;
              const pct = (pnl / 127.4) * 100;
              return (
                <div key={i} style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                    <span style={{ fontWeight: 600 }}>{m.model}</span>
                    <span style={{ color: '#16a34a', fontFamily: 'ui-monospace, monospace', fontSize: 12, fontWeight: 600 }}>
                      +${pnl.toFixed(2)}
                    </span>
                  </div>
                  <div style={{ position: 'relative', height: 18, background: 'var(--bg-muted)', borderRadius: 4, overflow: 'hidden' }}>
                    <div style={{
                      position: 'absolute', inset: 0, width: pct + '%',
                      background: '#3b82f6',
                    }} />
                    <span style={{
                      position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)',
                      fontSize: 11, color: 'var(--text)', fontFamily: 'ui-monospace, monospace', fontWeight: 600,
                    }}>{pct.toFixed(0)}%</span>
                  </div>
                </div>
              );
            })}
          </section>

          <section style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 14, padding: '20px',
          }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Brier by days out</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
              Forecast accuracy degrades with horizon. 1-2 days out is strongest.
            </p>
            {Object.entries(M.brierByDays).map(([day, brier], i) => (
              <div key={i} style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                  <span style={{ fontWeight: 600 }}>{day} day{day !== '1' ? 's' : ''} out</span>
                  <span style={{
                    fontFamily: 'ui-monospace, monospace', fontSize: 11,
                    color: brier < 0.20 ? '#16a34a' : brier < 0.30 ? '#ca8a04' : '#ef4444', fontWeight: 700,
                  }}>{brier.toFixed(3)}</span>
                </div>
                <div style={{ height: 6, background: 'var(--bg-muted)', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{
                    width: ((0.35 - brier) / 0.35) * 100 + '%', height: '100%',
                    background: brier < 0.20 ? '#16a34a' : brier < 0.30 ? '#ca8a04' : '#ef4444',
                  }} />
                </div>
              </div>
            ))}
          </section>
        </div>

        {/* City calibration table */}
        <section style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 14, overflow: 'hidden',
        }}>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)' }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>City calibration detail</h3>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 12 }}>
                {['City', 'N', 'Brier', 'Bias'].map(h => (
                  <th key={h} style={{
                    padding: '12px 16px', textAlign: h === 'City' ? 'left' : 'right',
                    fontWeight: 600, borderBottom: '1px solid var(--border)',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(M.cityCalibration).map(([city, cal], i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--bg-muted)' }}>
                  <td style={{ padding: '12px 16px', fontWeight: 600 }}>{city}</td>
                  <td style={{ padding: '12px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>{cal.n}</td>
                  <td style={{ padding: '12px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: cal.brier < 0.20 ? '#16a34a' : '#ca8a04' }}>
                    {cal.brier.toFixed(3)}
                  </td>
                  <td style={{ padding: '12px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)' }}>
                    {cal.bias >= 0 ? '+' : ''}{cal.bias.toFixed(3)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </main>
    );
  }

  // -- Risk tab (aged, correlated, directional, expiry cluster) --

  function RiskTab() {
    return (
      <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Risk</h1>
        <p style={{ margin: '4px 0 0 0', color: 'var(--text-muted)', fontSize: 13, marginBottom: 24 }}>
          Portfolio exposure, aged positions, correlated events, directional bias, expiry clustering.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
          <StatCard label="Portfolio heat" tooltip="% of capital deployed across open positions. Bot halts new trades above 80%." value="67%" sub="Within 80% limit" />
          <StatCard label="Aged positions" tooltip="Positions held longer than 36 hours. Old positions tie up capital and may signal stuck trades." value={M.agedPositions.length} sub=">36h old" />
          <StatCard label="Correlated events" tooltip="Multiple positions on related markets (same city, same day). High correlation means one weather miss hits multiple positions." value={M.correlatedEvents.length} sub="Same-day exposure" />
          <StatCard label="VaR (95%)" tooltip="Value at Risk. With 95% confidence, you won't lose more than this in 1 day." value="-$92.10" sub="1-day horizon" />
        </div>

        {/* Directional bias + Expiry clustering */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 18, marginBottom: 18 }}>
          <section style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 14, padding: '20px',
          }}>
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

          <section style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 14, padding: '20px',
          }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Expiry clustering</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
              ≥3 positions on same date = concentration risk. Spread expiries to reduce correlated losses.
            </p>
            {M.expiryCluster.map((exp, i) => (
              <div key={i} style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                  <span style={{ fontWeight: 600 }}>{exp.date}</span>
                  <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, color: exp.count >= 4 ? '#ef4444' : exp.count >= 3 ? '#ca8a04' : 'var(--text-muted)' }}>
                    {exp.count} pos · ${exp.total_cost.toFixed(2)}
                  </span>
                </div>
                <div style={{ height: 6, background: 'var(--bg-muted)', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{
                    width: (exp.count / 4) * 100 + '%', height: '100%',
                    background: exp.count >= 4 ? '#ef4444' : exp.count >= 3 ? '#ca8a04' : '#3b82f6',
                  }} />
                </div>
              </div>
            ))}
          </section>
        </div>

        {/* Exposure by city */}
        <section style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 14, padding: '20px', marginBottom: 18,
        }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 14 }}>Exposure by city</h3>
          {['Chicago', 'New York', 'Miami', 'Los Angeles', 'Boston'].map((city, i) => {
            const exp = [42, 38, 65, 35, 38][i];
            return (
              <div key={i} style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                  <span style={{ fontWeight: 600 }}>{city}</span>
                  <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-muted)' }}>
                    ${exp}.00 · {Math.round((exp / 218) * 100)}%
                  </span>
                </div>
                <div style={{ height: 6, background: 'var(--bg-muted)', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{ width: (exp / 65) * 100 + '%', height: '100%', background: '#3b82f6' }} />
                </div>
              </div>
            );
          })}
        </section>

        {/* Kill switch */}
        <section style={{
          background: 'var(--bg-card)', border: '1px solid #ef4444',
          borderRadius: 14, padding: '20px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: '#ef4444', marginBottom: 4 }}>
                Kill switch
              </h3>
              <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.4 }}>
                Emergency stop: close all positions, halt new orders, liquidate to cash. This cannot be undone.
              </p>
            </div>
            <button style={{
              padding: '10px 20px', borderRadius: 8, border: 'none',
              background: '#ef4444', color: 'white', fontWeight: 600, fontSize: 13, cursor: 'pointer',
            }}>Engage kill switch</button>
          </div>
        </section>
      </main>
    );
  }

  // -- Trades tab (closed history with pagination) --

  function TradesTab() {
    const [page, setPage] = useState(0);
    const [cityFilter, setCityFilter] = useState('');
    const [sideFilter, setSideFilter] = useState('');
    const PAGE_SIZE = 10;

    const filtered = useMemo(() => {
      return M.closedTrades.filter(t => {
        return (!cityFilter || t.city === cityFilter) && (!sideFilter || t.side === sideFilter);
      });
    }, [cityFilter, sideFilter]);

    const paginated = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
    const totalPages = Math.ceil(filtered.length / PAGE_SIZE);

    const cities = [...new Set(M.closedTrades.map(t => t.city))].sort();

    return (
      <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 18 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em' }}>Trade History</h1>
            <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
              {filtered.length} closed trades · {M.closedTrades.filter(t => t.pnl > 0).length} wins · {M.closedTrades.filter(t => t.pnl < 0).length} losses
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <select value={cityFilter} onChange={e => { setCityFilter(e.target.value); setPage(0); }} style={{
              padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)',
              background: 'var(--bg-card)', fontSize: 13, cursor: 'pointer',
            }}>
              <option value="">All cities</option>
              {cities.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={sideFilter} onChange={e => { setSideFilter(e.target.value); setPage(0); }} style={{
              padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)',
              background: 'var(--bg-card)', fontSize: 13, cursor: 'pointer',
            }}>
              <option value="">All sides</option>
              <option value="yes">YES</option>
              <option value="no">NO</option>
            </select>
          </div>
        </div>

        <section style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 14, overflow: 'hidden', marginBottom: 18,
        }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 12 }}>
                {['Ticker', 'City', 'Side', 'Entry', 'Outcome', 'P&L', 'Entered'].map((h, i) => (
                  <th key={h} style={{
                    padding: '12px 16px', textAlign: i >= 3 && i <= 5 ? 'right' : 'left',
                    fontWeight: 600, borderBottom: '1px solid var(--border)',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {paginated.map((t, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--bg-muted)' }}>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#3b82f6' }}>
                    {t.ticker}
                  </td>
                  <td style={{ padding: '14px 16px', fontWeight: 600 }}>{t.city}</td>
                  <td style={{ padding: '14px 16px' }}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 999,
                      background: t.side === 'yes' ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
                      color: t.side === 'yes' ? '#16a34a' : '#ef4444',
                      fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                    }}>{t.side}</span>
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>
                    {(t.entry_price * 100).toFixed(0)}¢
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right' }}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 999,
                      background: t.outcome === 'yes' ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
                      color: t.outcome === 'yes' ? '#16a34a' : '#ef4444',
                      fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                    }}>{t.outcome}</span>
                  </td>
                  <td style={{
                    padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', fontWeight: 700,
                    color: t.pnl >= 0 ? '#16a34a' : '#ef4444',
                  }}>
                    {t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}
                  </td>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-faint)' }}>
                    {new Date(t.entered_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
            {Array.from({ length: totalPages }, (_, i) => (
              <button key={i} onClick={() => setPage(i)} style={{
                padding: '6px 12px', borderRadius: 7,
                border: '1px solid var(--border)',
                background: page === i ? '#3b82f6' : 'var(--bg-card)',
                color: page === i ? 'white' : 'var(--text)',
                fontWeight: 500, fontSize: 12, cursor: 'pointer',
              }}>
                {i + 1}
              </button>
            ))}
          </div>
        )}
      </main>
    );
  }

  // -- Main app --

  function App() {
    const [activeTab, setActiveTab] = useState('Overview');
    const [theme, setTheme] = useState(() => localStorage.getItem('kalshi-theme') || 'light');

    useEffect(() => {
      applyTheme(theme);
      localStorage.setItem('kalshi-theme', theme);
    }, [theme]);

    let content;
    if (activeTab === 'Overview') content = <OverviewTab />;
    else if (activeTab === 'Positions') content = <PositionsTab />;
    else if (activeTab === 'Signals') content = <SignalsTab />;
    else if (activeTab === 'Forecast') content = <ForecastTab />;
    else if (activeTab === 'Analytics') content = <AnalyticsTab />;
    else if (activeTab === 'Risk') content = <RiskTab />;
    else if (activeTab === 'Trades') content = <TradesTab />;

    return (
      <div style={{
        background: 'var(--bg-page)', color: 'var(--text)',
        fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        fontSize: 14, minHeight: '100vh',
      }}>
        <Nav active={activeTab} onNavigate={setActiveTab} theme={theme} onToggleTheme={() => setTheme(t => t === 'dark' ? 'light' : 'dark')} />
        {content}
      </div>
    );
  }

  return { App };
})();

ReactDOM.createRoot(document.getElementById('full-proto-root')).render(<FullProto.App />);
