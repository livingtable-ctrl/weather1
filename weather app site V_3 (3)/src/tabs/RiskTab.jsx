import React, { useContext } from 'react';
import { DataContext } from '../DataContext.js';
import { authHeader } from '../useData.js';
import { StatCard } from '../shared.jsx';

export default function RiskTab() {
  const M = useContext(DataContext);
  const totalCost = M.positions.reduce((a, p) => a + p.cost, 0);
  const balance = M.stats.balance;
  const heatPct = balance > 0 ? ((totalCost / balance) * 100).toFixed(0) : 0;

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
            {((M.directionalBias.yes / (M.directionalBias.yes + M.directionalBias.no)) * 100).toFixed(0)}% bullish bias
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
