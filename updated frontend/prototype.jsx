// Operator dashboard — interactive prototype with all six tweaks wired

const Proto = (function () {
  const M = window.MOCK;
  const { useState, useEffect, useMemo } = React;

  function fmt$(v) { return (v >= 0 ? '+' : '') + '$' + v.toFixed(2); }

  // -- Charts --

  function LineOrAreaChart({ data, w = 800, h = 200, color, mode, dark }) {
    if (!data || !data.length) return null;
    const xs = data.map(d => d.t);
    const ys = data.map(d => d.v);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys) * 0.99, maxY = Math.max(...ys) * 1.01;
    const sx = x => ((x - minX) / Math.max(1, maxX - minX)) * (w - 50) + 40;
    const sy = y => h - 24 - ((y - minY) / Math.max(0.0001, maxY - minY)) * (h - 36);
    const pts = data.map(d => `${sx(d.t).toFixed(1)},${sy(d.v).toFixed(1)}`).join(' ');
    const fillPts = `${sx(data[0].t)},${h - 24} ${pts} ${sx(data[data.length - 1].t)},${h - 24}`;
    const grid = dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.07)';
    const muted = dark ? '#5e6e7e' : '#94a3b8';

    if (mode === 'candle') {
      // synthesize OHLC by chunking
      const N = 18;
      const chunkSize = Math.floor(data.length / N);
      const chunks = [];
      for (let i = 0; i < N; i++) {
        const slice = data.slice(i * chunkSize, (i + 1) * chunkSize);
        if (!slice.length) continue;
        const vs = slice.map(s => s.v);
        chunks.push({
          t: slice[Math.floor(slice.length / 2)].t,
          o: slice[0].v, c: slice[slice.length - 1].v,
          hi: Math.max(...vs), lo: Math.min(...vs),
        });
      }
      const cw = (w - 50) / N * 0.6;
      return (
        <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
          {[0.25, 0.5, 0.75].map((t, i) => (
            <line key={i} x1="40" y1={12 + (h - 36) * t} x2={w - 10} y2={12 + (h - 36) * t} stroke={grid} />
          ))}
          {chunks.map((k, i) => {
            const x = sx(k.t);
            const up = k.c >= k.o;
            const c = up ? '#00c896' : '#ff5060';
            return (
              <g key={i}>
                <line x1={x} y1={sy(k.hi)} x2={x} y2={sy(k.lo)} stroke={c} strokeWidth="1" />
                <rect x={x - cw / 2} y={sy(Math.max(k.o, k.c))} width={cw} height={Math.max(1, Math.abs(sy(k.o) - sy(k.c)))} fill={c} />
              </g>
            );
          })}
        </svg>
      );
    }

    return (
      <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
        {[0.25, 0.5, 0.75].map((t, i) => (
          <line key={i} x1="40" y1={12 + (h - 36) * t} x2={w - 10} y2={12 + (h - 36) * t} stroke={grid} />
        ))}
        {mode === 'area' && <polyline points={fillPts} fill={color} fillOpacity="0.15" stroke="none" />}
        <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
        <text x="40" y={h - 6} fontSize="9" fill={muted}>90d</text>
        <text x={w - 10} y={h - 6} fontSize="9" fill={muted} textAnchor="end">now</text>
      </svg>
    );
  }

  function Sparkline({ data, w = 100, h = 24, color, dark }) {
    if (!data || !data.length) return null;
    const ys = data.map(d => d.v);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const sy = v => h - ((v - minY) / Math.max(0.0001, maxY - minY)) * h;
    const pts = data.map((d, i) => `${(i / (data.length - 1)) * w},${sy(d.v).toFixed(1)}`).join(' ');
    return (
      <svg width={w} height={h} style={{ display: 'block' }}>
        <polyline points={pts} fill="none" stroke={color} strokeWidth="1.4" />
      </svg>
    );
  }

  // -- UI atoms --

  function Pill({ children, tone = 'neutral', t }) {
    const map = {
      neutral: { bg: t.dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)', fg: t.text },
      pos:     { bg: t.accent + '22',   fg: t.accent },
      neg:     { bg: 'rgba(255,80,90,0.14)', fg: t.neg },
      warn:    { bg: 'rgba(255,180,60,0.16)', fg: t.warn },
    };
    const s = map[tone] || map.neutral;
    return (
      <span style={{
        display: 'inline-block', padding: '1px 7px',
        borderRadius: t.radius, background: s.bg, color: s.fg,
        fontSize: 10, letterSpacing: '0.06em', textTransform: 'uppercase',
        fontWeight: 600, fontFamily: t.uiFont,
      }}>{children}</span>
    );
  }

  function Panel({ title, right, children, t, style = {} }) {
    return (
      <section style={{
        border: `1px solid ${t.line}`, background: t.surface, borderRadius: t.radius,
        overflow: 'hidden', ...style,
      }}>
        <header style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: t.density === 'compact' ? '6px 10px' : '10px 14px',
          borderBottom: `1px solid ${t.line}`,
          fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase',
          color: t.muted, fontFamily: t.uiFont, fontWeight: 600,
        }}>
          <span>{title}</span>
          <span style={{ display: 'flex', gap: 6 }}>{right}</span>
        </header>
        {children}
      </section>
    );
  }

  function StatCell({ label, value, sub, tone, t, sparkData, sparkColor }) {
    const c = tone === 'pos' ? t.pos : tone === 'neg' ? t.neg : t.text;
    return (
      <div style={{
        flex: 1, padding: t.density === 'compact' ? '8px 12px' : '14px 16px',
        borderRight: `1px solid ${t.line}`, minWidth: 0,
      }}>
        <div style={{
          fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase',
          color: t.muted, marginBottom: 4, fontFamily: t.uiFont, fontWeight: 600,
        }}>{label}</div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <div style={{
            fontFamily: t.numFont, fontSize: t.density === 'compact' ? 17 : 22,
            fontWeight: 600, color: c, lineHeight: 1, fontVariantNumeric: 'tabular-nums',
          }}>{value}</div>
          {sub && <div style={{ fontFamily: t.numFont, fontSize: 11, color: t.muted }}>{sub}</div>}
        </div>
        {sparkData && (
          <div style={{ marginTop: 6 }}>
            <Sparkline data={sparkData} w={140} h={20} color={sparkColor || t.accent} dark={t.dark} />
          </div>
        )}
      </div>
    );
  }

  // -- Theme builder --

  const PALETTES = {
    green:  { accent: '#00c896', accentSoft: '#7adcc4' },
    blue:   { accent: '#3b82f6', accentSoft: '#93c5fd' },
    amber:  { accent: '#f59e0b', accentSoft: '#fcd34d' },
    purple: { accent: '#8b5cf6', accentSoft: '#c4b5fd' },
  };

  function buildTheme(tw) {
    const dark = !!tw.dark;
    const compact = tw.density === 'compact';
    const pal = PALETTES[tw.palette] || PALETTES.green;
    return {
      dark, density: tw.density,
      bg:      dark ? '#0a0d0f' : '#f7f8fa',
      surface: dark ? '#10141a' : '#ffffff',
      line:    dark ? '#222a33' : '#e7eaef',
      track:   dark ? '#1a2128' : '#eef1f5',
      text:    dark ? '#d6deea' : '#0f172a',
      muted:   dark ? '#5e6e7e' : '#64748b',
      accent: pal.accent, accentSoft: pal.accentSoft,
      pos: '#00c896', neg: '#ff5060', warn: '#f59e0b',
      radius: 4,
      pad: compact ? 8 : 14,
      rowH: compact ? 22 : 30,
      uiFont: "Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
      numFont: "'JetBrains Mono', 'IBM Plex Mono', ui-monospace, Consolas, monospace",
    };
  }

  // -- Sub-views --

  function PositionsTable({ t }) {
    const [sortKey, setSortKey] = useState('edge');
    const [filter, setFilter] = useState('');
    const rows = useMemo(() => {
      const f = filter.toLowerCase();
      const filtered = M.positions.filter(p => !f || p.city.toLowerCase().includes(f) || p.ticker.toLowerCase().includes(f));
      return [...filtered].sort((a, b) => {
        if (sortKey === 'edge') return b.edge - a.edge;
        if (sortKey === 'cost') return b.cost - a.cost;
        if (sortKey === 'age') return a.age_h - b.age_h;
        return 0;
      });
    }, [sortKey, filter]);

    return (
      <Panel
        title={`Open Positions · ${M.positions.length}`}
        t={t}
        right={
          <>
            <input
              placeholder="filter…"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              style={{
                background: t.track, border: `1px solid ${t.line}`, color: t.text,
                fontSize: 10, padding: '2px 6px', borderRadius: t.radius, width: 90,
                fontFamily: t.uiFont, outline: 'none',
              }} />
            {['edge', 'cost', 'age'].map(k => (
              <button key={k} onClick={() => setSortKey(k)} style={{
                background: sortKey === k ? t.accent + '20' : 'transparent',
                color: sortKey === k ? t.accent : t.muted,
                border: `1px solid ${sortKey === k ? t.accent + '55' : t.line}`,
                fontSize: 10, padding: '2px 7px', borderRadius: t.radius, cursor: 'pointer',
                fontFamily: t.uiFont, textTransform: 'uppercase', letterSpacing: '0.06em',
              }}>{k}</button>
            ))}
          </>
        }>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ color: t.muted, fontSize: 10, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
              {['Ticker', 'City', 'Side', 'Cost', 'Mark', 'Fcst', 'Edge', 'Model', 'Expiry'].map((h, i) => (
                <th key={h} style={{
                  padding: t.density === 'compact' ? '4px 10px' : '8px 12px',
                  textAlign: i >= 3 && i <= 6 ? 'right' : i === 2 || i === 7 ? 'center' : 'left',
                  fontWeight: 600, borderBottom: `1px solid ${t.line}`, fontFamily: t.uiFont,
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((p, i) => (
              <tr key={i} style={{ height: t.rowH, borderBottom: `1px solid ${t.line}` }}>
                <td style={{ padding: '0 10px', color: t.accent, fontFamily: t.numFont, fontSize: 11 }}>{p.ticker}</td>
                <td style={{ padding: '0 10px', color: t.muted, fontFamily: t.uiFont }}>{p.city}</td>
                <td style={{ padding: '0 10px', textAlign: 'center' }}>
                  <Pill t={t} tone={p.side === 'yes' ? 'pos' : 'neg'}>{p.side.toUpperCase()}</Pill>
                </td>
                <td style={{ padding: '0 10px', textAlign: 'right', fontFamily: t.numFont }}>${p.cost.toFixed(2)}</td>
                <td style={{ padding: '0 10px', textAlign: 'right', color: t.muted, fontFamily: t.numFont }}>{p.mark.toFixed(2)}</td>
                <td style={{ padding: '0 10px', textAlign: 'right', fontFamily: t.numFont }}>{p.fcst.toFixed(2)}</td>
                <td style={{ padding: '0 10px', textAlign: 'right', color: t.pos, fontFamily: t.numFont, fontWeight: 600 }}>+{(p.edge * 100).toFixed(1)}%</td>
                <td style={{ padding: '0 10px', textAlign: 'center', color: t.muted, fontFamily: t.numFont, fontSize: 10 }}>{p.model}</td>
                <td style={{ padding: '0 10px', color: t.muted, fontFamily: t.numFont, fontSize: 11 }}>{p.expiry}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    );
  }

  function CalibrationPanel({ t }) {
    return (
      <Panel title="ML Calibration · per-city" t={t} right={<Pill t={t} tone="pos">8 models</Pill>}>
        <div style={{ padding: t.pad }}>
          {M.mlModels.slice(0, 6).map((m, i) => {
            const pct = (m.lift / 0.04) * 100;
            return (
              <div key={i} style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, alignItems: 'center',
                padding: '5px 0', fontSize: 11, fontFamily: t.numFont,
              }}>
                <span style={{ fontFamily: t.uiFont, color: t.text }}>{m.city}</span>
                <div style={{ height: 4, background: t.track, borderRadius: 2, overflow: 'hidden' }}>
                  <div style={{ width: pct + '%', height: '100%', background: t.accent }} />
                </div>
                <span style={{ textAlign: 'right', color: t.pos, fontWeight: 600 }}>−{m.lift.toFixed(3)} Brier</span>
              </div>
            );
          })}
        </div>
      </Panel>
    );
  }

  function AlertsTicker({ t }) {
    return (
      <Panel title="Alerts" t={t} right={<Pill t={t} tone="warn">{M.alerts.length}</Pill>}>
        <div>
          {M.alerts.map((a, i) => (
            <div key={i} style={{
              display: 'grid', gridTemplateColumns: '46px 56px 1fr', gap: 8,
              padding: t.density === 'compact' ? '4px 10px' : '8px 14px',
              borderBottom: i < M.alerts.length - 1 ? `1px solid ${t.line}` : 'none',
              fontSize: 11, alignItems: 'flex-start',
            }}>
              <span style={{ color: t.muted, fontFamily: t.numFont }}>{a.ts}</span>
              <Pill t={t} tone={a.level === 'warn' ? 'warn' : a.level === 'good' ? 'pos' : 'neutral'}>
                {a.level.toUpperCase()}
              </Pill>
              <span style={{ color: t.text, fontFamily: t.uiFont }}>{a.text}</span>
            </div>
          ))}
        </div>
      </Panel>
    );
  }

  // -- Main app --

  const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
    "palette": "green",
    "density": "compact",
    "chartStyle": "area",
    "layout": "topnav",
    "showAlerts": true,
    "showCalibration": true,
    "dark": true
  }/*EDITMODE-END*/;

  function App() {
    const [tw, setTweak] = window.useTweaks(TWEAK_DEFAULTS);
    const t = useMemo(() => buildTheme(tw), [tw]);
    const s = M.stats;

    const sidebar = tw.layout === 'sidebar';

    const TopBar = (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 16px', borderBottom: `1px solid ${t.line}`,
        background: t.surface, position: 'sticky', top: 0, zIndex: 5,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{
              width: 22, height: 22, borderRadius: 6,
              background: t.accent, display: 'grid', placeItems: 'center',
              color: t.dark ? '#0a0d0f' : '#fff', fontWeight: 800, fontSize: 12,
              fontFamily: t.uiFont,
            }}>K</div>
            <div style={{ fontWeight: 700, fontSize: 13, fontFamily: t.uiFont, letterSpacing: '0.04em' }}>
              KALSHI · WX
            </div>
          </div>
          {!sidebar && (
            <nav style={{ display: 'flex', gap: 2, fontSize: 12 }}>
              {['Dashboard', 'Positions', 'Signals', 'Forecast', 'Analytics', 'Risk'].map((n, i) => (
                <a key={n} href="#" style={{
                  padding: '6px 12px', borderRadius: t.radius,
                  color: i === 0 ? t.accent : t.muted,
                  background: i === 0 ? t.accent + '15' : 'transparent',
                  fontWeight: i === 0 ? 600 : 500, textDecoration: 'none', fontFamily: t.uiFont,
                }}>{n}</a>
              ))}
            </nav>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: t.muted, fontFamily: t.uiFont }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: t.pos, boxShadow: `0 0 6px ${t.pos}` }} />
            Live · 02:48 ago
          </div>
          <Pill t={t} tone="warn">DEMO</Pill>
          <Pill t={t} tone="pos">GRAD ✓</Pill>
          <button style={{
            padding: '5px 10px', borderRadius: t.radius, border: `1px solid ${t.line}`,
            background: t.surface, color: t.text, fontSize: 11, fontWeight: 600, fontFamily: t.uiFont,
            cursor: 'pointer',
          }}>Kill</button>
        </div>
      </div>
    );

    const Sidebar = sidebar && (
      <aside style={{
        width: 200, borderRight: `1px solid ${t.line}`, background: t.surface,
        display: 'flex', flexDirection: 'column', flex: '0 0 auto',
      }}>
        <div style={{
          padding: '14px 16px', borderBottom: `1px solid ${t.line}`,
          fontWeight: 700, fontSize: 13, color: t.accent, fontFamily: t.uiFont, letterSpacing: '0.05em',
        }}>KALSHI · WX</div>
        <nav style={{ flex: 1, padding: '10px 8px' }}>
          {['Dashboard', 'Positions', 'Signals', 'Forecast', 'Analytics', 'Risk', 'Trades'].map((n, i) => (
            <a key={n} href="#" style={{
              display: 'block', padding: '7px 12px', borderRadius: t.radius,
              color: i === 0 ? t.accent : t.muted,
              background: i === 0 ? t.accent + '15' : 'transparent',
              fontWeight: i === 0 ? 600 : 500, textDecoration: 'none', fontFamily: t.uiFont,
              fontSize: 12, marginBottom: 2,
            }}>{n}</a>
          ))}
        </nav>
        <div style={{ padding: '12px 16px', borderTop: `1px solid ${t.line}`, fontSize: 10, color: t.muted, fontFamily: t.numFont }}>
          v1.0 · uptime 12d 04h
        </div>
      </aside>
    );

    const StatStrip = (
      <div style={{
        display: 'flex', borderBottom: `1px solid ${t.line}`, background: t.surface,
      }}>
        <StatCell t={t} label="Paper Bal" value={'$' + s.balance.toFixed(2)}
          sub={'+' + ((s.balance - s.starting_balance) / s.starting_balance * 100).toFixed(1) + '%'}
          tone="pos" sparkData={M.balanceHist.slice(-30)} sparkColor={t.pos} />
        <StatCell t={t} label="Today P&L" value={fmt$(s.today_pnl)} sub="8 open · 3 settled" tone="pos" />
        <StatCell t={t} label="Open" value={s.open_count} sub="/20 max" />
        <StatCell t={t} label="Win Rate" value={(s.win_rate * 100).toFixed(1) + '%'} sub={'n=' + s.settled_count} tone="pos" />
        <StatCell t={t} label="Brier" value={s.brier.toFixed(3)} sub="↓ better" tone="pos" sparkData={M.brierHist.slice(-30)} sparkColor={t.warn} />
        <StatCell t={t} label="Day Spend" value={'$' + s.daily_spend.toFixed(0)} sub={'/$' + s.max_daily_spend} />
        <StatCell t={t} label="Fear/Greed" value={s.fear_greed} sub={s.fear_greed_label} tone="pos" />
      </div>
    );

    const Body = (
      <div style={{
        display: 'grid',
        gridTemplateColumns: tw.showAlerts ? '1.6fr 1fr 0.9fr' : '1.6fr 1fr',
        gap: 1, background: t.line, padding: 1, flex: 1, alignContent: 'flex-start',
      }}>
        {/* Equity chart */}
        <Panel title={'Equity Curve · 90d · ' + tw.chartStyle} t={t}
          right={<><Pill t={t}>1M</Pill><Pill t={t} tone="pos">3M</Pill><Pill t={t}>1Y</Pill></>}
          style={{ gridColumn: tw.showAlerts ? '1 / 3' : '1 / 2' }}>
          <div style={{ padding: t.pad, color: t.pos }}>
            <LineOrAreaChart data={M.balanceHist} w={800} h={180} color={t.accent} mode={tw.chartStyle} dark={t.dark} />
          </div>
        </Panel>

        {tw.showAlerts && <div style={{ gridRow: 'span 2' }}><AlertsTicker t={t} /></div>}

        <PositionsTable t={t} />

        <Panel title="Top Opportunities" t={t} right={<Pill t={t}>EDGE ≥ 7%</Pill>}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ color: t.muted, fontSize: 10, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                {['Ticker', 'Ask', 'Fcst', 'Edge', 'Tier'].map((h, i) => (
                  <th key={h} style={{
                    padding: '6px 10px', textAlign: i > 0 && i < 4 ? 'right' : 'left',
                    fontWeight: 600, borderBottom: `1px solid ${t.line}`, fontFamily: t.uiFont,
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {M.opportunities.slice(0, 6).map((o, i) => (
                <tr key={i} style={{ height: t.rowH, borderBottom: `1px solid ${t.line}` }}>
                  <td style={{ padding: '0 10px' }}>
                    <div style={{ color: t.accent, fontFamily: t.numFont, fontSize: 11 }}>{o.ticker.split('-')[0].replace('KX', '')}</div>
                    <div style={{ color: t.muted, fontFamily: t.uiFont, fontSize: 10 }}>{o.city}</div>
                  </td>
                  <td style={{ padding: '0 10px', textAlign: 'right', fontFamily: t.numFont }}>{o.yes_ask.toFixed(2)}</td>
                  <td style={{ padding: '0 10px', textAlign: 'right', fontFamily: t.numFont }}>{o.fcst.toFixed(2)}</td>
                  <td style={{ padding: '0 10px', textAlign: 'right', color: t.pos, fontFamily: t.numFont, fontWeight: 600 }}>+{(o.edge * 100).toFixed(0)}%</td>
                  <td style={{ padding: '0 10px', textAlign: 'center' }}>
                    <Pill t={t} tone={o.tier === 'STRONG' ? 'pos' : 'neutral'}>{o.tier}</Pill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Data Sources · Circuit Breakers" t={t} style={{ gridColumn: tw.showAlerts ? '1 / 3' : '1 / 2' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1, background: t.line }}>
            {M.circuitBreakers.map((cb, i) => {
              const open = cb.state === 'open';
              return (
                <div key={i} style={{
                  background: t.surface, padding: '8px 12px',
                  borderLeft: `2px solid ${open ? t.neg : t.pos}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, fontFamily: t.uiFont }}>
                    <span style={{ color: t.text, fontWeight: 500 }}>{cb.label}</span>
                    <span style={{ color: open ? t.neg : t.pos, fontWeight: 600 }}>{open ? 'OPEN' : 'OK'}</span>
                  </div>
                  <div style={{ fontSize: 10, color: t.muted, marginTop: 2, fontFamily: t.numFont }}>
                    {open ? `${cb.failures} failures · retry ${cb.retry_in_s}s` : `${cb.latency_ms}ms · ${cb.failures} fails`}
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>

        {tw.showCalibration && <CalibrationPanel t={t} />}
      </div>
    );

    return (
      <div style={{
        background: t.bg, color: t.text, fontFamily: t.uiFont,
        minHeight: '100vh', display: 'flex', flexDirection: sidebar ? 'row' : 'column',
      }}>
        {Sidebar}
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0 }}>
          {TopBar}
          {StatStrip}
          {Body}
        </div>

        <window.TweaksPanel title="Tweaks">
          <window.TweakSection label="Theme" />
          <window.TweakToggle label="Dark mode" value={tw.dark} onChange={v => setTweak('dark', v)} />
          <window.TweakRadio label="Color accent" value={tw.palette}
            options={['green', 'blue', 'amber', 'purple']}
            onChange={v => setTweak('palette', v)} />

          <window.TweakSection label="Layout" />
          <window.TweakRadio label="Nav" value={tw.layout}
            options={['topnav', 'sidebar']}
            onChange={v => setTweak('layout', v)} />
          <window.TweakRadio label="Density" value={tw.density}
            options={['compact', 'comfy']}
            onChange={v => setTweak('density', v)} />

          <window.TweakSection label="Charts" />
          <window.TweakRadio label="Style" value={tw.chartStyle}
            options={['line', 'area', 'candle']}
            onChange={v => setTweak('chartStyle', v)} />

          <window.TweakSection label="Panels" />
          <window.TweakToggle label="Alerts ticker" value={tw.showAlerts} onChange={v => setTweak('showAlerts', v)} />
          <window.TweakToggle label="ML Calibration" value={tw.showCalibration} onChange={v => setTweak('showCalibration', v)} />
        </window.TweaksPanel>
      </div>
    );
  }

  return { App };
})();

ReactDOM.createRoot(document.getElementById('proto-root')).render(<Proto.App />);
