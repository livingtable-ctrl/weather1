import React, { useState, useEffect, useContext, useMemo } from 'react';
import { DataContext } from '../DataContext.js';
import { authHeader } from '../useData.js';
import { normCity } from '../shared.jsx';

export default function SignalsTab() {
  const M = useContext(DataContext);
  const [minEdge, setMinEdge] = useState(5);
  const [selectedOpp, setSelectedOpp] = useState(null);
  const [actionMsg, setActionMsg] = useState('');
  const [qtyMap, setQtyMap] = useState({});
  const [confirmPending, setConfirmPending] = useState(null); // {opp, qty}
  const PLACED_KEY = 'kalshi-placed-signals';
  const [placedSet, setPlacedSet] = useState(() => {
    try { return new Set(JSON.parse(sessionStorage.getItem(PLACED_KEY) || '[]')); }
    catch { return new Set(); }
  });

  // Missing state that was referenced but never declared in the original file
  const [expandedId, setExpandedId] = useState(null);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [bulkActionMsg, setBulkActionMsg] = useState('');

  // Show every candidate the bot evaluated — no edge filter.
  // passes_threshold comes from the backend (cron.py gate logic).
  // The slider is a secondary visual highlight for manual exploration.
  const filtered = useMemo(() => M.opportunities, [M.opportunities]);
  const sameDayOpps  = useMemo(() => filtered.filter(o => (o.days_out ?? 1) === 0), [filtered]);
  const multiDayOpps = useMemo(() => filtered.filter(o => (o.days_out ?? 1) > 0),  [filtered]);

  useEffect(() => {
    const handler = () => { setSelectedOpp(null); setConfirmPending(null); };
    document.addEventListener('kalshi:escape', handler);
    return () => document.removeEventListener('kalshi:escape', handler);
  }, []);

  function handleAction(opp, action) {
    if (action === 'reject') {
      setActionMsg(`✗ ${opp.ticker} rejected`);
      setTimeout(() => setActionMsg(''), 2500);
      return;
    }
    // approve → show confirmation dialog first
    const mp = (opp.market_prob || 0) / 100;
    const qty = parseInt(qtyMap[opp.ticker] ?? (opp.kelly_qty || (opp.kelly_dollars > 0 && mp > 0 ? Math.max(1, Math.floor(opp.kelly_dollars / mp)) : 1)) ?? 1, 10) || 1;
    setConfirmPending({ opp, qty });
  }

  function handleConfirm() {
    if (!confirmPending) return;
    const { opp, qty } = confirmPending;
    setConfirmPending(null);
    fetch('/api/paper-order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader() },
      body: JSON.stringify({
        ticker:      opp.ticker,
        side:        (opp.side || 'yes').toLowerCase(),
        quantity:    qty,
        entry_price: opp.market_prob != null ? opp.market_prob / 100 : 0.5,
        entry_prob:  opp.forecast_prob != null ? opp.forecast_prob / 100 : null,
        net_edge:    opp.edge_pct != null ? opp.edge_pct / 100 : null,
        city:        opp.city || null,
        target_date: opp.target_date || opp.expiry || null,
        days_out:    opp.days_out ?? null,
      }),
    })
      .then(r => r.json())
      .then(d => {
        setActionMsg(d.error ? `✗ ${d.error}` : `✓ ${opp.ticker} placed`);
        setTimeout(() => setActionMsg(''), 3000);
        if (!d.error) {
          const key = `${opp.ticker}|${opp.target_date || opp.expiry || ''}`;
          setPlacedSet(prev => {
            const next = new Set([...prev, key]);
            try { sessionStorage.setItem(PLACED_KEY, JSON.stringify([...next])); } catch {}
            return next;
          });
          M.refresh();
        }
      })
      .catch(() => {
        setActionMsg(`✗ Request failed`);
        setTimeout(() => setActionMsg(''), 3000);
      });
  }

  // Bulk approve: place a paper order for each selected signal
  function handleBulkApprove() {
    if (selectedIds.size === 0) return;
    const oppsToApprove = filtered.filter(o => selectedIds.has(o.ticker));
    setBulkActionMsg(`Placing ${oppsToApprove.length} orders...`);

    Promise.all(oppsToApprove.map(opp => {
      const mp = (opp.market_prob || 0) / 100;
      const qty = parseInt(qtyMap[opp.ticker] ?? (opp.kelly_qty || (opp.kelly_dollars > 0 && mp > 0 ? Math.max(1, Math.floor(opp.kelly_dollars / mp)) : 1)) ?? 1, 10) || 1;
      return fetch('/api/paper-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeader() },
        body: JSON.stringify({
          ticker:      opp.ticker,
          side:        (opp.side || 'yes').toLowerCase(),
          quantity:    qty,
          entry_price: opp.market_prob != null ? opp.market_prob / 100 : 0.5,
          entry_prob:  opp.forecast_prob != null ? opp.forecast_prob / 100 : null,
          net_edge:    opp.edge_pct != null ? opp.edge_pct / 100 : null,
          city:        opp.city || null,
          target_date: opp.target_date || opp.expiry || null,
          days_out:    opp.days_out ?? null,
        }),
      }).then(r => r.json());
    })).then(() => {
      setBulkActionMsg(`✓ Placed ${oppsToApprove.length} orders`);
      setSelectedIds(new Set());
      M.refresh();
      setTimeout(() => setBulkActionMsg(''), 3000);
    }).catch(() => {
      setBulkActionMsg('✗ Bulk approve failed');
      setTimeout(() => setBulkActionMsg(''), 3000);
    });
  }

  // Bulk reject: just clear the selection and show a message
  function handleBulkReject() {
    const count = selectedIds.size;
    setSelectedIds(new Set());
    setBulkActionMsg(`✗ Rejected ${count} signal${count !== 1 ? 's' : ''}`);
    setTimeout(() => setBulkActionMsg(''), 2500);
  }

  // Shared row renderer — used by both Same-Day and Multi-Day sections.
  // Defined inside the component so it closes over state (expandedId, selectedIds, etc.)
  // without needing to thread them as props.
  function renderRows(opps) {
    return opps.map((o, i) => {
      const side = o.side.toLowerCase();
      const stars = o.stars || '★';
      const starColor = stars.length >= 2 ? '#16a34a' : stars.length === 1 ? '#ca8a04' : 'var(--text-faint)';
      const kelly = o.kelly_dollars > 0 ? '$' + o.kelly_dollars.toFixed(2) : '—';
      const placed = placedSet.has(`${o.ticker}|${o.target_date || o.expiry || ''}`);
      const isExpanded = expandedId === o.ticker;
      const belowThreshold = o.passes_threshold === false || (o.passes_threshold === undefined && o.edge_pct < minEdge);
      return (
        <React.Fragment key={i}>
          <tr onClick={() => !placed && setExpandedId(isExpanded ? null : o.ticker)} style={{
            borderBottom: isExpanded ? 'none' : '1px solid var(--bg-muted)',
            cursor: placed ? 'default' : 'pointer',
            opacity: placed ? 0.4 : belowThreshold ? 0.55 : 1,
            pointerEvents: placed ? 'none' : 'auto',
            background: isExpanded ? 'var(--bg-subtle)' : o.already_held ? 'rgba(59,130,246,0.04)' : 'transparent',
          }}>
            <td style={{ padding: '14px 16px', textAlign: 'center' }} onClick={e => e.stopPropagation()}>
              <input type="checkbox" checked={selectedIds.has(o.ticker)}
                onChange={(e) => { const next = new Set(selectedIds); if (e.target.checked) next.add(o.ticker); else next.delete(o.ticker); setSelectedIds(next); }}
                style={{ cursor: 'pointer' }} />
            </td>
            <td style={{ padding: '12px 16px', color: starColor, letterSpacing: 1 }}>{stars}</td>
            <td style={{ padding: '12px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#3b82f6' }}>{o.ticker}</td>
            <td style={{ padding: '12px 16px', fontWeight: 600 }}>{normCity(o.city)}</td>
            <td style={{ padding: '12px 16px' }}>
              <span style={{ display: 'inline-block', padding: '2px 8px', borderRadius: 999, background: side === 'yes' ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)', color: side === 'yes' ? '#16a34a' : '#ef4444', fontSize: 10, fontWeight: 600, textTransform: 'uppercase' }}>{side}</span>
            </td>
            <td style={{ padding: '12px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)' }}>{o.forecast_prob.toFixed(1)}%</td>
            <td style={{ padding: '12px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)' }}>{o.market_prob.toFixed(1)}%</td>
            <td style={{ padding: '12px 16px', textAlign: 'right', color: '#16a34a', fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>+{o.edge_pct.toFixed(1)}%</td>
            <td style={{ padding: '12px 16px' }}>
              <span style={{ display: 'inline-block', padding: '2px 8px', borderRadius: 999, fontSize: 10, fontWeight: 600, background: o.time_risk === 'LOW' ? 'rgba(34,197,94,0.12)' : o.time_risk === 'MEDIUM' ? 'rgba(234,179,8,0.12)' : 'rgba(239,68,68,0.12)', color: o.time_risk === 'LOW' ? '#16a34a' : o.time_risk === 'MEDIUM' ? '#ca8a04' : '#ef4444' }}>{o.time_risk}</span>
            </td>
            <td style={{ padding: '12px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)', fontSize: 12 }}>{kelly}</td>
            <td style={{ padding: '12px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-muted)' }}>
              {(() => {
                const td = o.target_date || o.expiry;
                if (!td) return '—';
                // Use server-computed days_out when available — avoids timezone skew where
                // the browser's local date (US evening) lags UTC and reports same-day
                // markets as "(1d)" even though the server correctly classified them as 0.
                const daysOut = o.days_out != null
                  ? o.days_out
                  : Math.ceil((new Date(td) - new Date(new Date().toDateString())) / 86400000);
                const label = daysOut === 0 ? 'today' : `${daysOut}d`;
                const color = daysOut === 0 ? '#16a34a' : daysOut <= 1 ? '#f59e0b' : daysOut <= 3 ? 'var(--text-muted)' : 'var(--text-faint)';
                return <span style={{ color }}>{td} <span style={{ fontSize: 10 }}>({label})</span></span>;
              })()}
            </td>
            <td style={{ padding: '12px 16px', fontSize: 13 }}>
              {belowThreshold && <span title={`Edge ${o.edge_pct.toFixed(1)}% below ${minEdge}% threshold`} style={{ display: 'inline-block', padding: '1px 6px', borderRadius: 999, marginRight: 4, background: 'rgba(100,116,139,0.12)', color: 'var(--text-muted)', fontSize: 10, fontWeight: 600 }}>LOW EDGE</span>}
              {o.near_threshold && <span title="Near threshold" style={{ color: '#ca8a04' }}>⚠ </span>}
              {o.is_hedge      && <span title="Hedges open position" style={{ color: 'var(--text-muted)' }}>↔ </span>}
              {o.already_held  && <span title="Already held" style={{ display: 'inline-block', padding: '1px 6px', borderRadius: 999, background: 'rgba(59,130,246,0.12)', color: '#3b82f6', fontSize: 10, fontWeight: 600 }}>HELD</span>}
              {!belowThreshold && !o.near_threshold && !o.is_hedge && !o.already_held && <span style={{ color: 'var(--text-faint)' }}>—</span>}
            </td>
            <td style={{ padding: '12px 16px' }} onClick={e => e.stopPropagation()}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                {(() => {
                  const mp = (o.market_prob || 0) / 100;
                  const kellyQty = o.kelly_qty || (o.kelly_dollars > 0 && mp > 0 ? Math.max(1, Math.floor(o.kelly_dollars / mp)) : 1);
                  return (<>
                    <input type="number" min="1" step="1" value={qtyMap[o.ticker] ?? kellyQty}
                      onChange={e => setQtyMap(prev => ({ ...prev, [o.ticker]: e.target.value }))}
                      title={`Kelly suggests ${kellyQty} contracts`}
                      style={{ width: 52, padding: '3px 5px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg-muted)', color: 'var(--text)', fontSize: 11, textAlign: 'center' }} />
                    <button onClick={() => (o.edge_pct || 0) > 0 && handleAction(o, 'approve')} disabled={(o.edge_pct || 0) <= 0} style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid #16a34a', background: 'rgba(34,197,94,0.08)', color: '#16a34a', fontSize: 11, fontWeight: 600, cursor: (o.edge_pct || 0) <= 0 ? 'not-allowed' : 'pointer', opacity: (o.edge_pct || 0) <= 0 ? 0.25 : 1 }}>✓</button>
                    <button onClick={() => handleAction(o, 'reject')} style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-muted)', fontSize: 11, fontWeight: 600, cursor: 'pointer' }}>✗</button>
                  </>);
                })()}
              </div>
            </td>
          </tr>
          {isExpanded && (
            <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
              <td colSpan="13" style={{ padding: '20px 24px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 16, marginBottom: 16 }}>
                  {[
                    { label: 'Edge',     value: '+' + o.edge_pct.toFixed(1) + '%', highlight: true },
                    { label: 'Forecast', value: o.forecast_prob.toFixed(1) + '%' },
                    { label: 'Market',   value: o.market_prob.toFixed(1) + '%' },
                    { label: 'Kelly $',  value: o.kelly_dollars > 0 ? '$' + o.kelly_dollars.toFixed(2) : '—' },
                    { label: 'Model',    value: o.model || '—' },
                    { label: 'Days Out', value: (() => { const td = o.target_date || o.expiry; if (!td) return '—'; return Math.ceil((new Date(td) - new Date()) / 86400000) + 'd'; })() },
                  ].map(item => (
                    <div key={item.label}>
                      <div style={{ color: 'var(--text-faint)', fontSize: 11, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{item.label}</div>
                      <div style={{ fontWeight: 600, fontSize: 15, fontFamily: 'ui-monospace, monospace', color: item.highlight ? '#16a34a' : 'inherit' }}>{item.value}</div>
                    </div>
                  ))}
                </div>
                <div style={{ padding: '12px', background: 'var(--bg-card)', borderRadius: 8, border: '1px solid var(--border)', fontSize: 12, color: 'var(--text-muted)' }}>
                  <strong>Market:</strong> {o.ticker} · <strong>Side:</strong> {o.side.toUpperCase()} · <strong>Risk:</strong> {o.time_risk}
                  {o.near_threshold && <span style={{ marginLeft: 12, color: '#ca8a04' }}>⚠ Near threshold</span>}
                  {o.is_hedge && <span style={{ marginLeft: 12 }}>↔ Hedges existing position</span>}
                </div>
              </td>
            </tr>
          )}
        </React.Fragment>
      );
    });
  }

  return (
    <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 18 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em' }}>Signals</h1>
          <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
            {filtered.length} candidate{filtered.length !== 1 ? 's' : ''} · {filtered.filter(o => o.passes_threshold !== false).length} above bot threshold
            {M.signalsMeta?.generatedAt && (() => {
              // Append 'Z' if the timestamp has no timezone info so browsers
              // treat it as UTC rather than local time (which would make
              // ageMs negative for US timezones and break the label).
              const ts = M.signalsMeta.generatedAt;
              const utcTs = (ts.endsWith('Z') || ts.includes('+')) ? ts : ts + 'Z';
              const ageMs = Date.now() - new Date(utcTs).getTime();
              const ageMin = Math.max(0, Math.round(ageMs / 60000));
              const isStale = M.signalsMeta.stale || ageMin > 90;
              const label = ageMin < 60 ? `${ageMin}m ago` : `${Math.round(ageMin / 60)}h ${ageMin % 60}m ago`;
              return (
                <span style={{ marginLeft: 10, color: isStale ? '#f59e0b' : 'var(--text-faint)', fontSize: 11 }}>
                  {isStale ? '⚠ ' : ''}Last scan: {label}
                </span>
              );
            })()}
          </p>
          <p style={{ margin: '6px 0 0', color: 'var(--text-muted)', fontSize: 12, maxWidth: 560, lineHeight: 1.5 }}>
            Each row is a market the bot would enter. Stars rank conviction. Click a row to expand; use Approve / Reject to act.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {actionMsg && (
            <span style={{ fontSize: 12, color: actionMsg.startsWith('✓') ? '#16a34a' : '#ef4444', fontWeight: 600 }}>{actionMsg}</span>
          )}
          <label style={{ fontSize: 13, color: 'var(--text-muted)' }}>Highlight threshold:</label>
          <input type="range" min="0" max="30" step="1" value={minEdge} onChange={e => setMinEdge(+e.target.value)} style={{ width: 120 }} />
          <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'ui-monospace, monospace', minWidth: 40 }}>{minEdge}%</span>
        </div>
      </div>

      {/* Bulk action bar */}
      {selectedIds.size > 0 && (
        <div style={{
          position: 'fixed', bottom: 20, left: '50%', transform: 'translateX(-50%)',
          background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 12,
          padding: '12px 20px', boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
          display: 'flex', gap: 16, alignItems: 'center', zIndex: 100,
        }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>{selectedIds.size} selected</span>
          <button onClick={handleBulkApprove} style={{
            padding: '6px 14px', borderRadius: 6, border: '1px solid #16a34a',
            background: 'rgba(34,197,94,0.08)', color: '#16a34a',
            fontSize: 12, fontWeight: 600, cursor: 'pointer',
          }}>✓ Approve All</button>
          <button onClick={handleBulkReject} style={{
            padding: '6px 14px', borderRadius: 6, border: '1px solid #ef4444',
            background: 'rgba(239,68,68,0.08)', color: '#ef4444',
            fontSize: 12, fontWeight: 600, cursor: 'pointer',
          }}>✗ Reject All</button>
          <button onClick={() => setSelectedIds(new Set())} style={{
            padding: '6px 14px', borderRadius: 6, border: '1px solid var(--border)',
            background: 'transparent', color: 'var(--text-muted)',
            fontSize: 12, fontWeight: 600, cursor: 'pointer',
          }}>Clear</button>
        </div>
      )}

      {bulkActionMsg && (
        <div style={{
          position: 'fixed', top: 80, right: 20, background: 'var(--bg-card)',
          border: '1px solid var(--border)', borderRadius: 8, padding: '12px 16px',
          boxShadow: '0 4px 12px rgba(0,0,0,0.1)', fontSize: 13, fontWeight: 500,
          zIndex: 1000,
        }}>
          {bulkActionMsg}
        </div>
      )}

      {/* Legend */}
      <section style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 12, padding: '12px 16px', marginBottom: 14,
        display: 'flex', flexWrap: 'wrap', gap: 20, alignItems: 'center', fontSize: 12,
      }}>
        <span style={{ color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', fontSize: 11 }}>Legend</span>
        {[
          { icon: '★★', color: '#16a34a', label: 'Strong signal', note: 'high edge & model agreement' },
          { icon: '★',  color: '#ca8a04', label: 'Moderate signal', note: '' },
          { icon: '⚠',  color: '#ca8a04', label: 'Near threshold', note: 'small temp swings flip outcome' },
          { icon: '↔',  color: 'var(--text-muted)', label: 'Hedge', note: 'opposite side of open position' },
        ].map(({ icon, color, label, note }) => (
          <span key={label} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ color, fontWeight: 700, fontSize: 13 }}>{icon}</span>
            <span>{label}</span>
            {note && <span style={{ color: 'var(--text-muted)' }}>· {note}</span>}
          </span>
        ))}
      </section>

      {filtered.length === 0 && (
        <section style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 14, padding: '40px 24px', marginBottom: 18,
          textAlign: 'center',
        }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>📡</div>
          <h3 style={{ margin: '0 0 8px', fontSize: 16, fontWeight: 600 }}>No signals yet</h3>
          <p style={{ margin: '0 0 20px', color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.5, maxWidth: 400, marginLeft: 'auto', marginRight: 'auto' }}>
            No scan data yet. Run a cron scan in the Settings tab to fetch live market data and generate signals.
          </p>
        </section>
      )}

      {/* ── Same-Day (METAR-locked) signals ─────────────────────────────── */}
      {sameDayOpps.length > 0 && (
        <div style={{ marginBottom: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Same-Day</h2>
            <span style={{
              padding: '2px 8px', borderRadius: 999, fontSize: 11, fontWeight: 600,
              background: 'rgba(59,130,246,0.12)', color: '#3b82f6',
            }}>settles today</span>
            <span style={{ color: 'var(--text-faint)', fontSize: 12 }}>{sameDayOpps.length} candidate{sameDayOpps.length !== 1 ? 's' : ''}</span>
          </div>
          <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 12 }}>
                <th style={{ padding: '12px 16px', width: 40 }}>
                  <input type="checkbox"
                    checked={selectedIds.size > 0 && sameDayOpps.every(o => selectedIds.has(o.ticker))}
                    onChange={(e) => {
                      const next = new Set(selectedIds);
                      sameDayOpps.forEach(o => e.target.checked ? next.add(o.ticker) : next.delete(o.ticker));
                      setSelectedIds(next);
                    }}
                    style={{ cursor: 'pointer' }}
                  />
                </th>
                {['★', 'Ticker', 'City', 'Side', 'Forecast', 'Market', 'Edge', 'Risk', 'Kelly $', 'Expires', 'Flags', 'Action'].map((h, i) => (
                  <th key={h} style={{
                    padding: '12px 16px', fontWeight: 600, borderBottom: '1px solid var(--border)',
                    textAlign: [4, 5, 6, 8].includes(i) ? 'right' : 'left',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {renderRows(sameDayOpps)}
            </tbody>
          </table>
          </section>
        </div>
      )}

      {/* ── Multi-Day Forecast signals ───────────────────────────────────── */}
      {multiDayOpps.length > 0 && (
        <div style={{ marginBottom: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Multi-Day Forecast</h2>
            <span style={{
              padding: '2px 8px', borderRadius: 999, fontSize: 11, fontWeight: 600,
              background: 'rgba(16,185,129,0.12)', color: '#10b981',
            }}>ensemble model</span>
            <span style={{ color: 'var(--text-faint)', fontSize: 12 }}>{multiDayOpps.length} candidate{multiDayOpps.length !== 1 ? 's' : ''}</span>
          </div>
          <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 12 }}>
                <th style={{ padding: '12px 16px', width: 40 }}>
                  <input type="checkbox"
                    checked={selectedIds.size > 0 && multiDayOpps.every(o => selectedIds.has(o.ticker))}
                    onChange={(e) => {
                      const next = new Set(selectedIds);
                      multiDayOpps.forEach(o => e.target.checked ? next.add(o.ticker) : next.delete(o.ticker));
                      setSelectedIds(next);
                    }}
                    style={{ cursor: 'pointer' }}
                  />
                </th>
                {['★', 'Ticker', 'City', 'Side', 'Forecast', 'Market', 'Edge', 'Risk', 'Kelly $', 'Expires', 'Flags', 'Action'].map((h, i) => (
                  <th key={h} style={{
                    padding: '12px 16px', fontWeight: 600, borderBottom: '1px solid var(--border)',
                    textAlign: [4, 5, 6, 8].includes(i) ? 'right' : 'left',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {renderRows(multiDayOpps)}
            </tbody>
          </table>
          </section>
        </div>
      )}

      {selectedOpp && (
        <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px 24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
            <div>
              <h3 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>{normCity(selectedOpp.city)} · {selectedOpp.ticker}</h3>
              <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
                {selectedOpp.signal || selectedOpp.stars} · forecast {selectedOpp.forecast_prob.toFixed(1)}% vs market {selectedOpp.market_prob.toFixed(1)}%
              </p>
            </div>
            <button onClick={() => setSelectedOpp(null)} style={{ padding: '6px 12px', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 12, cursor: 'pointer', color: 'var(--text)' }}>Close</button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16, marginBottom: 16 }}>
            {[
              { label: 'Edge',            value: '+' + selectedOpp.edge_pct.toFixed(1) + '%' },
              { label: 'Forecast p',      value: selectedOpp.forecast_prob.toFixed(1) + '%' },
              { label: 'Market p',        value: selectedOpp.market_prob.toFixed(1) + '%' },
              { label: 'Kelly $',         value: selectedOpp.kelly_dollars > 0 ? '$' + selectedOpp.kelly_dollars.toFixed(2) : '—' },
              { label: 'Kelly contracts', value: (() => { const mp2 = (selectedOpp.market_prob || 0) / 100; const kq = selectedOpp.kelly_qty || (selectedOpp.kelly_dollars > 0 && mp2 > 0 ? Math.max(1, Math.floor(selectedOpp.kelly_dollars / mp2)) : 0); return kq > 0 ? kq + ' cts' : '—'; })() },
            ].map(item => (
              <div key={item.label}>
                <div style={{ color: 'var(--text-faint)', fontSize: 11, marginBottom: 4 }}>{item.label}</div>
                <div style={{ fontWeight: 600, fontSize: 15, fontFamily: 'ui-monospace, monospace' }}>{item.value}</div>
              </div>
            ))}
          </div>
          <div style={{ padding: '14px 16px', borderRadius: 8, background: 'var(--bg-muted)', fontSize: 12 }}>
            <strong>Suggested action:</strong> Buy {selectedOpp.side.toUpperCase()} — forecast probability ({selectedOpp.forecast_prob.toFixed(1)}%) exceeds market ({selectedOpp.market_prob.toFixed(1)}%) by {selectedOpp.edge_pct.toFixed(1)} pts.
          </div>
        </section>
      )}

      {/* Confirmation modal — Escape cancels, Enter confirms */}
      {confirmPending && (
        <div
          onKeyDown={e => { if (e.key === 'Enter') handleConfirm(); }}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
          }} onClick={() => setConfirmPending(null)}>
          <div onClick={e => e.stopPropagation()} style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 14, padding: '24px 28px', minWidth: 340, maxWidth: 420,
          }}>
            <h3 style={{ margin: '0 0 6px', fontSize: 16, fontWeight: 700 }}>Confirm trade</h3>
            {(() => {
              const cost = confirmPending.qty * (confirmPending.opp.market_prob || 0) / 100;
              const remaining = (M.stats.balance || 0) - M.positions.reduce((a, p) => a + p.cost, 0) - cost;
              return (
                <p style={{ margin: '0 0 18px', color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.5 }}>
                  Place <strong>{confirmPending.qty} contract{confirmPending.qty !== 1 ? 's' : ''}</strong> of{' '}
                  <strong style={{ color: '#3b82f6' }}>{confirmPending.opp.ticker}</strong>{' '}
                  <strong style={{ color: confirmPending.opp.side === 'yes' ? '#16a34a' : '#ef4444' }}>
                    {(confirmPending.opp.side || 'YES').toUpperCase()}
                  </strong>{' '}
                  at <strong>{confirmPending.opp.market_prob?.toFixed(1)}¢</strong>?
                  {' '}Cost: <strong>${cost.toFixed(2)}</strong>.
                  <br />
                  <span style={{ fontSize: 12, color: remaining < 10 ? '#ef4444' : 'var(--text-faint)' }}>
                    Balance after: <strong>${remaining.toFixed(2)}</strong>
                  </span>
                </p>
              );
            })()}
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button onClick={() => setConfirmPending(null)} style={{
                padding: '9px 18px', borderRadius: 8, border: '1px solid var(--border)',
                background: 'var(--bg-card)', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13, cursor: 'pointer',
              }}>Cancel</button>
              <button onClick={handleConfirm} style={{
                padding: '9px 20px', borderRadius: 8, border: 'none',
                background: '#16a34a', color: 'white', fontWeight: 700, fontSize: 13, cursor: 'pointer',
              }}>Place order</button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
