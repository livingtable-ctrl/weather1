// Variation B — Modern fintech calm
// Generous whitespace, soft surfaces, restrained accents, light-by-default friendly.

const CalmVar = (function () {
  const M = window.MOCK;

  function AreaChart({ data, w = 600, h = 160, color = '#3b82f6', fill = true }) {
    if (!data || !data.length) return null;
    const xs = data.map(d => d.t);
    const ys = data.map(d => d.v);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys) * 0.985, maxY = Math.max(...ys) * 1.005;
    const sx = x => ((x - minX) / Math.max(1, maxX - minX)) * (w - 40) + 30;
    const sy = y => h - 20 - ((y - minY) / Math.max(0.0001, maxY - minY)) * (h - 30);
    const pts = data.map(d => `${sx(d.t).toFixed(1)},${sy(d.v).toFixed(1)}`).join(' ');
    const fillPts = `${sx(data[0].t)},${h - 20} ${pts} ${sx(data[data.length - 1].t)},${h - 20}`;
    return (
      <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
        <defs>
          <linearGradient id="cv-grad" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.18" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((t, i) => (
          <line key={i} x1="30" y1={20 + (h - 40) * t} x2={w - 10} y2={20 + (h - 40) * t}
            stroke="var(--cv-grid)" strokeWidth="1" strokeDasharray="2 4" />
        ))}
        {fill && <polyline points={fillPts} fill="url(#cv-grad)" stroke="none" />}
        <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
        <text x="30" y={h - 4} fontSize="10" fill="var(--cv-muted)">90 days ago</text>
        <text x={w - 10} y={h - 4} fontSize="10" fill="var(--cv-muted)" textAnchor="end">today</text>
      </svg>
    );
  }

  function StatCard({ label, value, delta, deltaTone = 'pos', sub }) {
    return (
      <div style={{
        background: 'var(--cv-surface)', border: '1px solid var(--cv-border)',
        borderRadius: 16, padding: '20px 22px',
      }}>
        <div style={{ color: 'var(--cv-muted)', fontSize: 13, fontWeight: 500 }}>{label}</div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 8 }}>
          <div style={{ fontSize: 28, fontWeight: 600, letterSpacing: '-0.02em', color: 'var(--cv-text)' }}>
            {value}
          </div>
          {delta && (
            <div style={{
              fontSize: 13, fontWeight: 500,
              color: deltaTone === 'pos' ? 'var(--cv-pos)' : deltaTone === 'neg' ? 'var(--cv-neg)' : 'var(--cv-muted)',
            }}>{delta}</div>
          )}
        </div>
        {sub && <div style={{ marginTop: 6, color: 'var(--cv-muted)', fontSize: 12 }}>{sub}</div>}
      </div>
    );
  }

  function SectionCard({ title, action, children, padding = 22 }) {
    return (
      <section style={{
        background: 'var(--cv-surface)', border: '1px solid var(--cv-border)',
        borderRadius: 16, overflow: 'hidden',
      }}>
        <header style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '16px 22px', borderBottom: '1px solid var(--cv-border)',
        }}>
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--cv-text)' }}>{title}</h3>
          {action}
        </header>
        <div style={{ padding }}>{children}</div>
      </section>
    );
  }

  function ProgressRow({ label, current, target, format = v => v, complete }) {
    const pct = Math.min(100, Math.max(0, (current / target) * 100));
    return (
      <div style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
          <span style={{ color: 'var(--cv-muted)' }}>{label}</span>
          <span style={{ color: 'var(--cv-text)', fontWeight: 500 }}>
            {format(current)} <span style={{ color: 'var(--cv-muted)' }}>/ {format(target)}</span>
          </span>
        </div>
        <div style={{ height: 6, background: 'var(--cv-track)', borderRadius: 6, overflow: 'hidden' }}>
          <div style={{
            width: pct + '%', height: '100%',
            background: complete ? 'var(--cv-pos)' : 'var(--cv-accent)',
            transition: 'width 0.5s',
          }} />
        </div>
      </div>
    );
  }

  function Pill({ children, tone = 'neutral' }) {
    const map = {
      neutral: { bg: 'var(--cv-track)',         fg: 'var(--cv-text)' },
      pos:     { bg: 'rgba(34,197,94,0.12)',     fg: 'var(--cv-pos)' },
      neg:     { bg: 'rgba(239,68,68,0.12)',     fg: 'var(--cv-neg)' },
      warn:    { bg: 'rgba(234,179,8,0.14)',     fg: 'var(--cv-warn)' },
      info:    { bg: 'rgba(59,130,246,0.12)',    fg: 'var(--cv-accent)' },
    };
    const s = map[tone] || map.neutral;
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center',
        padding: '3px 10px', borderRadius: 999, background: s.bg, color: s.fg,
        fontSize: 11, fontWeight: 600, letterSpacing: '0.02em',
      }}>{children}</span>
    );
  }

  function App() {
    const s = M.stats;

    return (
      <div style={{
        '--cv-bg':       '#fafafa',
        '--cv-surface':  '#ffffff',
        '--cv-border':   '#eef0f3',
        '--cv-track':    '#f1f3f6',
        '--cv-text':     '#0f172a',
        '--cv-muted':    '#64748b',
        '--cv-accent':   '#3b82f6',
        '--cv-pos':      '#16a34a',
        '--cv-neg':      '#ef4444',
        '--cv-warn':     '#ca8a04',
        '--cv-grid':     '#e5e7eb',
        background: 'var(--cv-bg)', color: 'var(--cv-text)',
        fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        fontSize: 14, width: '100%', height: '100%', overflow: 'auto',
      }}>
        {/* Top nav */}
        <header style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '18px 32px', borderBottom: '1px solid var(--cv-border)',
          background: 'var(--cv-surface)', position: 'sticky', top: 0, zIndex: 5,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 32 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{
                width: 28, height: 28, borderRadius: 8,
                background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
                display: 'grid', placeItems: 'center', color: 'white', fontWeight: 700, fontSize: 13,
              }}>K</div>
              <div style={{ fontWeight: 600, fontSize: 15 }}>Kalshi Weather</div>
            </div>
            <nav style={{ display: 'flex', gap: 4, fontSize: 13 }}>
              {['Overview', 'Positions', 'Signals', 'Forecast', 'Analytics', 'Risk'].map((n, i) => (
                <a key={n} href="#" style={{
                  padding: '8px 14px', borderRadius: 8,
                  color: i === 0 ? 'var(--cv-text)' : 'var(--cv-muted)',
                  background: i === 0 ? 'var(--cv-track)' : 'transparent',
                  fontWeight: i === 0 ? 600 : 500, textDecoration: 'none',
                }}>{n}</a>
              ))}
            </nav>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Pill tone="warn">Demo · Paper</Pill>
            <Pill tone="pos">● Live</Pill>
            <button style={{
              padding: '8px 14px', borderRadius: 8, border: '1px solid var(--cv-border)',
              background: 'var(--cv-surface)', color: 'var(--cv-text)', fontWeight: 500, fontSize: 13, cursor: 'pointer',
            }}>Kill switch</button>
          </div>
        </header>

        <main style={{ maxWidth: 1280, margin: '0 auto', padding: '32px' }}>
          {/* Hero / headline */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 24 }}>
            <div>
              <div style={{ color: 'var(--cv-muted)', fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
                Wednesday, May 6 · Good morning
              </div>
              <h1 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: '-0.02em' }}>
                Up <span style={{ color: 'var(--cv-pos)' }}>+$127.40</span> today
              </h1>
              <div style={{ color: 'var(--cv-muted)', fontSize: 14, marginTop: 4 }}>
                8 open positions · 7 new opportunities · 1 data source degraded
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button style={{
                padding: '10px 16px', borderRadius: 10, border: '1px solid var(--cv-border)',
                background: 'var(--cv-surface)', fontWeight: 500, cursor: 'pointer', fontSize: 13,
              }}>Run scan</button>
              <button style={{
                padding: '10px 16px', borderRadius: 10, border: 'none',
                background: 'var(--cv-accent)', color: 'white', fontWeight: 500, cursor: 'pointer', fontSize: 13,
              }}>New paper trade</button>
            </div>
          </div>

          {/* Stat cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
            <StatCard label="Paper balance" value={'$' + s.balance.toFixed(2)} delta={'+' + ((s.balance - s.starting_balance) / s.starting_balance * 100).toFixed(1) + '%'} sub={'from $' + s.starting_balance.toFixed(2) + ' start'} />
            <StatCard label="Open positions" value={s.open_count} sub={'$' + M.positions.reduce((a, p) => a + p.cost, 0).toFixed(2) + ' deployed'} />
            <StatCard label="Win rate" value={(s.win_rate * 100).toFixed(1) + '%'} delta="+2.3 pts" sub={s.settled_count + ' settled trades'} />
            <StatCard label="Brier score" value={s.brier.toFixed(3)} delta="−0.012" sub="lower is better · target ≤0.20" />
          </div>

          {/* Equity + graduation */}
          <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 16, marginBottom: 24 }}>
            <SectionCard
              title="Equity curve"
              action={
                <div style={{ display: 'flex', gap: 4 }}>
                  {['1M', '3M', '1Y', 'All'].map((r, i) => (
                    <button key={r} style={{
                      padding: '5px 12px', borderRadius: 6,
                      border: 'none', background: i === 1 ? 'var(--cv-track)' : 'transparent',
                      color: i === 1 ? 'var(--cv-text)' : 'var(--cv-muted)',
                      fontSize: 12, fontWeight: 500, cursor: 'pointer',
                    }}>{r}</button>
                  ))}
                </div>
              }>
              <AreaChart data={M.balanceHist} w={700} h={220} />
            </SectionCard>

            <SectionCard title="Graduation gate" action={<Pill tone="pos">Ready</Pill>}>
              <ProgressRow label="Settled trades" current={s.graduation.trades_done} target={s.graduation.trades_target} format={v => v} complete />
              <ProgressRow label="Net P&L" current={s.graduation.total_pnl} target={s.graduation.pnl_target} format={v => '$' + v.toFixed(0)} complete />
              <ProgressRow label="Brier score (inverse)" current={Math.max(0, 0.25 - s.graduation.brier)} target={0.05} format={v => (0.25 - v).toFixed(3)} complete />
              <div style={{
                marginTop: 16, padding: '12px 14px', borderRadius: 10,
                background: 'rgba(34,197,94,0.08)', color: 'var(--cv-pos)',
                fontSize: 13, fontWeight: 500,
              }}>
                ✓ All gates passed. Set <code style={{ background: 'rgba(0,0,0,0.06)', padding: '1px 5px', borderRadius: 4, fontSize: 12 }}>KALSHI_ENV=prod</code> to go live.
              </div>
            </SectionCard>
          </div>

          {/* Positions + Opportunities */}
          <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 16, marginBottom: 24 }}>
            <SectionCard title="Open positions" action={<a href="#" style={{ fontSize: 13, color: 'var(--cv-accent)', textDecoration: 'none', fontWeight: 500 }}>View all →</a>} padding={0}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ color: 'var(--cv-muted)', fontSize: 12 }}>
                    {['Market', 'Side', 'Cost', 'Edge', 'Expiry'].map((h, i) => (
                      <th key={h} style={{
                        padding: '10px 18px', textAlign: i === 0 ? 'left' : i < 4 ? 'right' : 'left',
                        fontWeight: 500, borderBottom: '1px solid var(--cv-border)',
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {M.positions.slice(0, 6).map((p, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--cv-border)' }}>
                      <td style={{ padding: '14px 18px' }}>
                        <div style={{ fontWeight: 500 }}>{p.city}</div>
                        <div style={{ fontSize: 11, color: 'var(--cv-muted)', fontFamily: 'ui-monospace, monospace', marginTop: 2 }}>
                          {p.ticker}
                        </div>
                      </td>
                      <td style={{ padding: '14px 18px', textAlign: 'right' }}>
                        <Pill tone={p.side === 'yes' ? 'pos' : 'neg'}>{p.side.toUpperCase()}</Pill>
                      </td>
                      <td style={{ padding: '14px 18px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                        ${p.cost.toFixed(2)}
                      </td>
                      <td style={{ padding: '14px 18px', textAlign: 'right', color: 'var(--cv-pos)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                        +{(p.edge * 100).toFixed(1)}%
                      </td>
                      <td style={{ padding: '14px 18px', color: 'var(--cv-muted)', fontVariantNumeric: 'tabular-nums' }}>
                        {p.expiry}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </SectionCard>

            <SectionCard title="Top opportunities" action={<Pill tone="info">Edge ≥ 7%</Pill>} padding={16}>
              {M.opportunities.slice(0, 5).map((o, i) => (
                <div key={i} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '12px 8px', borderBottom: i < 4 ? '1px solid var(--cv-border)' : 'none',
                }}>
                  <div>
                    <div style={{ fontWeight: 500 }}>{o.city}</div>
                    <div style={{ fontSize: 11, color: 'var(--cv-muted)', fontFamily: 'ui-monospace, monospace', marginTop: 2 }}>
                      {o.ticker.split('-').slice(0, 2).join('-')}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontWeight: 600, color: 'var(--cv-pos)', fontSize: 14 }}>
                      +{(o.edge * 100).toFixed(0)}%
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--cv-muted)', marginTop: 2 }}>
                      ask {o.yes_ask.toFixed(2)} · fcst {o.fcst.toFixed(2)}
                    </div>
                  </div>
                </div>
              ))}
            </SectionCard>
          </div>

          {/* Data sources + Model */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
            <SectionCard title="Data sources">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                {M.circuitBreakers.map((cb, i) => {
                  const open = cb.state === 'open';
                  return (
                    <div key={i} style={{
                      padding: '12px 14px', borderRadius: 10,
                      background: 'var(--cv-track)',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <span style={{
                          width: 8, height: 8, borderRadius: '50%',
                          background: open ? 'var(--cv-neg)' : 'var(--cv-pos)',
                        }} />
                        <span style={{ fontSize: 13, fontWeight: 500 }}>{cb.label}</span>
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--cv-muted)' }}>
                        {open ? `Retry in ${cb.retry_in_s}s` : `${cb.latency_ms}ms`}
                      </div>
                    </div>
                  );
                })}
              </div>
            </SectionCard>

            <SectionCard title="Model accuracy">
              {M.modelAccuracy.map((m, i) => (
                <div key={i} style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
                    <span style={{ fontWeight: 500 }}>{m.model}</span>
                    <span style={{ color: 'var(--cv-muted)', fontVariantNumeric: 'tabular-nums' }}>
                      Brier <strong style={{ color: 'var(--cv-text)' }}>{m.brier.toFixed(3)}</strong> · {(m.win_rate * 100).toFixed(0)}% · n={m.trades}
                    </span>
                  </div>
                  <div style={{ height: 4, background: 'var(--cv-track)', borderRadius: 6, overflow: 'hidden' }}>
                    <div style={{
                      width: ((0.25 - m.brier) / 0.25 * 100) + '%', height: '100%',
                      background: 'var(--cv-accent)',
                    }} />
                  </div>
                </div>
              ))}
            </SectionCard>
          </div>
        </main>
      </div>
    );
  }

  return { App };
})();
window.CalmVar = CalmVar;
