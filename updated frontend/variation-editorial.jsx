// Variation C — Editorial / data-journalism
// Charts as the hero. Serif headlines. Annotated. FT/Pudding vibes.

const EditVar = (function () {
  const M = window.MOCK;

  function HeroChart({ data, w = 900, h = 320 }) {
    if (!data || !data.length) return null;
    const xs = data.map(d => d.t);
    const ys = data.map(d => d.v);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = 980, maxY = Math.max(...ys) * 1.02;
    const sx = x => ((x - minX) / Math.max(1, maxX - minX)) * (w - 80) + 40;
    const sy = y => h - 50 - ((y - minY) / Math.max(0.0001, maxY - minY)) * (h - 80);
    const pts = data.map(d => `${sx(d.t).toFixed(1)},${sy(d.v).toFixed(1)}`).join(' ');
    const fillPts = `${sx(data[0].t)},${h - 50} ${pts} ${sx(data[data.length - 1].t)},${h - 50}`;
    const last = data[data.length - 1];
    const peakIdx = ys.indexOf(Math.max(...ys));
    const peak = data[peakIdx];

    return (
      <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
        {/* Grid + y-axis labels */}
        {[1000, 1100, 1200, 1300].map((v, i) => (
          <g key={v}>
            <line x1="40" y1={sy(v)} x2={w - 20} y2={sy(v)} stroke="var(--ed-rule)" strokeWidth="0.5" />
            <text x="36" y={sy(v) + 3} fontSize="11" fill="var(--ed-muted)" textAnchor="end" fontFamily="var(--ed-mono)">${v}</text>
          </g>
        ))}
        {/* Starting line annotation */}
        <line x1="40" y1={sy(1000)} x2={w - 20} y2={sy(1000)} stroke="var(--ed-rule-strong)" strokeDasharray="3 3" />
        <text x={w - 24} y={sy(1000) - 6} fontSize="10" fill="var(--ed-muted)" textAnchor="end" fontStyle="italic">Starting balance</text>

        <polyline points={fillPts} fill="var(--ed-accent)" fillOpacity="0.10" stroke="none" />
        <polyline points={pts} fill="none" stroke="var(--ed-accent)" strokeWidth="2.2" strokeLinejoin="round" />

        {/* Peak annotation */}
        <circle cx={sx(peak.t)} cy={sy(peak.v)} r="4" fill="var(--ed-accent)" />
        <line x1={sx(peak.t)} y1={sy(peak.v) - 8} x2={sx(peak.t)} y2={sy(peak.v) - 32} stroke="var(--ed-text)" strokeWidth="0.6" />
        <text x={sx(peak.t)} y={sy(peak.v) - 38} fontSize="11" fill="var(--ed-text)" textAnchor="middle">Peak ${peak.v.toFixed(0)}</text>

        {/* Final marker */}
        <circle cx={sx(last.t)} cy={sy(last.v)} r="5" fill="var(--ed-accent)" stroke="var(--ed-bg)" strokeWidth="2" />
        <text x={sx(last.t) - 8} y={sy(last.v) + 4} fontSize="13" fill="var(--ed-text)" textAnchor="end" fontWeight="600" fontFamily="var(--ed-mono)">${last.v.toFixed(2)}</text>
      </svg>
    );
  }

  function CalibrationChart({ data, w = 360, h = 320 }) {
    return (
      <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
        {[0, 0.25, 0.5, 0.75, 1].map(t => (
          <g key={t}>
            <line x1={40 + t * (w - 70)} y1="20" x2={40 + t * (w - 70)} y2={h - 40} stroke="var(--ed-rule)" strokeWidth="0.5" />
            <text x={40 + t * (w - 70)} y={h - 22} fontSize="10" fill="var(--ed-muted)" textAnchor="middle" fontFamily="var(--ed-mono)">{t.toFixed(2)}</text>
            <line x1="40" y1={20 + (1 - t) * (h - 60)} x2={w - 30} y2={20 + (1 - t) * (h - 60)} stroke="var(--ed-rule)" strokeWidth="0.5" />
            <text x="36" y={24 + (1 - t) * (h - 60)} fontSize="10" fill="var(--ed-muted)" textAnchor="end" fontFamily="var(--ed-mono)">{t.toFixed(2)}</text>
          </g>
        ))}
        <line x1="40" y1={h - 40} x2={w - 30} y2="20" stroke="var(--ed-muted)" strokeWidth="1" strokeDasharray="3 3" />
        <text x={w - 50} y="34" fontSize="10" fontStyle="italic" fill="var(--ed-muted)" textAnchor="end">perfect</text>

        <polyline
          points={data.map(c => `${40 + c.bucket * (w - 70)},${20 + (1 - c.realized) * (h - 60)}`).join(' ')}
          fill="none" stroke="var(--ed-accent)" strokeWidth="2" />
        {data.map((c, i) => (
          <circle key={i} cx={40 + c.bucket * (w - 70)} cy={20 + (1 - c.realized) * (h - 60)}
            r={Math.sqrt(c.n) / 1.5} fill="var(--ed-accent)" fillOpacity="0.3" stroke="var(--ed-accent)" strokeWidth="1.5" />
        ))}
        <text x={w / 2} y={h - 4} fontSize="11" fill="var(--ed-muted)" textAnchor="middle">Forecast probability</text>
        <text x="14" y={h / 2} fontSize="11" fill="var(--ed-muted)" textAnchor="middle" transform={`rotate(-90 14 ${h / 2})`}>Realized rate</text>
      </svg>
    );
  }

  function ModelBars({ data }) {
    const max = Math.max(...data.map(m => m.edge_realized));
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {data.map((m, i) => (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '60px 1fr 80px', alignItems: 'center', gap: 12 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>{m.model}</div>
            <div style={{ position: 'relative', height: 22, background: 'var(--ed-rule)' }}>
              <div style={{
                position: 'absolute', inset: 0, width: (m.edge_realized / max * 100) + '%',
                background: 'var(--ed-accent)',
              }} />
              <span style={{
                position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)',
                fontSize: 11, color: 'var(--ed-text)', fontFamily: 'var(--ed-mono)',
              }}>+{(m.edge_realized * 100).toFixed(1)}% realized edge</span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--ed-muted)', textAlign: 'right', fontFamily: 'var(--ed-mono)' }}>
              n={m.trades}
            </div>
          </div>
        ))}
      </div>
    );
  }

  function PnlBars({ data }) {
    const all = data.map(d => d.pnl);
    const min = Math.min(...all), max = Math.max(...all);
    const range = Math.max(Math.abs(min), Math.abs(max));
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {data.map((d, i) => {
          const pos = d.pnl >= 0;
          const w = (Math.abs(d.pnl) / range) * 50;
          return (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '160px 1fr 70px', alignItems: 'center', gap: 12, fontSize: 13 }}>
              <span style={{ color: 'var(--ed-text)' }}>{d.source}</span>
              <div style={{ position: 'relative', height: 14, display: 'flex' }}>
                <div style={{ width: '50%', display: 'flex', justifyContent: 'flex-end' }}>
                  {!pos && <div style={{ width: w + '%', background: 'var(--ed-neg)', height: '100%' }} />}
                </div>
                <div style={{ width: 1, background: 'var(--ed-rule-strong)' }} />
                <div style={{ width: '50%' }}>
                  {pos && <div style={{ width: w + '%', background: 'var(--ed-pos)', height: '100%' }} />}
                </div>
              </div>
              <span style={{
                fontFamily: 'var(--ed-mono)', textAlign: 'right',
                color: pos ? 'var(--ed-pos)' : 'var(--ed-neg)', fontWeight: 600,
              }}>{pos ? '+' : ''}${d.pnl.toFixed(2)}</span>
            </div>
          );
        })}
      </div>
    );
  }

  function App() {
    const s = M.stats;

    return (
      <div style={{
        '--ed-bg':           '#f5f1e8',
        '--ed-surface':      '#fdfaf2',
        '--ed-text':         '#1a1814',
        '--ed-muted':        '#6b6356',
        '--ed-rule':         '#dcd4c2',
        '--ed-rule-strong':  '#1a1814',
        '--ed-accent':       '#b03a2e',
        '--ed-pos':          '#2d6a4f',
        '--ed-neg':          '#9d2226',
        '--ed-mono':         "'JetBrains Mono', 'IBM Plex Mono', ui-monospace, monospace",
        background: 'var(--ed-bg)', color: 'var(--ed-text)',
        fontFamily: "'Source Serif 4', 'Source Serif Pro', Georgia, serif",
        fontSize: 15, lineHeight: 1.55,
        width: '100%', height: '100%', overflow: 'auto',
      }}>
        {/* Masthead */}
        <header style={{ borderBottom: '2px solid var(--ed-rule-strong)', padding: '20px 0' }}>
          <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 32px', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <div style={{ fontFamily: 'var(--ed-mono)', fontSize: 11, letterSpacing: '0.2em', textTransform: 'uppercase', color: 'var(--ed-muted)' }}>
              Vol. I · No. 187 · Wednesday, May 6, 2026
            </div>
            <div style={{ fontFamily: 'var(--ed-mono)', fontSize: 11, letterSpacing: '0.2em', textTransform: 'uppercase' }}>
              The Kalshi Weather Ledger
            </div>
            <div style={{ fontFamily: 'var(--ed-mono)', fontSize: 11, color: 'var(--ed-muted)' }}>
              Demo · Paper trading
            </div>
          </div>
        </header>

        <main style={{ maxWidth: 1100, margin: '0 auto', padding: '40px 32px 60px' }}>
          {/* Headline */}
          <div style={{ borderBottom: '1px solid var(--ed-rule)', paddingBottom: 32, marginBottom: 36 }}>
            <div style={{
              fontFamily: 'var(--ed-mono)', fontSize: 11, letterSpacing: '0.2em', textTransform: 'uppercase',
              color: 'var(--ed-accent)', marginBottom: 14,
            }}>
              Today's report — operating in greed
            </div>
            <h1 style={{
              margin: 0, fontSize: 56, lineHeight: 1.05, fontWeight: 600, letterSpacing: '-0.02em',
              maxWidth: 920,
            }}>
              Eight open positions, betting on a hot week — and the bot is up <span style={{ color: 'var(--ed-pos)' }}>$247.83</span>.
            </h1>
            <p style={{
              fontSize: 19, lineHeight: 1.5, marginTop: 24, color: 'var(--ed-muted)',
              maxWidth: 760, fontStyle: 'italic',
            }}>
              The graduation gate cleared overnight on the 567th settled trade. Brier score of 0.151 — well below the 0.20 ceiling. Pirate Weather is offline; the ensemble is running on three sources.
            </p>

            {/* Big numbers row */}
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 32,
              marginTop: 36, paddingTop: 24, borderTop: '1px solid var(--ed-rule)',
            }}>
              {[
                { label: 'Paper balance', value: '$' + s.balance.toFixed(2), sub: '+24.8% from $1,000', tone: 'pos' },
                { label: 'Today', value: '+$' + s.today_pnl.toFixed(2), sub: '8 open · 3 settled', tone: 'pos' },
                { label: 'Win rate', value: (s.win_rate * 100).toFixed(1) + '%', sub: 'on ' + s.settled_count + ' trades', tone: null },
                { label: 'Brier score', value: s.brier.toFixed(3), sub: 'random = 0.250', tone: 'pos' },
              ].map((stat, i) => (
                <div key={i}>
                  <div style={{
                    fontFamily: 'var(--ed-mono)', fontSize: 10, letterSpacing: '0.18em',
                    textTransform: 'uppercase', color: 'var(--ed-muted)', marginBottom: 6,
                  }}>{stat.label}</div>
                  <div style={{
                    fontSize: 38, fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1,
                    color: stat.tone === 'pos' ? 'var(--ed-pos)' : 'var(--ed-text)',
                  }}>{stat.value}</div>
                  <div style={{ fontSize: 12, color: 'var(--ed-muted)', marginTop: 8 }}>{stat.sub}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Hero chart */}
          <section style={{ marginBottom: 48 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
              <h2 style={{ margin: 0, fontSize: 24, fontWeight: 600, letterSpacing: '-0.01em' }}>
                The equity curve, ninety days running
              </h2>
              <div style={{ fontFamily: 'var(--ed-mono)', fontSize: 11, color: 'var(--ed-muted)' }}>
                Source: paper.db · daily settlement
              </div>
            </div>
            <p style={{ color: 'var(--ed-muted)', marginTop: 4, marginBottom: 24, maxWidth: 760, fontSize: 14 }}>
              The bot started with a virtual $1,000 on Feb 5. After the calibration drawdown in mid-March, Kelly sizing recovered the curve and never looked back.
            </p>
            <HeroChart data={M.balanceHist} />
          </section>

          {/* Two-column: Calibration + P&L attribution */}
          <section style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 40,
            paddingTop: 32, borderTop: '1px solid var(--ed-rule)', marginBottom: 48,
          }}>
            <div>
              <h3 style={{ margin: 0, fontSize: 19, fontWeight: 600 }}>Is it well-calibrated?</h3>
              <p style={{ color: 'var(--ed-muted)', marginTop: 6, marginBottom: 16, fontSize: 14, lineHeight: 1.5 }}>
                When the bot says 70%, does it actually win 70% of the time? Each dot is a probability bucket; size is sample count. Closer to the diagonal is better.
              </p>
              <CalibrationChart data={M.calibration} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: 19, fontWeight: 600 }}>Where the P&amp;L came from</h3>
              <p style={{ color: 'var(--ed-muted)', marginTop: 6, marginBottom: 24, fontSize: 14, lineHeight: 1.5 }}>
                Decomposing the $557 of gross P&L since inception by signal source. Fees and slippage take the largest bite back.
              </p>
              <PnlBars data={M.pnlAttribution} />
              <div style={{
                marginTop: 20, paddingTop: 12, borderTop: '1px solid var(--ed-rule)',
                fontFamily: 'var(--ed-mono)', fontSize: 12, display: 'flex', justifyContent: 'space-between',
              }}>
                <span style={{ color: 'var(--ed-muted)' }}>Net</span>
                <span style={{ color: 'var(--ed-pos)', fontWeight: 600 }}>+$557.30</span>
              </div>
            </div>
          </section>

          {/* Model accuracy */}
          <section style={{ paddingTop: 32, borderTop: '1px solid var(--ed-rule)', marginBottom: 48 }}>
            <h3 style={{ margin: 0, fontSize: 19, fontWeight: 600 }}>Five forecast sources, ranked by realized edge</h3>
            <p style={{ color: 'var(--ed-muted)', marginTop: 6, marginBottom: 24, fontSize: 14 }}>
              National Blend (NBM) wins again. The ensemble — weighted average of all four — is what the bot actually trades.
            </p>
            <div style={{ maxWidth: 720 }}>
              <ModelBars data={M.modelAccuracy} />
            </div>
          </section>

          {/* Open positions table */}
          <section style={{ paddingTop: 32, borderTop: '1px solid var(--ed-rule)', marginBottom: 48 }}>
            <h3 style={{ margin: 0, fontSize: 19, fontWeight: 600 }}>Eight bets currently in the book</h3>
            <p style={{ color: 'var(--ed-muted)', marginTop: 6, marginBottom: 24, fontSize: 14 }}>
              Mostly highs across the south and the coasts. Every position closes within the week.
            </p>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--ed-rule-strong)' }}>
                  {['City', 'Market', 'Side', 'Cost', 'Edge', 'Model', 'Closes'].map((h, i) => (
                    <th key={h} style={{
                      padding: '10px 12px', textAlign: i >= 3 && i <= 4 ? 'right' : 'left',
                      fontFamily: 'var(--ed-mono)', fontSize: 10, letterSpacing: '0.15em',
                      textTransform: 'uppercase', fontWeight: 500, color: 'var(--ed-muted)',
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {M.positions.map((p, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--ed-rule)' }}>
                    <td style={{ padding: '12px', fontWeight: 600 }}>{p.city}</td>
                    <td style={{ padding: '12px', fontFamily: 'var(--ed-mono)', fontSize: 12, color: 'var(--ed-muted)' }}>
                      {p.ticker}
                    </td>
                    <td style={{ padding: '12px' }}>
                      <span style={{
                        fontFamily: 'var(--ed-mono)', fontSize: 11, letterSpacing: '0.1em', fontWeight: 600,
                        color: p.side === 'yes' ? 'var(--ed-pos)' : 'var(--ed-neg)',
                      }}>{p.side === 'yes' ? '↑ YES' : '↓ NO'}</span>
                    </td>
                    <td style={{ padding: '12px', textAlign: 'right', fontFamily: 'var(--ed-mono)', fontVariantNumeric: 'tabular-nums' }}>
                      ${p.cost.toFixed(2)}
                    </td>
                    <td style={{ padding: '12px', textAlign: 'right', color: 'var(--ed-pos)', fontWeight: 600, fontFamily: 'var(--ed-mono)' }}>
                      +{(p.edge * 100).toFixed(1)}%
                    </td>
                    <td style={{ padding: '12px', fontFamily: 'var(--ed-mono)', fontSize: 12 }}>{p.model}</td>
                    <td style={{ padding: '12px', color: 'var(--ed-muted)', fontFamily: 'var(--ed-mono)', fontSize: 12 }}>
                      {p.expiry}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {/* Footer notes */}
          <footer style={{
            paddingTop: 32, borderTop: '2px solid var(--ed-rule-strong)',
            display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 32,
          }}>
            <div>
              <div style={{
                fontFamily: 'var(--ed-mono)', fontSize: 10, letterSpacing: '0.18em',
                textTransform: 'uppercase', color: 'var(--ed-muted)', marginBottom: 8,
              }}>Today's dispatch</div>
              {M.alerts.slice(0, 3).map((a, i) => (
                <p key={i} style={{ margin: '6px 0', fontSize: 13, color: 'var(--ed-text)' }}>
                  <span style={{ fontFamily: 'var(--ed-mono)', color: 'var(--ed-muted)', marginRight: 10 }}>{a.ts}</span>
                  {a.text}
                </p>
              ))}
            </div>
            <div style={{ textAlign: 'right', fontFamily: 'var(--ed-mono)', fontSize: 11, color: 'var(--ed-muted)' }}>
              <div>Auto-refresh in 4:23</div>
              <div style={{ marginTop: 4 }}>Last cron: 02:48 ago</div>
              <div style={{ marginTop: 4 }}>Backup: OneDrive ✓</div>
            </div>
          </footer>
        </main>
      </div>
    );
  }

  return { App };
})();
window.EditVar = EditVar;
