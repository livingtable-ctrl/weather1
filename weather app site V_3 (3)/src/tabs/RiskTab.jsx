import React, { useContext } from 'react';
import { DataContext } from '../DataContext.js';
import { authHeader } from '../useData.js';
import { StatCard } from '../shared.jsx';

// ---------------------------------------------------------------------------
// BrierAlertCard — P10.3 Brier degradation alert. Fires when weekly Brier
// exceeds 0.22 (P10.3_THRESHOLD in alerts.py) for 2+ consecutive weeks.
// Threshold hardcoded here so the card stays frontend-only with no new endpoint.
// ---------------------------------------------------------------------------
function BrierAlertCard() {
  const M = useContext(DataContext);
  const THRESHOLD = 0.22;
  const recent = (M.brierHistory || []).slice(-6);

  if (recent.length < 2) return null;

  let consecutiveAbove = 0;
  for (let i = recent.length - 1; i >= 0; i--) {
    if (recent[i].brier > THRESHOLD) consecutiveAbove++;
    else break;
  }

  const latest = recent[recent.length - 1];
  const statusColor = consecutiveAbove >= 2 ? '#ef4444' : consecutiveAbove === 1 ? '#ca8a04' : '#16a34a';
  const statusLabel = consecutiveAbove >= 2 ? 'DEGRADING' : consecutiveAbove === 1 ? 'ALERT' : 'CLEAR';
  const borderColor = consecutiveAbove >= 2 ? 'rgba(239,68,68,0.4)' : consecutiveAbove === 1 ? 'rgba(202,138,4,0.4)' : 'var(--border)';

  const W = 400, H = 70, PAD = { top: 8, right: 16, bottom: 20, left: 8 };
  const iW = W - PAD.left - PAD.right;
  const iH = H - PAD.top - PAD.bottom;

  const allBriers = recent.map(e => e.brier);
  // Pad min/max so the 0.22 threshold line is always visible with breathing room
  const minB = Math.min(THRESHOLD - 0.05, ...allBriers);
  const maxB = Math.max(THRESHOLD + 0.05, ...allBriers);
  const rangeB = maxB - minB || 0.01;

  const toX = i => PAD.left + (i / Math.max(recent.length - 1, 1)) * iW;
  const toY = b => PAD.top + (1 - (b - minB) / rangeB) * iH;

  const pts = recent.map((e, i) => `${toX(i)},${toY(e.brier)}`).join(' ');
  const threshY = toY(THRESHOLD);
  const endX = toX(recent.length - 1);
  const endY = toY(latest.brier);

  const consecutiveText = consecutiveAbove === 0
    ? 'Within target'
    : `${consecutiveAbove} consecutive week${consecutiveAbove > 1 ? 's' : ''} above threshold`;

  return (
    <section style={{
      background: 'var(--bg-card)', border: `1px solid ${borderColor}`,
      borderRadius: 14, padding: '20px', marginBottom: 18,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>P10.3 Brier alert</h3>
          <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.4 }}>
            Weekly Brier vs 0.22 threshold. Alert fires when above limit 2+ consecutive weeks.
          </p>
        </div>
        <span style={{
          fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 999, flexShrink: 0, marginLeft: 12,
          background: consecutiveAbove >= 2 ? 'rgba(239,68,68,0.12)' : consecutiveAbove === 1 ? 'rgba(202,138,4,0.12)' : 'rgba(22,163,74,0.12)',
          color: statusColor,
        }}>{statusLabel}</span>
      </div>

      <div style={{ display: 'flex', gap: 20, marginBottom: 10, fontSize: 13, flexWrap: 'wrap' }}>
        <div>
          <span style={{ color: 'var(--text-muted)' }}>Latest ({latest.week}):</span>{' '}
          <strong style={{ fontFamily: 'ui-monospace, monospace', color: latest.brier > THRESHOLD ? '#ef4444' : '#16a34a' }}>
            {latest.brier.toFixed(3)}
          </strong>
          <span style={{ color: 'var(--text-muted)', marginLeft: 6 }}>
            — {latest.brier > THRESHOLD ? 'above' : 'below'} {THRESHOLD} limit
          </span>
        </div>
        <div style={{ color: consecutiveAbove === 0 ? '#16a34a' : statusColor }}>
          {consecutiveText}
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}>
        {/* Dashed threshold line at 0.22 */}
        <line x1={PAD.left} y1={threshY} x2={W - PAD.right} y2={threshY}
          stroke="rgba(239,68,68,0.5)" strokeWidth="1" strokeDasharray="4,3" />
        <polyline points={pts} fill="none" stroke={statusColor} strokeWidth="2" strokeLinejoin="round" />
        <circle cx={endX} cy={endY} r="4" fill={statusColor} stroke="white" strokeWidth="2" />
        {recent.map((e, i) => (
          <text key={i} x={toX(i)} y={H - 4} textAnchor="middle"
            fontSize="9" fill="var(--text-faint)" fontFamily="ui-monospace, monospace">
            {e.week.slice(-3)}
          </text>
        ))}
      </svg>
    </section>
  );
}

// ---------------------------------------------------------------------------
// KillSwitchCriteriaCard — checklist of conditions the operator should verify
// before removing the kill switch manually. Invisible when kill switch is off.
// ---------------------------------------------------------------------------
function KillSwitchCriteriaCard() {
  const M = useContext(DataContext);
  if (!M.stats.kill_switch) return null;

  const anomalyDetected = M.anomalyStatus?.anomaly_detected;
  const drawdownTier = M.stats.drawdown_tier;
  const brier = M.stats.brier;

  const allPass = anomalyDetected === false && drawdownTier === 'TIER_1' && brier != null && brier < 0.35;

  const checks = [
    {
      label: 'Anomaly clear',
      icon: anomalyDetected === false ? '✓' : anomalyDetected === true ? '✗' : '?',
      color: anomalyDetected === false ? '#16a34a' : anomalyDetected === true ? '#ef4444' : '#8b949e',
      rowBg: anomalyDetected === false ? 'rgba(22,163,74,0.06)' : anomalyDetected === true ? 'rgba(239,68,68,0.06)' : 'var(--bg-subtle)',
    },
    {
      label: 'Drawdown TIER_1',
      icon: drawdownTier === 'TIER_1' ? '✓' : drawdownTier == null ? '?' : '✗',
      color: drawdownTier === 'TIER_1' ? '#16a34a' : drawdownTier == null ? '#8b949e' : '#ca8a04',
      rowBg: drawdownTier === 'TIER_1' ? 'rgba(22,163,74,0.06)' : drawdownTier == null ? 'var(--bg-subtle)' : 'rgba(202,138,4,0.06)',
    },
    {
      label: 'Brier below 0.35',
      icon: brier == null ? '?' : brier < 0.35 ? '✓' : '✗',
      color: brier == null ? '#8b949e' : brier < 0.35 ? '#16a34a' : '#ef4444',
      rowBg: brier == null ? 'var(--bg-subtle)' : brier < 0.35 ? 'rgba(22,163,74,0.06)' : 'rgba(239,68,68,0.06)',
    },
  ];

  return (
    <section style={{
      background: 'var(--bg-card)',
      border: `1px solid ${allPass ? 'rgba(22,163,74,0.4)' : 'rgba(245,158,11,0.3)'}`,
      borderRadius: 14, padding: '20px', marginBottom: 18,
    }}>
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Kill switch removal criteria</h3>
      <p style={{ margin: '0 0 14px', color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.4 }}>
        Conditions to verify before removing the kill switch manually.
      </p>
      <div style={{ display: 'grid', gap: 10 }}>
        {checks.map(c => (
          <div key={c.label} style={{
            display: 'flex', alignItems: 'center', gap: 12,
            padding: '10px 14px', borderRadius: 8, background: c.rowBg,
          }}>
            <span style={{
              width: 24, height: 24, borderRadius: '50%', flexShrink: 0,
              background: c.color === '#16a34a' ? 'rgba(22,163,74,0.15)'
                : c.color === '#ef4444' ? 'rgba(239,68,68,0.15)'
                : c.color === '#ca8a04' ? 'rgba(202,138,4,0.15)'
                : 'rgba(139,148,158,0.15)',
              color: c.color, fontSize: 13, fontWeight: 700,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>{c.icon}</span>
            <span style={{ fontSize: 13, fontWeight: 500 }}>{c.label}</span>
            <span style={{ fontSize: 11, color: c.color, marginLeft: 'auto' }}>
              {c.icon === '✓' ? 'Pass' : c.icon === '✗' ? 'Fail' : 'Unknown'}
            </span>
          </div>
        ))}
      </div>
      <p style={{ margin: '12px 0 0', fontSize: 11, color: 'var(--text-faint)', lineHeight: 1.5 }}>
        Meeting these conditions does not auto-remove the kill switch — run{' '}
        <code style={{ background: 'var(--bg-subtle)', padding: '1px 4px', borderRadius: 3 }}>
          py main.py admin kill-switch off
        </code>{' '}
        manually.
      </p>
    </section>
  );
}

export default function RiskTab() {
  const M = useContext(DataContext);
  const totalCost = M.positions.reduce((a, p) => a + p.cost, 0);
  const balance = M.stats.balance;
  const heatPct = balance > 0 ? ((totalCost / balance) * 100).toFixed(0) : 0;
  // Guard against division by zero when there are no open positions
  const biasTotal = (M.directionalBias.yes || 0) + (M.directionalBias.no || 0);
  const bullishPct = biasTotal > 0 ? ((M.directionalBias.yes / biasTotal) * 100).toFixed(0) : null;

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

      {M.stats.var_95 != null && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12, marginBottom: 18 }}>
          <StatCard label="VaR 95%" tooltip="5th-percentile P&L from Monte Carlo — 95% of days should lose less than this."
            value={(M.stats.var_95 >= 0 ? '' : '-') + '$' + Math.abs(M.stats.var_95).toFixed(2)}
            sub="daily loss estimate" deltaTone="neg" />
          <StatCard label="VaR 99%" tooltip="1st-percentile P&L from Monte Carlo — 99% of days should lose less than this."
            value={(M.stats.var_99 >= 0 ? '' : '-') + '$' + Math.abs(M.stats.var_99).toFixed(2)}
            sub="daily loss estimate" deltaTone="neg" />
        </div>
      )}

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
            {bullishPct != null ? `${bullishPct}% bullish bias` : 'No open positions'}
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

      {/* Circuit breakers — data source health */}
      {M.circuitBreakers && M.circuitBreakers.length > 0 && (
        <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 14 }}>Data source health</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 10 }}>
            {M.circuitBreakers.map(cb => {
              const isOpen = cb.state === 'open';
              return (
                <div key={cb.key} style={{
                  padding: '12px 14px', borderRadius: 10,
                  background: isOpen ? 'rgba(239,68,68,0.06)' : 'var(--bg-subtle)',
                  border: `1px solid ${isOpen ? 'rgba(239,68,68,0.3)' : 'var(--border)'}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <span style={{ fontSize: 12, fontWeight: 600 }}>{cb.label}</span>
                    <span style={{
                      fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 999,
                      background: isOpen ? 'rgba(239,68,68,0.12)' : 'rgba(34,197,94,0.12)',
                      color: isOpen ? '#ef4444' : '#16a34a',
                    }}>{isOpen ? 'OPEN' : 'CLOSED'}</span>
                  </div>
                  <div style={{ display: 'flex', gap: 12, fontSize: 11, color: 'var(--text-muted)' }}>
                    <span>{cb.failures} fail{cb.failures !== 1 ? 's' : ''}</span>
                    {cb.latency_ms != null && <span>{cb.latency_ms}ms</span>}
                    {isOpen && cb.retry_in_s > 0 && <span style={{ color: '#f59e0b' }}>retry in {cb.retry_in_s}s</span>}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Anomaly detection window — win-rate collapse monitor */}
      {M.anomalyStatus && (
        <section style={{
          background: 'var(--bg-card)',
          border: `1px solid ${M.anomalyStatus.should_halt ? '#ef4444' : M.anomalyStatus.anomaly_detected ? '#f59e0b' : 'var(--border)'}`,
          borderRadius: 14, padding: '20px', marginBottom: 18,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
            <div>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Anomaly detection window</h3>
              <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.4 }}>
                Last {M.anomalyStatus.n} multi-day settlements. Halts at &lt;{(M.anomalyStatus.halt_threshold * 100).toFixed(0)}% win rate (min {M.anomalyStatus.min_samples} settled).
              </p>
            </div>
            {M.anomalyStatus.should_halt
              ? <span style={{ fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 999, background: 'rgba(239,68,68,0.12)', color: '#ef4444' }}>HALT TRIGGERED</span>
              : M.anomalyStatus.anomaly_detected
                ? <span style={{ fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 999, background: 'rgba(245,158,11,0.12)', color: '#f59e0b' }}>ANOMALY</span>
                : M.anomalyStatus.active
                  ? <span style={{ fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 999, background: 'rgba(34,197,94,0.12)', color: '#16a34a' }}>NORMAL</span>
                  : <span style={{ fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 999, background: 'var(--bg-muted)', color: 'var(--text-faint)' }}>INACTIVE</span>
            }
          </div>

          {/* Win rate progress bar */}
          {M.anomalyStatus.active && M.anomalyStatus.win_rate != null && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                <span style={{ fontWeight: 600 }}>
                  Win rate: {(M.anomalyStatus.win_rate * 100).toFixed(0)}%
                  &nbsp;({M.anomalyStatus.wins}W / {M.anomalyStatus.losses}L)
                </span>
                <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-muted)' }}>
                  halt threshold: {(M.anomalyStatus.halt_threshold * 100).toFixed(0)}%
                </span>
              </div>
              <div style={{ height: 8, background: 'var(--bg-muted)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{
                  width: (M.anomalyStatus.win_rate * 100) + '%', height: '100%',
                  background: M.anomalyStatus.win_rate < M.anomalyStatus.halt_threshold ? '#ef4444'
                    : M.anomalyStatus.win_rate < 0.40 ? '#f59e0b' : '#16a34a',
                  transition: 'width 0.4s',
                }} />
              </div>
            </div>
          )}
          {!M.anomalyStatus.active && (
            <p style={{ fontSize: 12, color: 'var(--text-faint)', fontStyle: 'italic', marginBottom: 14 }}>
              Needs {M.anomalyStatus.min_samples} settled multi-day trades in the window to activate.
            </p>
          )}

          {/* Trade window list */}
          {M.anomalyStatus.window_trades.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {M.anomalyStatus.window_trades.map((t, i) => (
                <div key={i} style={{
                  padding: '4px 9px', borderRadius: 6, fontSize: 11, fontFamily: 'ui-monospace, monospace',
                  background: t.won ? 'rgba(34,197,94,0.10)' : 'rgba(239,68,68,0.10)',
                  color: t.won ? '#16a34a' : '#ef4444',
                  border: `1px solid ${t.won ? 'rgba(34,197,94,0.25)' : 'rgba(239,68,68,0.25)'}`,
                }}>
                  {t.ticker.split('-').slice(-2).join('-')} {t.won ? 'W' : 'L'}{t.pnl != null ? ` ${t.pnl > 0 ? '+' : ''}${t.pnl.toFixed(2)}` : ''}
                </div>
              ))}
            </div>
          )}

          {M.anomalyStatus.anomaly_messages.length > 0 && (
            <div style={{ marginTop: 10, padding: '8px 12px', borderRadius: 8, background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.2)' }}>
              {M.anomalyStatus.anomaly_messages.map((msg, i) => (
                <div key={i} style={{ fontSize: 12, color: '#92400e' }}>{msg}</div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* Scan filter breakdown — how many markets each gate rejected in the last cron scan */}
      {M.scanStats && (M.scanStats.total_scanned > 0 || Object.keys(M.scanStats.filters).length > 0) && (
        <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Scan filter breakdown</h3>
          <p style={{ margin: '0 0 16px', color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.4 }}>
            {M.scanStats.total_scanned} markets scanned last run. Bars show how many were rejected at each gate.
          </p>
          {(() => {
            const FILTER_LABELS = {
              no_analysis:  'No analysis',
              same_day:     'Same-day (info)',
              mkt_prob:     'Mkt prob gate',
              divergence:   'Divergence gate',
              net_edge:     'Net edge gate',
              prob_edge:    'Prob edge gate',
              passed:       'Passed all gates',
            };
            const allEntries = [
              ...Object.entries(M.scanStats.filters),
              ...Object.entries(M.scanStats.gate_counts),
            ];
            const maxVal = Math.max(1, ...allEntries.map(([, v]) => v));
            return (
              <div style={{ display: 'grid', gap: 8 }}>
                {allEntries.map(([key, val]) => (
                  <div key={key}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                      <span style={{ fontWeight: 500, color: key === 'passed' ? '#16a34a' : 'var(--text-default)' }}>
                        {FILTER_LABELS[key] ?? key}
                      </span>
                      <span style={{ fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)' }}>{val}</span>
                    </div>
                    <div style={{ height: 6, background: 'var(--bg-muted)', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{
                        width: (val / maxVal) * 100 + '%', height: '100%',
                        background: key === 'passed' ? '#16a34a' : key === 'same_day' ? '#3b82f6' : '#6366f1',
                      }} />
                    </div>
                  </div>
                ))}
              </div>
            );
          })()}
        </section>
      )}

      {/* P10.3 Brier degradation alert — sparkline + consecutive-weeks counter */}
      <BrierAlertCard />

      {/* Kill switch removal criteria — only visible when kill switch is active */}
      <KillSwitchCriteriaCard />

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
