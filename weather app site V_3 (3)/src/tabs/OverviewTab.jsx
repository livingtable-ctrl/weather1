import React, { useContext } from 'react';
import { DataContext } from '../DataContext.js';
import { normCity, StatCard, BalanceSparkline, SystemEventsCard } from '../shared.jsx';

// ---------------------------------------------------------------------------
// LastSettlementBatch — compact inline summary of the most recently settled
// batch. Groups by target_date (observation day) so a single cron settlement
// run appears as one batch instead of spread across entered_at times.
// ---------------------------------------------------------------------------
function LastSettlementBatch() {
  const M = useContext(DataContext);

  const settled = (M.closedTrades || []).filter(t => t.target_date);
  if (settled.length < 2) return null;

  const sortedDates = [...new Set(settled.map(t => t.target_date))].sort();
  const latestDate = sortedDates[sortedDates.length - 1];
  const batch = settled.filter(t => t.target_date === latestDate);

  // Single-trade batches aren't meaningful to summarize
  if (batch.length < 2) return null;

  const wins = batch.filter(t => t.pnl > 0).length;
  const losses = batch.filter(t => t.pnl <= 0).length;
  const netPnl = batch.reduce((s, t) => s + (t.pnl || 0), 0);

  // Append T12:00:00Z so the date parses in UTC and doesn't shift by timezone
  const label = new Date(latestDate + 'T12:00:00Z')
    .toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

  return (
    <div style={{
      display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap',
      padding: '12px 18px', background: 'var(--bg-card)',
      border: '1px solid var(--border)', borderRadius: 10, marginBottom: 18, fontSize: 13,
    }}>
      <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>Last settlement · {label}</span>
      <span style={{ color: '#16a34a', fontWeight: 600 }}>{wins}W</span>
      <span style={{ color: '#ef4444', fontWeight: 600 }}>{losses}L</span>
      <span style={{
        fontFamily: 'ui-monospace, monospace', fontWeight: 700,
        color: netPnl >= 0 ? '#16a34a' : '#ef4444',
      }}>
        {netPnl >= 0 ? '+' : ''}{netPnl.toFixed(2)}
      </span>
      <span style={{ color: 'var(--text-faint)', fontSize: 11 }}>
        {batch.length} trade{batch.length !== 1 ? 's' : ''}
      </span>
    </div>
  );
}

export default function OverviewTab() {
  const M = useContext(DataContext);
  const s = M.stats;
  const grad = s.graduation;
  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
  const pnlToday = s.today_pnl;
  const pnlKnown = pnlToday != null;
  const unrealizedPnl = M.positions.reduce((sum, p) => {
    const entryPerCt = p.cost / p.qty;
    return sum + (p.mark - entryPerCt) * p.qty;
  }, 0);

  // Compute alert states here so we can render a top-of-page banner — both
  // conditions are operationally critical and easy to miss if only in RiskTab.
  const killSwitchActive = s.kill_switch;
  const BRIER_THRESHOLD = 0.22;
  const recentBrier = (M.brierHistory || []).slice(-6);
  let consecutiveBrierAbove = 0;
  for (let i = recentBrier.length - 1; i >= 0; i--) {
    if (recentBrier[i].brier > BRIER_THRESHOLD) consecutiveBrierAbove++;
    else break;
  }
  const brierAlertFiring = consecutiveBrierAbove >= 1;

  return (
    <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
      <div style={{ marginBottom: 18 }}>
        <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 500, marginBottom: 3 }}>{today}</div>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, letterSpacing: '-0.025em', fontFamily: "'Source Serif 4', Georgia, serif" }}>
          {!pnlKnown
            ? <>{s.open_count} positions open{grad.ready ? ' — graduation gate cleared.' : '.'}</>
            : pnlToday >= 0
              ? <>Up <span style={{ color: '#16a34a' }}>+${Number(pnlToday).toFixed(2)}</span> today — {s.open_count} positions open{grad.ready ? ', graduation gate cleared.' : '.'}</>
              : <>Down <span style={{ color: '#ef4444' }}>-${Math.abs(Number(pnlToday)).toFixed(2)}</span> today — {s.open_count} positions open.</>
          }
        </h1>
        {M.positions.length > 0 && (
          <p style={{ margin: '6px 0 0', fontSize: 13, color: unrealizedPnl >= 0 ? '#16a34a' : '#ef4444' }}>
            {unrealizedPnl >= 0 ? '+' : ''}{unrealizedPnl.toFixed(2)} unrealized P&amp;L across {M.positions.length} open positions
          </p>
        )}
      </div>

      {/* Alert banner — kill switch and/or Brier degradation. Shown here so
          critical alerts are visible without navigating to RiskTab. */}
      {(killSwitchActive || brierAlertFiring) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
          {killSwitchActive && (
            <div style={{
              padding: '10px 16px', borderRadius: 9,
              background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.35)',
              color: '#ef4444', fontSize: 13, fontWeight: 600,
            }}>
              ⛔ Kill switch active — all new trades halted. Run{' '}
              <code style={{ background: 'rgba(239,68,68,0.08)', padding: '1px 5px', borderRadius: 3, fontWeight: 400 }}>
                py main.py cron
              </code>{' '}
              to override for one cycle.
            </div>
          )}
          {brierAlertFiring && (
            <div style={{
              padding: '10px 16px', borderRadius: 9,
              background: 'rgba(202,138,4,0.07)', border: '1px solid rgba(202,138,4,0.35)',
              color: '#92400e', fontSize: 13, fontWeight: 600,
            }}>
              ⚠ P10.3 Brier alert —{' '}
              {consecutiveBrierAbove} consecutive week{consecutiveBrierAbove > 1 ? 's' : ''} above 0.22 threshold.{' '}
              <span style={{ fontWeight: 400 }}>See Risk tab for details.</span>
            </div>
          )}
        </div>
      )}

      {/* KPI row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 12 }}>
        <StatCard label="Paper balance" tooltip="Simulated cash balance in the paper-trading sandbox. No real money."
          value={'$' + Number(s.balance).toFixed(2)}
          delta={(s.balance >= s.starting_balance ? '+' : '') + ((Number(s.balance) - Number(s.starting_balance)) / Number(s.starting_balance) * 100).toFixed(1) + '%'}
          deltaTone={s.balance >= s.starting_balance ? 'pos' : 'neg'}
          sub={'from $' + Number(s.starting_balance).toFixed(2) + ' start'} />
        <StatCard label="Open positions" tooltip="Active contracts that haven't expired or been closed yet."
          value={s.open_count} sub={s.settled_count + ' settled so far'} />
        <StatCard label="Win rate" tooltip="% of settled trades that were profitable."
          value={s.win_rate != null ? (s.win_rate * 100).toFixed(1) + '%' : '—'} />
        <StatCard label="Brier score" tooltip="Forecast quality (0=perfect, 0.25=random). Lower is better. Target ≤0.20."
          value={s.brier != null ? Number(s.brier).toFixed(3) : '—'}
          deltaTone="pos" sub="target ≤0.20" />
      </div>

      {/* Drawdown risk row — peak, halt floor, current drawdown, Kelly scaling, tier */}
      {(() => {
        const tier = s.drawdown_tier ?? 'TIER_1';
        const tierColor = tier === 'HALTED' ? '#ef4444'
          : tier === 'TIER_1' ? '#16a34a'
          : '#ca8a04';
        return (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 18 }}>
            <StatCard label="Peak balance"
              tooltip="Highest balance reached — used to measure drawdown percentage."
              value={s.peak_balance != null ? '$' + Number(s.peak_balance).toFixed(2) : '—'} />
            <StatCard label="Halt floor"
              tooltip="80% of peak balance. Bot halts all trading if balance falls below this level."
              value={s.halt_floor != null ? '$' + Number(s.halt_floor).toFixed(2) : '—'} />
            <StatCard label="Drawdown"
              tooltip="Current balance vs peak. Tiers reduce Kelly at 5%, 10%, 15%, and 20% drawdown."
              value={s.drawdown_pct != null ? Number(s.drawdown_pct).toFixed(1) + '%' : '—'}
              deltaTone={s.drawdown_pct != null && s.drawdown_pct > 5 ? 'neg' : null} />
            <StatCard label="Kelly factor"
              tooltip="Current fraction of full Kelly used for position sizing. Reduced during drawdowns."
              value={s.kelly_factor != null ? (Number(s.kelly_factor) * 100).toFixed(0) + '%' : '—'} />
            <div style={{
              background: 'var(--bg-card)', border: '1px solid var(--border)',
              borderRadius: 12, padding: '14px 16px',
            }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 500, marginBottom: 6 }}>
                Drawdown tier
              </div>
              <div style={{ fontSize: 20, fontWeight: 700, color: tierColor, letterSpacing: '-0.01em' }}>
                {tier}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 4 }}>
                {tier === 'TIER_1' ? 'Full Kelly' : tier === 'TIER_2' ? '70% Kelly' : tier === 'TIER_3' ? '30% Kelly' : tier === 'TIER_4' ? '10% Kelly' : 'Trading halted'}
              </div>
            </div>
          </div>
        );
      })()}

      {/* Graduation gates */}
      <section style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 14, padding: '20px', marginBottom: 18,
      }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Graduation progress</h3>
        <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 16, lineHeight: 1.4 }}>
          Three gates to go live: 30+ trades, $50+ P&L, Brier ≤0.20.{' '}
          {grad.ready ? '✓ All gates cleared!' : 'Keep building track record…'}
        </p>
        <div style={{ display: 'grid', gap: 14 }}>
          {[
            { label: 'Trades',  current: grad.trades_done, target: grad.trades_target, unit: '',  invert: false, complete: grad.trades_done >= grad.trades_target },
            { label: 'P&L',    current: grad.total_pnl,   target: grad.pnl_target,    unit: '$', invert: false, complete: grad.total_pnl >= grad.pnl_target },
            { label: 'Brier',  current: grad.brier,       target: grad.brier_target,  unit: '',  invert: true,  complete: grad.brier <= grad.brier_target },
          ].map((g) => {
            const pct = g.invert
              ? Math.min(100, Math.max(0, (1 - g.current / 0.25) * 100))
              : Math.min(100, Math.max(0, (g.current / g.target) * 100));
            return (
              <div key={g.label}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                  <span style={{ fontWeight: 600 }}>{g.label}</span>
                  <span style={{ fontFamily: 'ui-monospace, monospace', color: g.complete ? '#16a34a' : 'var(--text-muted)' }}>
                    {g.unit}{g.invert ? g.current.toFixed(3) : (g.unit === '$' ? g.current.toFixed(2) : Math.round(g.current))}/{g.unit}{g.target}
                  </span>
                </div>
                <div style={{ height: 8, background: 'var(--bg-muted)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ width: pct + '%', height: '100%', background: g.complete ? '#16a34a' : '#3b82f6', transition: 'width 0.4s' }} />
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Fear/Greed + Data sources */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 12, marginBottom: 18 }}>
        <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px' }}>
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

        <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px' }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 14 }}>Data sources</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 9 }}>
            {M.circuitBreakers.map((cb) => {
              const isOpen = cb.state === 'open';
              return (
                <div key={cb.key} style={{
                  padding: '9px 11px', borderRadius: 8, background: 'var(--bg-subtle)',
                  border: '1px solid ' + (isOpen ? '#ef4444' : 'var(--border)'),
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: isOpen ? '#ef4444' : '#16a34a', display: 'inline-block' }} />
                    <span style={{ fontSize: 11, fontWeight: 600 }}>{cb.label}</span>
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-faint)', fontFamily: 'ui-monospace, monospace' }}>
                    {isOpen ? `Retry ${cb.retry_in_s}s` : cb.latency_ms != null ? `${cb.latency_ms}ms` : 'OK'}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>

      {/* Summary cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
        {[
          { title: 'Open Positions',    count: M.positions.length,         desc: 'View all with detail' },
          { title: 'Top Opportunities', count: M.opportunities.length,     desc: 'Signals with edge' },
          { title: 'Closed Trades',     count: M.closedTrades.length,      desc: (() => { const w = M.closedTrades.filter(t => t.pnl > 0).length; const l = M.closedTrades.filter(t => t.pnl != null && t.pnl < 0).length; return M.closedTrades.length ? `${w}W / ${l}L` : 'History & P&L'; })() },
          { title: 'Forecast Quality',  count: Object.keys(M.cityBrier).length, desc: 'Cities tracked' },
        ].map((card) => (
          <section key={card.title} style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 14, padding: '18px 20px',
          }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>{card.title}</h3>
            <div style={{ fontSize: 24, fontWeight: 700, color: '#3b82f6', marginBottom: 6 }}>{card.count}</div>
            <div style={{ color: 'var(--text-faint)', fontSize: 12 }}>{card.desc}</div>
          </section>
        ))}
      </div>

      {/* Balance history sparkline */}
      <BalanceSparkline hist={M.balanceHist} />

      {/* Most recent settlement batch — W/L/PnL summary grouped by target_date */}
      <LastSettlementBatch />

      {/* System events feed */}
      <SystemEventsCard alerts={M.alerts} />
    </main>
  );
}
