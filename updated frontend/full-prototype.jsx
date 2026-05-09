// Full multi-tab operator dashboard prototype
// Tabs: Overview | Positions | Signals | Analytics | Risk | Calibration

const FullProto = (function () {
  const M = window.MOCK;
  const { useState, useMemo } = React;

  // -- Shared components --

  function Nav({ active, onNavigate }) {
    const tabs = ['Overview', 'Positions', 'Signals', 'Analytics', 'Risk', 'Calibration'];
    return (
      <header style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '16px 28px', borderBottom: '1px solid #e7eaef',
        background: '#fff', position: 'sticky', top: 0, zIndex: 10,
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
                color: active === tab ? '#0f172a' : '#64748b',
                background: active === tab ? '#f1f5f9' : 'transparent',
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
          <button style={{
            padding: '7px 13px', borderRadius: 7, border: '1px solid #e7eaef',
            background: '#fff', color: '#0f172a', fontWeight: 500, fontSize: 12, cursor: 'pointer',
          }}>Kill switch</button>
        </div>
      </header>
    );
  }

  function StatCard({ label, value, delta, deltaTone, sub }) {
    return (
      <div style={{
        background: '#fff', border: '1px solid #e7eaef',
        borderRadius: 14, padding: '18px 20px',
      }}>
        <div style={{ color: '#64748b', fontSize: 12, fontWeight: 500, marginBottom: 6 }}>{label}</div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <div style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-0.02em', color: '#0f172a' }}>
            {value}
          </div>
          {delta && (
            <div style={{
              fontSize: 13, fontWeight: 600,
              color: deltaTone === 'pos' ? '#16a34a' : deltaTone === 'neg' ? '#ef4444' : '#64748b',
            }}>{delta}</div>
          )}
        </div>
        {sub && <div style={{ marginTop: 6, color: '#94a3b8', fontSize: 11 }}>{sub}</div>}
      </div>
    );
  }

  // -- Overview tab (from variation-hybrid) --

  function OverviewTab() {
    const s = M.stats;

    return (
      <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
        <div style={{ marginBottom: 18 }}>
          <div style={{ color: '#64748b', fontSize: 12, fontWeight: 500, marginBottom: 3 }}>
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
          <StatCard label="Paper balance" value={'$' + s.balance.toFixed(2)} delta={'+' + ((s.balance - s.starting_balance) / s.starting_balance * 100).toFixed(1) + '%'} deltaTone="pos" sub={'from $' + s.starting_balance.toFixed(2) + ' start'} />
          <StatCard label="Open positions" value={s.open_count} sub={s.settled_count + ' settled so far'} />
          <StatCard label="Win rate" value={(s.win_rate * 100).toFixed(1) + '%'} delta="+2.3 pts" deltaTone="pos" />
          <StatCard label="Brier score" value={s.brier.toFixed(3)} delta="−0.012" deltaTone="pos" sub="target ≤0.20" />
        </div>

        <section style={{
          background: '#fff', border: '1px solid #e7eaef',
          borderRadius: 14, padding: '18px 20px', marginBottom: 18,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 3 }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>Equity curve · 90 days</h2>
            <div style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'ui-monospace, monospace' }}>Feb 5 → today</div>
          </div>
          <p style={{ color: '#64748b', fontSize: 12, marginTop: 3, marginBottom: 16 }}>
            Started with $1,000. After a mid-March drawdown, Kelly sizing recovered and held steady.
          </p>
          <div style={{ height: 240, display: 'grid', placeItems: 'center', color: '#94a3b8', fontSize: 13 }}>
            [Equity chart — see variation-hybrid.jsx]
          </div>
        </section>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 12 }}>
          {[
            { title: 'Open Positions', count: 8, desc: 'View all positions with detail' },
            { title: 'Top Opportunities', count: 7, desc: 'Signals with edge ≥ 7%' },
            { title: 'Data Sources', count: 6, desc: '1 circuit breaker open' },
            { title: 'ML Calibration', count: 8, desc: 'Per-city models trained' },
          ].map((card, i) => (
            <section key={i} style={{
              background: '#fff', border: '1px solid #e7eaef',
              borderRadius: 14, padding: '18px 20px', cursor: 'pointer',
            }}>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>{card.title}</h3>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#3b82f6', marginBottom: 6 }}>{card.count}</div>
              <div style={{ color: '#94a3b8', fontSize: 12 }}>{card.desc}</div>
            </section>
          ))}
        </div>
      </main>
    );
  }

  // -- Positions tab --

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
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em' }}>
              Open Positions
            </h1>
            <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 13 }}>
              {M.positions.length} positions · ${M.positions.reduce((a, p) => a + p.cost, 0).toFixed(2)} deployed
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <input
              placeholder="Filter by city or ticker..."
              value={filter}
              onChange={e => setFilter(e.target.value)}
              style={{
                padding: '8px 14px', borderRadius: 8, border: '1px solid #e7eaef',
                background: '#fff', fontSize: 13, width: 240, outline: 'none',
              }} />
            <select value={sortKey} onChange={e => setSortKey(e.target.value)} style={{
              padding: '8px 14px', borderRadius: 8, border: '1px solid #e7eaef',
              background: '#fff', fontSize: 13, cursor: 'pointer',
            }}>
              <option value="edge">Sort by Edge</option>
              <option value="cost">Sort by Cost</option>
              <option value="age">Sort by Age</option>
            </select>
          </div>
        </div>

        <section style={{
          background: '#fff', border: '1px solid #e7eaef',
          borderRadius: 14, overflow: 'hidden',
        }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#f8f9fb', color: '#64748b', fontSize: 12 }}>
                {['Ticker', 'City', 'Side', 'Cost', 'Qty', 'Mark', 'Fcst', 'Edge', 'Model', 'Expiry', 'Age'].map((h, i) => (
                  <th key={h} style={{
                    padding: '12px 16px', textAlign: i >= 3 && i <= 7 ? 'right' : 'left',
                    fontWeight: 600, borderBottom: '1px solid #e7eaef',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((p, i) => (
                <tr key={i} onClick={() => setSelectedPos(p)} style={{
                  borderBottom: '1px solid #f1f5f9', cursor: 'pointer',
                  background: selectedPos === p ? '#f8f9fb' : 'transparent',
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
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: '#64748b' }}>{p.mark.toFixed(2)}</td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>{p.fcst.toFixed(2)}</td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', color: '#16a34a', fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>
                    +{(p.edge * 100).toFixed(1)}%
                  </td>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#64748b' }}>{p.model}</td>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#64748b' }}>{p.expiry}</td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#94a3b8' }}>{p.age_h}h</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {selectedPos && (
          <section style={{
            marginTop: 18, background: '#fff', border: '1px solid #e7eaef',
            borderRadius: 14, padding: '20px 24px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>{selectedPos.city} · {selectedPos.ticker}</h3>
                <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 13 }}>
                  Opened {selectedPos.age_h}h ago · {selectedPos.model} forecast · closes {selectedPos.expiry}
                </p>
              </div>
              <button onClick={() => setSelectedPos(null)} style={{
                padding: '6px 12px', borderRadius: 7, border: '1px solid #e7eaef',
                background: '#fff', fontSize: 12, cursor: 'pointer',
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
                  <div style={{ color: '#94a3b8', fontSize: 11, marginBottom: 4 }}>{item.label}</div>
                  <div style={{ fontWeight: 600, fontSize: 15, fontFamily: 'ui-monospace, monospace' }}>{item.value}</div>
                </div>
              ))}
            </div>
          </section>
        )}
      </main>
    );
  }

  // -- Signals tab --

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
            <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 13 }}>
              {filtered.length} opportunities above {minEdge}% edge · updated 2 min ago
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <label style={{ fontSize: 13, color: '#64748b' }}>Min edge:</label>
            <input
              type="range"
              min="0"
              max="15"
              step="1"
              value={minEdge}
              onChange={e => setMinEdge(+e.target.value)}
              style={{ width: 120 }} />
            <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'ui-monospace, monospace', minWidth: 40 }}>
              {minEdge}%
            </span>
          </div>
        </div>

        <section style={{
          background: '#fff', border: '1px solid #e7eaef',
          borderRadius: 14, overflow: 'hidden', marginBottom: 18,
        }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#f8f9fb', color: '#64748b', fontSize: 12 }}>
                {['Ticker', 'City', 'Ask', 'Forecast', 'Edge', 'Tier', 'Models agree', 'Volume'].map((h, i) => (
                  <th key={h} style={{
                    padding: '12px 16px', textAlign: i >= 2 && i <= 4 ? 'right' : 'left',
                    fontWeight: 600, borderBottom: '1px solid #e7eaef',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((o, i) => (
                <tr key={i} onClick={() => setSelectedOpp(o)} style={{
                  borderBottom: '1px solid #f1f5f9', cursor: 'pointer',
                  background: selectedOpp === o ? '#f8f9fb' : 'transparent',
                }}>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#3b82f6' }}>
                    {o.ticker.split('-')[0].replace('KX', '')}
                  </td>
                  <td style={{ padding: '14px 16px', fontWeight: 600 }}>{o.city}</td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>
                    {o.yes_ask.toFixed(2)}
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>
                    {o.fcst.toFixed(2)}
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', color: '#16a34a', fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>
                    +{(o.edge * 100).toFixed(1)}%
                  </td>
                  <td style={{ padding: '14px 16px' }}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 999,
                      background: o.tier === 'STRONG' ? 'rgba(34,197,94,0.12)' : 'rgba(100,116,139,0.08)',
                      color: o.tier === 'STRONG' ? '#16a34a' : '#64748b',
                      fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                    }}>{o.tier}</span>
                  </td>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#64748b' }}>
                    {o.model_agreement}%
                  </td>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#94a3b8' }}>
                    {o.volume}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {selectedOpp && (
          <section style={{
            background: '#fff', border: '1px solid #e7eaef',
            borderRadius: 14, padding: '20px 24px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>{selectedOpp.city} · {selectedOpp.ticker.split('-')[0]}</h3>
                <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 13 }}>
                  Forecast breakdown · {selectedOpp.tier} tier · {selectedOpp.model_agreement}% model agreement
                </p>
              </div>
              <button onClick={() => setSelectedOpp(null)} style={{
                padding: '6px 12px', borderRadius: 7, border: '1px solid #e7eaef',
                background: '#fff', fontSize: 12, cursor: 'pointer',
              }}>Close</button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16, marginBottom: 20 }}>
              {M.modelAccuracy.map((m, i) => (
                <div key={i}>
                  <div style={{ color: '#94a3b8', fontSize: 11, marginBottom: 4 }}>{m.model}</div>
                  <div style={{ fontWeight: 600, fontSize: 15, fontFamily: 'ui-monospace, monospace' }}>
                    {(selectedOpp.fcst + (Math.random() - 0.5) * 0.08).toFixed(2)}
                  </div>
                </div>
              ))}
            </div>
            <div style={{ padding: '14px 16px', borderRadius: 8, background: '#f1f5f9', fontSize: 12 }}>
              <strong>Suggested action:</strong> Buy YES at {selectedOpp.yes_ask.toFixed(2)} with Kelly fraction 0.18 (max ${(120 * 0.18).toFixed(2)})
            </div>
          </section>
        )}
      </main>
    );
  }

  // -- Analytics tab --

  function AnalyticsTab() {
    return (
      <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Analytics</h1>
        <p style={{ margin: '4px 0 0 0', color: '#64748b', fontSize: 13, marginBottom: 24 }}>
          Backtest performance, P&L attribution, feature importance, model comparison.
        </p>

        {/* Stats */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
          <StatCard label="Total P&L" value="+$127.40" delta="+12.7%" deltaTone="pos" sub="From 567 settled trades" />
          <StatCard label="Sharpe ratio" value="1.84" delta="+0.14" deltaTone="pos" sub="90-day rolling" />
          <StatCard label="Max drawdown" value="-8.2%" sub="Recovered in 12 days" />
          <StatCard label="Avg hold time" value="18.3h" sub="Target: 12-24h" />
        </div>

        {/* P&L attribution */}
        <section style={{
          background: '#fff', border: '1px solid #e7eaef',
          borderRadius: 14, padding: '20px', marginBottom: 18,
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
                <div style={{ position: 'relative', height: 18, background: '#f1f5f9', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{
                    position: 'absolute', inset: 0, width: pct + '%',
                    background: '#3b82f6',
                  }} />
                  <span style={{
                    position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)',
                    fontSize: 11, color: '#0f172a', fontFamily: 'ui-monospace, monospace', fontWeight: 600,
                  }}>{pct.toFixed(0)}% of total</span>
                </div>
              </div>
            );
          })}
        </section>

        {/* Feature importance */}
        <section style={{
          background: '#fff', border: '1px solid #e7eaef',
          borderRadius: 14, padding: '20px',
        }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Feature importance</h3>
          <p style={{ color: '#64748b', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
            Which variables drive model edge? Shap values from GradientBoosting ensemble.
          </p>
          {[
            { name: 'NBM ensemble spread', value: 0.38 },
            { name: 'Temperature delta (24h)', value: 0.24 },
            { name: 'Model consensus variance', value: 0.19 },
            { name: 'Historical volatility', value: 0.11 },
            { name: 'Hour until close', value: 0.08 },
          ].map((feat, i) => {
            const pct = feat.value * 100;
            return (
              <div key={i} style={{
                display: 'grid', gridTemplateColumns: '1.5fr 1fr 0.5fr', gap: 10, alignItems: 'center',
                padding: '6px 0', fontSize: 12,
              }}>
                <span style={{ fontWeight: 500 }}>{feat.name}</span>
                <div style={{ height: 4, background: '#f1f5f9', borderRadius: 2, overflow: 'hidden' }}>
                  <div style={{ width: pct + '%', height: '100%', background: '#8b5cf6' }} />
                </div>
                <span style={{ textAlign: 'right', fontWeight: 700, fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>
                  {pct.toFixed(0)}%
                </span>
              </div>
            );
          })}
        </section>
      </main>
    );
  }

  // -- Risk tab --

  function RiskTab() {
    return (
      <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Risk</h1>
        <p style={{ margin: '4px 0 0 0', color: '#64748b', fontSize: 13, marginBottom: 24 }}>
          Portfolio exposure, Monte Carlo simulations, drawdown analysis, kill switch controls.
        </p>

        {/* Risk metrics */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
          <StatCard label="Portfolio heat" value="67%" sub="Within 80% limit" />
          <StatCard label="Max position size" value="$87.40" sub="15% of capital" />
          <StatCard label="VaR (95%)" value="-$92.10" sub="1-day horizon" />
          <StatCard label="Days to recovery" value="4.2" sub="Avg after drawdown" />
        </div>

        {/* Monte Carlo */}
        <section style={{
          background: '#fff', border: '1px solid #e7eaef',
          borderRadius: 14, padding: '20px', marginBottom: 18,
        }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Monte Carlo · 1000 sims · 30 days</h3>
          <p style={{ color: '#64748b', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
            Projected equity paths under current strategy. 95% of outcomes fall within the shaded region.
          </p>
          <div style={{
            height: 220, display: 'grid', placeItems: 'center',
            background: '#f8f9fb', borderRadius: 8, color: '#94a3b8', fontSize: 13,
          }}>
            [Monte Carlo fan chart placeholder]
          </div>
          <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
            {[
              { label: 'P5 outcome', value: '$1,082' },
              { label: 'Median', value: '$1,218' },
              { label: 'P95 outcome', value: '$1,387' },
            ].map((stat, i) => (
              <div key={i} style={{ padding: '10px 12px', borderRadius: 8, background: '#f1f5f9' }}>
                <div style={{ color: '#94a3b8', fontSize: 11, marginBottom: 3 }}>{stat.label}</div>
                <div style={{ fontWeight: 700, fontSize: 15, fontFamily: 'ui-monospace, monospace' }}>{stat.value}</div>
              </div>
            ))}
          </div>
        </section>

        {/* Exposure breakdown */}
        <section style={{
          background: '#fff', border: '1px solid #e7eaef',
          borderRadius: 14, padding: '20px', marginBottom: 18,
        }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 14 }}>Exposure by city</h3>
          {['Chicago', 'NYC', 'LA', 'Houston', 'Miami'].map((city, i) => {
            const exp = [42, 38, 27, 19, 14][i];
            return (
              <div key={i} style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                  <span style={{ fontWeight: 600 }}>{city}</span>
                  <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#64748b' }}>
                    ${exp}.00 · {Math.round((exp / 140) * 100)}%
                  </span>
                </div>
                <div style={{ height: 6, background: '#f1f5f9', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{ width: (exp / 42) * 100 + '%', height: '100%', background: '#3b82f6' }} />
                </div>
              </div>
            );
          })}
        </section>

        {/* Kill switch */}
        <section style={{
          background: '#fff', border: '1px solid #ef4444',
          borderRadius: 14, padding: '20px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: '#ef4444', marginBottom: 4 }}>
                Kill switch
              </h3>
              <p style={{ margin: 0, color: '#64748b', fontSize: 12, lineHeight: 1.4 }}>
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

  // -- Calibration tab --

  function CalibrationTab() {
    return (
      <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Calibration</h1>
        <p style={{ margin: '4px 0 0 0', color: '#64748b', fontSize: 13, marginBottom: 24 }}>
          Full calibration curve, Brier history, drift detection, per-city ML models.
        </p>

        {/* Stats */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
          <StatCard label="Overall Brier" value="0.151" delta="−0.012" deltaTone="pos" sub="567 trades" />
          <StatCard label="Calibration error" value="0.028" sub="Mean absolute error" />
          <StatCard label="Resolution" value="0.087" sub="Higher = better" />
          <StatCard label="Drift detected" value="No" sub="Last check: 2m ago" />
        </div>

        {/* Full calibration curve */}
        <section style={{
          background: '#fff', border: '1px solid #e7eaef',
          borderRadius: 14, padding: '20px', marginBottom: 18,
        }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Calibration curve</h3>
          <p style={{ color: '#64748b', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
            Predicted probability vs observed frequency. Perfect calibration = diagonal. Each dot is a 5% bucket.
          </p>
          <div style={{
            height: 280, display: 'grid', placeItems: 'center',
            background: '#f8f9fb', borderRadius: 8, color: '#94a3b8', fontSize: 13,
          }}>
            [Calibration scatter plot placeholder]
          </div>
          <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8, background: '#f1f5f9', fontSize: 12 }}>
            <strong style={{ color: '#0f172a' }}>Interpretation:</strong> Well-calibrated across all buckets. Slight overconfidence at high probabilities (85-95%).
          </div>
        </section>

        {/* Brier history */}
        <section style={{
          background: '#fff', border: '1px solid #e7eaef',
          borderRadius: 14, padding: '20px', marginBottom: 18,
        }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Brier score over time</h3>
          <p style={{ color: '#64748b', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
            30-day rolling Brier. Lower = better. Target threshold at 0.20.
          </p>
          <div style={{
            height: 180, display: 'grid', placeItems: 'center',
            background: '#f8f9fb', borderRadius: 8, color: '#94a3b8', fontSize: 13,
          }}>
            [Brier time series placeholder]
          </div>
        </section>

        {/* Per-city models */}
        <section style={{
          background: '#fff', border: '1px solid #e7eaef',
          borderRadius: 14, padding: '20px',
        }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Per-city ML calibration</h3>
          <p style={{ color: '#64748b', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
            GradientBoosting models trained on 200+ settled trades per city. Brier lift vs raw ensemble forecasts.
          </p>
          {M.mlModels.map((m, i) => {
            const pct = (m.lift / 0.04) * 100;
            return (
              <div key={i} style={{
                display: 'grid', gridTemplateColumns: '1.2fr 1fr 0.9fr', gap: 10, alignItems: 'center',
                padding: '6px 0', fontSize: 12,
              }}>
                <span style={{ fontWeight: 500 }}>{m.city}</span>
                <div style={{ height: 4, background: '#f1f5f9', borderRadius: 2, overflow: 'hidden' }}>
                  <div style={{ width: pct + '%', height: '100%', background: '#3b82f6' }} />
                </div>
                <span style={{ textAlign: 'right', color: '#16a34a', fontWeight: 700, fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>
                  −{m.lift.toFixed(3)}
                </span>
              </div>
            );
          })}
        </section>
      </main>
    );
  }

  // -- Main app --

  function App() {
    const [activeTab, setActiveTab] = useState('Overview');

    let content;
    if (activeTab === 'Overview') content = <OverviewTab />;
    else if (activeTab === 'Positions') content = <PositionsTab />;
    else if (activeTab === 'Signals') content = <SignalsTab />;
    else if (activeTab === 'Analytics') content = <AnalyticsTab />;
    else if (activeTab === 'Risk') content = <RiskTab />;
    else if (activeTab === 'Calibration') content = <CalibrationTab />;

    return (
      <div style={{
        background: '#fafafa', color: '#0f172a',
        fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        fontSize: 14, minHeight: '100vh',
      }}>
        <Nav active={activeTab} onNavigate={setActiveTab} />
        {content}
      </div>
    );
  }

  return { App };
})();

ReactDOM.createRoot(document.getElementById('full-proto-root')).render(<FullProto.App />);
