// Variation D — Hybrid: Calm structure + Editorial charts
// Takes B's clean layout and C's data-journalism visual language.

const HybridVar = (function () {
  const M = window.MOCK;

  function HeroEquityChart({ data, w = 880, h = 280 }) {
    if (!data || !data.length) return null;
    const xs = data.map(d => d.t);
    const ys = data.map(d => d.v);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = 980, maxY = Math.max(...ys) * 1.015;
    const sx = x => ((x - minX) / Math.max(1, maxX - minX)) * (w - 70) + 50;
    const sy = y => h - 40 - ((y - minY) / Math.max(0.0001, maxY - minY)) * (h - 70);
    const pts = data.map(d => `${sx(d.t).toFixed(1)},${sy(d.v).toFixed(1)}`).join(' ');
    const fillPts = `${sx(data[0].t)},${h - 40} ${pts} ${sx(data[data.length - 1].t)},${h - 40}`;
    const last = data[data.length - 1];
    const peakIdx = ys.indexOf(Math.max(...ys));
    const peak = data[peakIdx];

    return (
      <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
        <defs>
          <linearGradient id="hyb-grad" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.20" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[1000, 1100, 1200, 1300].map((v, i) => (
          <g key={v}>
            <line x1="50" y1={sy(v)} x2={w - 20} y2={sy(v)} stroke="#e5e7eb" strokeWidth="1" />
            <text x="46" y={sy(v) + 3} fontSize="11" fill="#94a3b8" textAnchor="end" fontFamily="ui-monospace, monospace">${v}</text>
          </g>
        ))}
        <line x1="50" y1={sy(1000)} x2={w - 20} y2={sy(1000)} stroke="#94a3b8" strokeDasharray="3 3" strokeWidth="1" />
        <text x={w - 24} y={sy(1000) - 8} fontSize="11" fill="#64748b" textAnchor="end" fontStyle="italic">start</text>

        <polyline points={fillPts} fill="url(#hyb-grad)" stroke="none" />
        <polyline points={pts} fill="none" stroke="#3b82f6" strokeWidth="2.5" strokeLinejoin="round" />

        <circle cx={sx(peak.t)} cy={sy(peak.v)} r="4" fill="#3b82f6" />
        <line x1={sx(peak.t)} y1={sy(peak.v) - 8} x2={sx(peak.t)} y2={sy(peak.v) - 28} stroke="#0f172a" strokeWidth="0.8" />
        <text x={sx(peak.t)} y={sy(peak.v) - 34} fontSize="12" fill="#0f172a" textAnchor="middle" fontWeight="600">Peak ${peak.v.toFixed(0)}</text>

        <circle cx={sx(last.t)} cy={sy(last.v)} r="5" fill="#3b82f6" stroke="#fff" strokeWidth="2.5" />
        <text x={sx(last.t) - 10} y={sy(last.v) + 5} fontSize="15" fill="#0f172a" textAnchor="end" fontWeight="700" fontFamily="ui-monospace, monospace">${last.v.toFixed(2)}</text>
      </svg>
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

  function CalibrationMini({ data, w = 340, h = 200 }) {
    return (
      <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
        {[0, 0.25, 0.5, 0.75, 1].map(t => (
          <g key={t}>
            <line x1={30 + t * (w - 50)} y1="15" x2={30 + t * (w - 50)} y2={h - 30} stroke="#e5e7eb" strokeWidth="0.8" />
            <text x={30 + t * (w - 50)} y={h - 14} fontSize="9" fill="#94a3b8" textAnchor="middle" fontFamily="ui-monospace, monospace">{t.toFixed(1)}</text>
            <line x1="30" y1={15 + (1 - t) * (h - 45)} x2={w - 20} y2={15 + (1 - t) * (h - 45)} stroke="#e5e7eb" strokeWidth="0.8" />
            <text x="26" y={19 + (1 - t) * (h - 45)} fontSize="9" fill="#94a3b8" textAnchor="end" fontFamily="ui-monospace, monospace">{t.toFixed(1)}</text>
          </g>
        ))}
        <line x1="30" y1={h - 30} x2={w - 20} y2="15" stroke="#cbd5e1" strokeWidth="1.2" strokeDasharray="2 3" />
        {data.map((c, i) => (
          <circle key={i} cx={30 + c.bucket * (w - 50)} cy={15 + (1 - c.realized) * (h - 45)}
            r={Math.sqrt(c.n) / 1.8} fill="#3b82f6" fillOpacity="0.25" stroke="#3b82f6" strokeWidth="1.5" />
        ))}
        <polyline
          points={data.map(c => `${30 + c.bucket * (w - 50)},${15 + (1 - c.realized) * (h - 45)}`).join(' ')}
          fill="none" stroke="#3b82f6" strokeWidth="1.8" />
        <text x={w / 2} y={h - 1} fontSize="10" fill="#94a3b8" textAnchor="middle">Forecast probability</text>
      </svg>
    );
  }

  function OpportunitiesTable() {
    return (
      <section style={{
        background: '#fff', border: '1px solid #e7eaef',
        borderRadius: 14, overflow: 'hidden',
      }}>
        <div style={{
          padding: '14px 18px', borderBottom: '1px solid #e7eaef',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Top opportunities</h3>
          <span style={{
            padding: '3px 9px', borderRadius: 999, background: 'rgba(59,130,246,0.12)', color: '#3b82f6',
            fontSize: 10, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase',
          }}>EDGE ≥ 7%</span>
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ color: '#94a3b8', fontSize: 11 }}>
              {['Ticker', 'City', 'Ask', 'Fcst', 'Edge', 'Tier'].map((h, i) => (
                <th key={h} style={{
                  padding: '9px 16px', textAlign: i >= 2 && i <= 4 ? 'right' : 'left',
                  fontWeight: 500, borderBottom: '1px solid #e7eaef',
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {M.opportunities.slice(0, 7).map((o, i) => (
              <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                <td style={{ padding: '10px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#3b82f6' }}>
                  {o.ticker.split('-')[0].replace('KX', '')}
                </td>
                <td style={{ padding: '10px 16px' }}>{o.city}</td>
                <td style={{ padding: '10px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>{o.yes_ask.toFixed(2)}</td>
                <td style={{ padding: '10px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>{o.fcst.toFixed(2)}</td>
                <td style={{ padding: '10px 16px', textAlign: 'right', color: '#16a34a', fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>
                  +{(o.edge * 100).toFixed(0)}%
                </td>
                <td style={{ padding: '10px 16px' }}>
                  <span style={{
                    display: 'inline-block', padding: '2px 7px', borderRadius: 999,
                    background: o.tier === 'STRONG' ? 'rgba(34,197,94,0.12)' : 'rgba(100,116,139,0.08)',
                    color: o.tier === 'STRONG' ? '#16a34a' : '#64748b',
                    fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                  }}>{o.tier}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    );
  }

  function ModelAccuracy() {
    const max = Math.max(...M.modelAccuracy.map(m => m.edge_realized));
    return (
      <section style={{
        background: '#fff', border: '1px solid #e7eaef',
        borderRadius: 14, padding: '20px',
      }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Model accuracy</h3>
        <p style={{ color: '#64748b', fontSize: 12, marginBottom: 16, lineHeight: 1.4 }}>
          Five forecast sources ranked by realized edge. NBM wins; the ensemble (weighted average) is what we trade.
        </p>
        {M.modelAccuracy.map((m, i) => (
          <div key={i} style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
              <span style={{ fontWeight: 600 }}>{m.model}</span>
              <span style={{ color: '#94a3b8', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>
                Brier {m.brier.toFixed(3)} · {(m.win_rate * 100).toFixed(0)}% · n={m.trades}
              </span>
            </div>
            <div style={{ position: 'relative', height: 18, background: '#f1f5f9', borderRadius: 4, overflow: 'hidden' }}>
              <div style={{
                position: 'absolute', inset: 0, width: (m.edge_realized / max * 100) + '%',
                background: '#3b82f6',
              }} />
              <span style={{
                position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)',
                fontSize: 11, color: '#0f172a', fontFamily: 'ui-monospace, monospace', fontWeight: 600,
              }}>+{(m.edge_realized * 100).toFixed(1)}%</span>
            </div>
          </div>
        ))}
      </section>
    );
  }

  function AlertsFeed() {
    return (
      <section style={{
        background: '#fff', border: '1px solid #e7eaef',
        borderRadius: 14, overflow: 'hidden',
      }}>
        <div style={{
          padding: '14px 18px', borderBottom: '1px solid #e7eaef',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Alerts</h3>
          <span style={{
            padding: '3px 9px', borderRadius: 999, background: 'rgba(234,179,8,0.12)', color: '#ca8a04',
            fontSize: 10, fontWeight: 600,
          }}>{M.alerts.length}</span>
        </div>
        {M.alerts.map((a, i) => (
          <div key={i} style={{
            display: 'grid', gridTemplateColumns: '50px 60px 1fr', gap: 10, alignItems: 'flex-start',
            padding: '11px 18px', borderBottom: i < M.alerts.length - 1 ? '1px solid #f1f5f9' : 'none',
          }}>
            <span style={{ color: '#94a3b8', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>{a.ts}</span>
            <span style={{
              display: 'inline-block', padding: '2px 7px', borderRadius: 999,
              background: a.level === 'warn' ? 'rgba(234,179,8,0.12)' : a.level === 'good' ? 'rgba(34,197,94,0.12)' : 'rgba(100,116,139,0.08)',
              color: a.level === 'warn' ? '#ca8a04' : a.level === 'good' ? '#16a34a' : '#64748b',
              fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em',
            }}>{a.level}</span>
            <span style={{ fontSize: 12, color: '#0f172a' }}>{a.text}</span>
          </div>
        ))}
      </section>
    );
  }

  function MLCalibration() {
    return (
      <section style={{
        background: '#fff', border: '1px solid #e7eaef',
        borderRadius: 14, padding: '20px',
      }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>ML Calibration · per-city models</h3>
        <p style={{ color: '#64748b', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
          GradientBoosting models trained on 200+ settled trades per city. Shows Brier lift vs raw forecasts.
        </p>
        {M.mlModels.slice(0, 8).map((m, i) => {
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
    );
  }

  function App() {
    const s = M.stats;

    return (
      <div style={{
        background: '#fafafa', color: '#0f172a',
        fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        fontSize: 14, width: '100%', minHeight: '100vh', overflow: 'auto',
      }}>
        {/* Nav */}
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
              {['Overview', 'Positions', 'Signals', 'Forecast', 'Analytics', 'Risk'].map((n, i) => (
                <a key={n} href="#" style={{
                  padding: '7px 13px', borderRadius: 7,
                  color: i === 0 ? '#0f172a' : '#64748b',
                  background: i === 0 ? '#f1f5f9' : 'transparent',
                  fontWeight: i === 0 ? 600 : 500, textDecoration: 'none',
                }}>{n}</a>
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

        <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
          {/* Headline */}
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

          {/* Stat cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
            <StatCard label="Paper balance" value={'$' + s.balance.toFixed(2)} delta={'+' + ((s.balance - s.starting_balance) / s.starting_balance * 100).toFixed(1) + '%'} deltaTone="pos" sub={'from $' + s.starting_balance.toFixed(2) + ' start'} />
            <StatCard label="Open positions" value={s.open_count} sub={s.settled_count + ' settled so far'} />
            <StatCard label="Win rate" value={(s.win_rate * 100).toFixed(1) + '%'} delta="+2.3 pts" deltaTone="pos" />
            <StatCard label="Brier score" value={s.brier.toFixed(3)} delta="−0.012" deltaTone="pos" sub="target ≤0.20" />
          </div>

          {/* Hero equity chart */}
          <section style={{
            background: '#fff', border: '1px solid #e7eaef',
            borderRadius: 14, padding: '18px 20px', marginBottom: 18,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 3 }}>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>Equity curve · 90 days</h2>
              <div style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'ui-monospace, monospace' }}>
                Feb 5 → today
              </div>
            </div>
            <p style={{ color: '#64748b', fontSize: 12, marginTop: 3, marginBottom: 16 }}>
              Started with $1,000. After a mid-March drawdown, Kelly sizing recovered and held steady.
            </p>
            <HeroEquityChart data={M.balanceHist} />
          </section>

          {/* Grid: Calibration | Positions | Opportunities */}
          <div style={{ display: 'grid', gridTemplateColumns: '0.85fr 1.4fr 1fr', gap: 12, marginBottom: 18 }}>
            <section style={{
              background: '#fff', border: '1px solid #e7eaef',
              borderRadius: 14, padding: '18px', display: 'flex', flexDirection: 'column',
            }}>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Calibration</h3>
              <p style={{ color: '#64748b', fontSize: 11, marginBottom: 12, lineHeight: 1.45 }}>
                When we say 70%, does it happen 70%? Closer to diagonal = better.
              </p>
              <CalibrationMini data={M.calibration} />
              <div style={{ marginTop: 12, padding: '9px 11px', borderRadius: 8, background: '#f1f5f9', fontSize: 11 }}>
                <strong style={{ color: '#0f172a' }}>Brier 0.151</strong> · 567 trades
              </div>
            </section>

            <section style={{
              background: '#fff', border: '1px solid #e7eaef',
              borderRadius: 14, overflow: 'hidden',
            }}>
              <div style={{
                padding: '13px 16px', borderBottom: '1px solid #e7eaef',
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              }}>
                <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Open positions</h3>
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ color: '#94a3b8', fontSize: 11 }}>
                    {['Market', 'Side', 'Cost', 'Edge', 'Expiry'].map((h, i) => (
                      <th key={h} style={{
                        padding: '8px 14px', textAlign: i === 0 ? 'left' : i < 4 ? 'right' : 'left',
                        fontWeight: 500, borderBottom: '1px solid #e7eaef',
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {M.positions.map((p, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                      <td style={{ padding: '10px 14px' }}>
                        <div style={{ fontWeight: 600, color: '#0f172a', fontSize: 12 }}>{p.city}</div>
                        <div style={{ fontSize: 10, color: '#94a3b8', fontFamily: 'ui-monospace, monospace', marginTop: 1 }}>
                          {p.ticker}
                        </div>
                      </td>
                      <td style={{ padding: '10px 14px', textAlign: 'right' }}>
                        <span style={{
                          display: 'inline-block', padding: '2px 7px', borderRadius: 999,
                          background: p.side === 'yes' ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
                          color: p.side === 'yes' ? '#16a34a' : '#ef4444',
                          fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                        }}>{p.side}</span>
                      </td>
                      <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', fontVariantNumeric: 'tabular-nums', fontSize: 12 }}>
                        ${p.cost.toFixed(2)}
                      </td>
                      <td style={{ padding: '10px 14px', textAlign: 'right', color: '#16a34a', fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>
                        +{(p.edge * 100).toFixed(1)}%
                      </td>
                      <td style={{ padding: '10px 14px', color: '#94a3b8', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>
                        {p.expiry}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <OpportunitiesTable />
          </div>

          {/* Bottom row: Data sources | Model | Alerts | ML */}
          <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr 1fr 1fr', gap: 12 }}>
            <section style={{
              background: '#fff', border: '1px solid #e7eaef',
              borderRadius: 14, padding: '18px',
            }}>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Data sources</h3>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 9 }}>
                {M.circuitBreakers.map((cb, i) => {
                  const open = cb.state === 'open';
                  return (
                    <div key={i} style={{
                      padding: '9px 11px', borderRadius: 8,
                      background: '#f8f9fb', border: '1px solid #eef0f3',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                        <span style={{
                          width: 6, height: 6, borderRadius: '50%',
                          background: open ? '#ef4444' : '#16a34a',
                        }} />
                        <span style={{ fontSize: 11, fontWeight: 600 }}>{cb.label}</span>
                      </div>
                      <div style={{ fontSize: 10, color: '#94a3b8', fontFamily: 'ui-monospace, monospace' }}>
                        {open ? `Retry ${cb.retry_in_s}s` : `${cb.latency_ms}ms`}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            <ModelAccuracy />
            <AlertsFeed />
            <MLCalibration />
          </div>
        </main>
      </div>
    );
  }

  return { App };
})();
window.HybridVar = HybridVar;
