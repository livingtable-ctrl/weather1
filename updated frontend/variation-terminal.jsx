// Variation A — Terminal / Bloomberg-density
// Mono, tight, high info-density, dark-by-default, accent green.

const TermVar = (function () {
  const M = window.MOCK;

  function Sparkline({ data, w = 120, h = 28, color = 'currentColor', fill = false }) {
    if (!data || !data.length) return null;
    const xs = data.map(d => d.t || d.bucket || 0);
    const ys = data.map(d => d.v ?? d.realized ?? 0);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const sx = x => ((x - minX) / Math.max(1, maxX - minX)) * w;
    const sy = y => h - ((y - minY) / Math.max(0.0001, maxY - minY)) * h;
    const pts = data.map(d => `${sx(d.t || d.bucket).toFixed(1)},${sy(d.v ?? d.realized).toFixed(1)}`).join(' ');
    const fillPts = `0,${h} ${pts} ${w},${h}`;
    return (
      <svg width={w} height={h} style={{ display: 'block' }}>
        {fill && <polyline points={fillPts} fill={color} fillOpacity="0.12" stroke="none" />}
        <polyline points={pts} fill="none" stroke={color} strokeWidth="1.25" />
      </svg>
    );
  }

  function Bar({ pct, color = 'var(--tv-accent)', bg = 'var(--tv-line)' }) {
    return (
      <div style={{ background: bg, height: 4, borderRadius: 0, overflow: 'hidden', width: '100%' }}>
        <div style={{ width: Math.min(100, Math.max(0, pct)) + '%', height: '100%', background: color }} />
      </div>
    );
  }

  function Cell({ children, mono = true, dim = false, pos = false, neg = false, w, align = 'left', style = {} }) {
    const c = pos ? 'var(--tv-pos)' : neg ? 'var(--tv-neg)' : dim ? 'var(--tv-muted)' : 'var(--tv-text)';
    return (
      <td style={{
        padding: '3px 10px', color: c, fontFamily: mono ? 'var(--tv-mono)' : 'inherit',
        textAlign: align, width: w, whiteSpace: 'nowrap', borderBottom: '1px solid var(--tv-line)',
        ...style,
      }}>{children}</td>
    );
  }

  function Header({ children, w, align = 'left' }) {
    return (
      <th style={{
        padding: '4px 10px', textAlign: align, width: w, fontWeight: 500,
        color: 'var(--tv-muted)', fontSize: 10, letterSpacing: '0.08em',
        textTransform: 'uppercase', borderBottom: '1px solid var(--tv-line2)',
        background: 'var(--tv-bg2)',
      }}>{children}</th>
    );
  }

  function Panel({ title, right, children, style = {} }) {
    return (
      <section style={{ border: '1px solid var(--tv-line2)', background: 'var(--tv-bg2)', ...style }}>
        <header style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '6px 10px', borderBottom: '1px solid var(--tv-line2)',
          fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase',
          color: 'var(--tv-muted)',
        }}>
          <span>{title}</span>
          <span style={{ display: 'flex', gap: 8 }}>{right}</span>
        </header>
        <div>{children}</div>
      </section>
    );
  }

  function Pill({ children, tone = 'neutral' }) {
    const map = {
      neutral: { bg: 'rgba(255,255,255,0.04)', fg: 'var(--tv-text)' },
      pos:     { bg: 'rgba(0,200,150,0.10)',   fg: 'var(--tv-pos)' },
      neg:     { bg: 'rgba(255,80,90,0.10)',   fg: 'var(--tv-neg)' },
      warn:    { bg: 'rgba(255,180,60,0.10)',  fg: 'var(--tv-warn)' },
      strong:  { bg: 'rgba(0,200,150,0.16)',   fg: 'var(--tv-pos)' },
    };
    const s = map[tone] || map.neutral;
    return (
      <span style={{
        display: 'inline-block', padding: '1px 6px', background: s.bg, color: s.fg,
        fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase',
        border: `1px solid ${s.fg}33`,
      }}>{children}</span>
    );
  }

  function StatCell({ label, value, sub, tone, w, sparkData, sparkColor }) {
    const c = tone === 'pos' ? 'var(--tv-pos)' : tone === 'neg' ? 'var(--tv-neg)' : 'var(--tv-text)';
    return (
      <div style={{
        flex: w ? `0 0 ${w}` : 1, padding: '10px 14px',
        borderRight: '1px solid var(--tv-line2)', minWidth: 0,
      }}>
        <div style={{
          fontSize: 9, letterSpacing: '0.1em', textTransform: 'uppercase',
          color: 'var(--tv-muted)', marginBottom: 4,
        }}>{label}</div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <div style={{ fontFamily: 'var(--tv-mono)', fontSize: 18, fontWeight: 500, color: c, lineHeight: 1 }}>
            {value}
          </div>
          {sub && (
            <div style={{ fontFamily: 'var(--tv-mono)', fontSize: 11, color: 'var(--tv-muted)' }}>
              {sub}
            </div>
          )}
        </div>
        {sparkData && (
          <div style={{ marginTop: 6, color: sparkColor || 'var(--tv-accent)' }}>
            <Sparkline data={sparkData} w={140} h={22} fill />
          </div>
        )}
      </div>
    );
  }

  function App({ density = 'compact' }) {
    const s = M.stats;
    const rowH = density === 'compact' ? 22 : 28;

    return (
      <div style={{
        '--tv-bg': '#0a0d0f',
        '--tv-bg2': '#10141a',
        '--tv-line': '#1a2128',
        '--tv-line2': '#222a33',
        '--tv-text': '#d6deea',
        '--tv-muted': '#5e6e7e',
        '--tv-accent': '#7adcc4',
        '--tv-pos': '#00c896',
        '--tv-neg': '#ff5060',
        '--tv-warn': '#ffb43c',
        '--tv-mono': "'JetBrains Mono', 'IBM Plex Mono', Consolas, monospace",
        background: 'var(--tv-bg)', color: 'var(--tv-text)', fontFamily: 'var(--tv-mono)',
        fontSize: 12, width: '100%', height: '100%', overflow: 'auto',
      }}>
        {/* Top bar */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 14px', borderBottom: '1px solid var(--tv-line2)',
          background: 'var(--tv-bg2)', position: 'sticky', top: 0, zIndex: 5,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ width: 8, height: 8, background: 'var(--tv-pos)', boxShadow: '0 0 6px var(--tv-pos)' }} />
              <div style={{ fontSize: 11, letterSpacing: '0.18em' }}>KALSHI/WX/BOT · v1.0</div>
            </div>
            <div style={{ display: 'flex', gap: 14, fontSize: 10, color: 'var(--tv-muted)', letterSpacing: '0.08em' }}>
              <span>ENV: <span style={{ color: 'var(--tv-warn)' }}>DEMO</span></span>
              <span>STRAT: <span style={{ color: 'var(--tv-text)' }}>KELLY/2</span></span>
              <span>UPTIME: 12d 04h</span>
              <span>SCAN: 5m</span>
              <span>NEXT: 02:14</span>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6, fontSize: 10 }}>
            <Pill tone="pos">LIVE</Pill>
            <Pill tone="neutral">GRAD ✓</Pill>
            <Pill tone="warn">1 CB OPEN</Pill>
          </div>
        </div>

        {/* Stat strip */}
        <div style={{
          display: 'flex', borderBottom: '1px solid var(--tv-line2)',
          background: 'var(--tv-bg2)',
        }}>
          <StatCell label="Paper Bal." value={'$' + s.balance.toFixed(2)} sub={`+${((s.balance - s.starting_balance) / s.starting_balance * 100).toFixed(1)}%`} tone="pos" sparkData={M.balanceHist} sparkColor="var(--tv-pos)" />
          <StatCell label="Today P&L" value={(s.today_pnl >= 0 ? '+' : '') + '$' + s.today_pnl.toFixed(2)} sub="8 open · 3 settled" tone="pos" />
          <StatCell label="Open Pos." value={s.open_count} sub={`/${20} max`} />
          <StatCell label="Win Rate" value={(s.win_rate * 100).toFixed(1) + '%'} sub={`n=${s.settled_count}`} tone="pos" />
          <StatCell label="Brier" value={s.brier.toFixed(4)} sub="↓ better" tone="pos" sparkData={M.brierHist} sparkColor="var(--tv-warn)" />
          <StatCell label="Day Spend" value={'$' + s.daily_spend.toFixed(0)} sub={`/$${s.max_daily_spend}`} />
          <StatCell label="Fear/Greed" value={s.fear_greed} sub={s.fear_greed_label} tone="pos" />
        </div>

        {/* Main grid */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1.6fr 1fr 1fr',
          gridTemplateRows: 'auto auto auto',
          gap: 1, background: 'var(--tv-line2)', padding: 1,
        }}>
          {/* Open Positions */}
          <Panel title="Open Positions · 8" right={<><Pill tone="neutral">SORT: EDGE</Pill></>} style={{ gridColumn: '1 / 2' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
              <thead>
                <tr>
                  <Header>Ticker</Header>
                  <Header>City</Header>
                  <Header align="center" w={50}>Side</Header>
                  <Header align="right" w={60}>Cost</Header>
                  <Header align="right" w={60}>Mark</Header>
                  <Header align="right" w={60}>Fcst</Header>
                  <Header align="right" w={60}>Edge</Header>
                  <Header align="center" w={60}>Model</Header>
                  <Header align="right" w={60}>Age</Header>
                </tr>
              </thead>
              <tbody>
                {M.positions.map((p, i) => (
                  <tr key={i} style={{ height: rowH }}>
                    <Cell><span style={{ color: 'var(--tv-accent)' }}>{p.ticker}</span></Cell>
                    <Cell dim>{p.city}</Cell>
                    <Cell align="center">
                      <Pill tone={p.side === 'yes' ? 'pos' : 'neg'}>{p.side.toUpperCase()}</Pill>
                    </Cell>
                    <Cell align="right">${p.cost.toFixed(2)}</Cell>
                    <Cell align="right" dim>{p.mark.toFixed(2)}</Cell>
                    <Cell align="right">{p.fcst.toFixed(2)}</Cell>
                    <Cell align="right" pos>+{(p.edge * 100).toFixed(1)}%</Cell>
                    <Cell align="center" dim>{p.model}</Cell>
                    <Cell align="right" dim>{p.age_h}h</Cell>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          {/* Top Opportunities */}
          <Panel title="Top Opportunities · 7" right={<Pill tone="neutral">EDGE ≥ 7%</Pill>} style={{ gridColumn: '2 / 3' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
              <thead>
                <tr>
                  <Header>Ticker</Header>
                  <Header align="right" w={50}>Ask</Header>
                  <Header align="right" w={50}>Fcst</Header>
                  <Header align="right" w={60}>Edge</Header>
                  <Header align="center" w={60}>Tier</Header>
                </tr>
              </thead>
              <tbody>
                {M.opportunities.map((o, i) => (
                  <tr key={i} style={{ height: rowH }}>
                    <Cell><span style={{ color: 'var(--tv-accent)' }}>{o.ticker.split('-')[0].replace('KX', '')}</span><div style={{ fontSize: 10, color: 'var(--tv-muted)' }}>{o.city}</div></Cell>
                    <Cell align="right">{o.yes_ask.toFixed(2)}</Cell>
                    <Cell align="right">{o.fcst.toFixed(2)}</Cell>
                    <Cell align="right" pos>+{(o.edge * 100).toFixed(0)}%</Cell>
                    <Cell align="center">
                      <Pill tone={o.tier === 'STRONG' ? 'strong' : o.tier === 'MED' ? 'pos' : 'neutral'}>{o.tier}</Pill>
                    </Cell>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          {/* Alerts ticker */}
          <Panel title="Alerts" right={<Pill tone="warn">5</Pill>} style={{ gridColumn: '3 / 4' }}>
            <div>
              {M.alerts.map((a, i) => (
                <div key={i} style={{
                  display: 'grid', gridTemplateColumns: '46px 50px 1fr', gap: 8,
                  padding: '6px 10px', borderBottom: '1px solid var(--tv-line)',
                  fontSize: 11, alignItems: 'flex-start',
                }}>
                  <span style={{ color: 'var(--tv-muted)' }}>{a.ts}</span>
                  <Pill tone={a.level === 'warn' ? 'warn' : a.level === 'good' ? 'pos' : 'neutral'}>
                    {a.level.toUpperCase()}
                  </Pill>
                  <span>{a.text}</span>
                </div>
              ))}
            </div>
          </Panel>

          {/* Balance chart */}
          <Panel title="Equity Curve · 90d" right={<><Pill tone="neutral">90D</Pill><Pill tone="neutral">1Y</Pill><Pill tone="neutral">ALL</Pill></>} style={{ gridColumn: '1 / 3' }}>
            <div style={{ padding: 12, color: 'var(--tv-pos)' }}>
              <Sparkline data={M.balanceHist} w={780} h={140} fill />
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--tv-muted)', marginTop: 6 }}>
                <span>$1,000.00 · 90d ago</span>
                <span>peak ${Math.max(...M.balanceHist.map(d => d.v)).toFixed(2)}</span>
                <span>${s.balance.toFixed(2)} · now</span>
              </div>
            </div>
          </Panel>

          {/* Model accuracy */}
          <Panel title="Model Accuracy" style={{ gridColumn: '3 / 4' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
              <thead>
                <tr>
                  <Header>Model</Header>
                  <Header align="right">N</Header>
                  <Header align="right">Brier</Header>
                  <Header align="right">Win%</Header>
                </tr>
              </thead>
              <tbody>
                {M.modelAccuracy.map((m, i) => (
                  <tr key={i} style={{ height: rowH }}>
                    <Cell><span style={{ color: 'var(--tv-accent)' }}>{m.model}</span></Cell>
                    <Cell align="right" dim>{m.trades}</Cell>
                    <Cell align="right" pos={m.brier < 0.16}>{m.brier.toFixed(3)}</Cell>
                    <Cell align="right">{(m.win_rate * 100).toFixed(0)}%</Cell>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          {/* Data sources / circuit breakers */}
          <Panel title="Data Sources · Circuit Breakers" style={{ gridColumn: '1 / 3' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1, background: 'var(--tv-line)' }}>
              {M.circuitBreakers.map((cb, i) => {
                const open = cb.state === 'open';
                return (
                  <div key={i} style={{
                    background: 'var(--tv-bg2)', padding: '8px 12px',
                    borderLeft: `2px solid ${open ? 'var(--tv-neg)' : 'var(--tv-pos)'}`,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                      <span>{cb.label}</span>
                      <span style={{ color: open ? 'var(--tv-neg)' : 'var(--tv-pos)' }}>
                        {open ? 'OPEN' : 'OK'}
                      </span>
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--tv-muted)', marginTop: 2 }}>
                      {open
                        ? `${cb.failures} failures · retry ${cb.retry_in_s}s`
                        : `${cb.latency_ms}ms · ${cb.failures} fails`}
                    </div>
                  </div>
                );
              })}
            </div>
          </Panel>

          {/* Calibration */}
          <Panel title="Calibration · Brier 0.151" style={{ gridColumn: '3 / 4' }}>
            <div style={{ padding: 12 }}>
              <svg width="100%" viewBox="0 0 200 140" style={{ display: 'block' }}>
                <line x1="20" y1="120" x2="190" y2="120" stroke="var(--tv-line2)" />
                <line x1="20" y1="20" x2="20" y2="120" stroke="var(--tv-line2)" />
                <line x1="20" y1="120" x2="190" y2="20" stroke="var(--tv-muted)" strokeDasharray="2 2" strokeWidth="0.6" />
                {M.calibration.map((c, i) => {
                  const x = 20 + c.bucket * 170;
                  const y = 120 - c.realized * 100;
                  return <circle key={i} cx={x} cy={y} r={Math.sqrt(c.n) / 2} fill="var(--tv-accent)" fillOpacity="0.85" />;
                })}
                <polyline
                  points={M.calibration.map(c => `${20 + c.bucket * 170},${120 - c.realized * 100}`).join(' ')}
                  fill="none" stroke="var(--tv-accent)" strokeWidth="1"
                />
                <text x="20" y="135" fontSize="8" fill="var(--tv-muted)">0.0</text>
                <text x="180" y="135" fontSize="8" fill="var(--tv-muted)">1.0 fcst</text>
              </svg>
              <div style={{ fontSize: 10, color: 'var(--tv-muted)', marginTop: 4 }}>
                567 settled · 9 buckets · diagonal = perfect
              </div>
            </div>
          </Panel>
        </div>

        {/* Footer command bar */}
        <div style={{
          padding: '6px 14px', fontSize: 10, color: 'var(--tv-muted)',
          borderTop: '1px solid var(--tv-line2)', background: 'var(--tv-bg2)',
          display: 'flex', justifyContent: 'space-between',
        }}>
          <span>F1 SCAN · F2 POS · F3 ANALYZE · F4 KILL · F5 RESUME · F6 EXPORT</span>
          <span>last cron 02:48 ago · next 02:12 · disk 1.4MB · cloud ✓</span>
        </div>
      </div>
    );
  }

  return { App };
})();
window.TermVar = TermVar;
