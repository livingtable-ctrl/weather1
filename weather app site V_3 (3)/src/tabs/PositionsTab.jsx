import React, { useState, useEffect, useContext, useMemo } from 'react';
import { DataContext } from '../DataContext.js';
import { authHeader } from '../useData.js';
import { normCity, kalshiMarketUrl } from '../shared.jsx';

// ---------------------------------------------------------------------------
// WeatherAlertBanner — NWS active alerts for cities with open positions
// ---------------------------------------------------------------------------
function WeatherAlertBanner({ alerts }) {
  if (!alerts || alerts.length === 0) return null;
  return (
    <div style={{
      background: 'rgba(239,68,68,0.08)', border: '1px solid #ef4444',
      borderRadius: 8, padding: '8px 14px', marginBottom: 12, fontSize: 12,
    }}>
      <strong style={{ color: '#ef4444' }}>⚠ Active Weather Alerts</strong>
      {alerts.map((a, i) => (
        <div key={i} style={{ marginTop: 4, color: 'var(--text)' }}>
          <strong>{a.city}</strong> — {a.event}
          {a.headline && <span style={{ color: 'var(--text-muted)' }}> — {a.headline}</span>}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PortfolioEvCard — aggregate expected value summary for all open positions
// ---------------------------------------------------------------------------
function PortfolioEvCard({ stats }) {
  if (!stats || stats.portfolio_ev == null || stats.portfolio_cost == null) return null;
  if (stats.portfolio_cost === 0) return null;
  const ev = stats.portfolio_ev;
  const roi = stats.portfolio_ev_roi_pct;
  const cost = stats.portfolio_cost;
  return (
    <div style={{
      display: 'flex', gap: 24, padding: '10px 16px', marginBottom: 12,
      background: 'var(--bg-card)', borderRadius: 8, border: '1px solid var(--border)',
    }}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>Expected Profit</div>
        <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'ui-monospace, monospace', color: ev >= 0 ? '#16a34a' : '#ef4444' }}>
          {ev >= 0 ? '+' : ''}{ev.toFixed(2)}
        </div>
      </div>
      {roi != null && (
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>EV ROI</div>
          <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'ui-monospace, monospace', color: roi >= 0 ? '#16a34a' : '#ef4444' }}>
            {roi >= 0 ? '+' : ''}{roi.toFixed(1)}%
          </div>
        </div>
      )}
      <div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>Deployed</div>
        <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'ui-monospace, monospace', color: 'var(--text)' }}>
          ${cost.toFixed(2)}
        </div>
      </div>
    </div>
  );
}

export default function PositionsTab() {
  const M = useContext(DataContext);
  const [filter, setFilter] = useState('');
  const [sortKey, setSortKey] = useState('edge');
  const [selectedPos, setSelectedPos] = useState(null);
  const [closeMsg, setCloseMsg] = useState('');
  const [confirmClose, setConfirmClose] = useState(null);
  const [alertsPanelOpen, setAlertsPanelOpen] = useState(false);
  const [alerts, setAlerts] = useState(() => {
    try { return JSON.parse(localStorage.getItem('kalshi-position-alerts') || '[]'); }
    catch { return []; }
  });
  const [newAlertTicker, setNewAlertTicker] = useState('');
  const [newAlertThreshold, setNewAlertThreshold] = useState('');
  const [newAlertDir, setNewAlertDir] = useState('above');

  function addAlert() {
    if (!newAlertTicker || !newAlertThreshold) return;
    const updated = [...alerts, { ticker: newAlertTicker, threshold: parseFloat(newAlertThreshold), dir: newAlertDir }];
    setAlerts(updated);
    localStorage.setItem('kalshi-position-alerts', JSON.stringify(updated));
    setNewAlertTicker('');
    setNewAlertThreshold('');
  }

  function removeAlert(i) {
    const updated = alerts.filter((_, j) => j !== i);
    setAlerts(updated);
    localStorage.setItem('kalshi-position-alerts', JSON.stringify(updated));
  }

  // Batch selection state
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [bulkActionMsg, setBulkActionMsg] = useState('');

  useEffect(() => {
    const handler = () => {
      setSelectedPos(null);
      setSelectedIds(new Set());
    };
    document.addEventListener('kalshi:escape', handler);
    return () => document.removeEventListener('kalshi:escape', handler);
  }, []);

  // Bulk close positions
  function handleBulkClose() {
    if (selectedIds.size === 0) return;
    const positionsToClose = filtered.filter(p => selectedIds.has(p.id));
    setBulkActionMsg(`Closing ${positionsToClose.length} positions...`);

    Promise.all(positionsToClose.map(p =>
      fetch('/api/close-position', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeader() },
        body: JSON.stringify({ trade_id: p.id, exit_price: p.mark || 0 }),
      }).then(r => r.json())
    )).then(() => {
      setBulkActionMsg(`✓ Closed ${positionsToClose.length} positions`);
      setSelectedIds(new Set());
      M.refresh();
      setTimeout(() => setBulkActionMsg(''), 3000);
    }).catch(() => {
      setBulkActionMsg('✗ Bulk close failed');
      setTimeout(() => setBulkActionMsg(''), 3000);
    });
  }

  function handleClose(pos) {
    setConfirmClose(pos);
  }

  function handleCloseConfirm() {
    if (!confirmClose) return;
    const pos = confirmClose;
    setConfirmClose(null);

    if (!pos.id) { setCloseMsg('✗ No trade ID'); setTimeout(() => setCloseMsg(''), 3000); return; }
    fetch('/api/close-position', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader() },
      body: JSON.stringify({ trade_id: pos.id, exit_price: pos.mark || 0 }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.error) { setCloseMsg(`✗ ${d.error}`); }
        else {
          const pnl = d.pnl != null ? (d.pnl >= 0 ? `+$${d.pnl.toFixed(2)}` : `-$${Math.abs(d.pnl).toFixed(2)}`) : '';
          setCloseMsg(`✓ Closed ${pos.ticker} ${pnl}`);
          setSelectedPos(null);
          M.refresh();
        }
        setTimeout(() => setCloseMsg(''), 4000);
      })
      .catch(() => { setCloseMsg('✗ Request failed'); setTimeout(() => setCloseMsg(''), 3000); });
  }

  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape') {
        setConfirmClose(null);
        setAlertsPanelOpen(false);
      }
      if (confirmClose && e.key === 'Enter') {
        handleCloseConfirm();
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [confirmClose]);

  const filtered = useMemo(() => {
    const f = filter.toLowerCase();
    const rows = M.positions.filter(p =>
      !f || normCity(p.city).toLowerCase().includes(f) || p.ticker.toLowerCase().includes(f)
    );
    return [...rows].sort((a, b) =>
      sortKey === 'edge' ? b.edge - a.edge : sortKey === 'cost' ? b.cost - a.cost : a.age_h - b.age_h
    );
  }, [filter, sortKey, M.positions]);

  return (
    <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 18 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em' }}>Open Positions</h1>
          {(() => {
            const deployed = M.positions.reduce((a, p) => a + p.cost, 0);
            const available = (M.stats.balance || 0) - deployed;
            return (
              <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
                {M.positions.length} positions · <span style={{ color: '#3b82f6', fontWeight: 600 }}>${deployed.toFixed(2)}</span> deployed · <span style={{ color: '#16a34a', fontWeight: 600 }}>${available.toFixed(2)}</span> available
              </p>
            );
          })()}
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <input placeholder="Filter by city or ticker…" value={filter} onChange={e => setFilter(e.target.value)}
            style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 13, width: 240, outline: 'none', color: 'var(--text)' }} />
          <select value={sortKey} onChange={e => setSortKey(e.target.value)}
            style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 13, cursor: 'pointer', color: 'var(--text)' }}>
            <option value="edge">Sort by Edge</option>
            <option value="cost">Sort by Cost</option>
            <option value="age">Sort by Age</option>
          </select>
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
          <button onClick={handleBulkClose} style={{
            padding: '6px 14px', borderRadius: 6, border: '1px solid #ef4444',
            background: 'rgba(239,68,68,0.08)', color: '#ef4444',
            fontSize: 12, fontWeight: 600, cursor: 'pointer',
          }}>Close All</button>
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
          zIndex: 1000, animation: 'slideIn 0.2s ease-out',
        }}>
          {bulkActionMsg}
        </div>
      )}

      <WeatherAlertBanner alerts={M.weatherAlerts?.alerts} />
      <PortfolioEvCard stats={M.stats} />

      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 12 }}>
              <th style={{ padding: '12px 16px', width: 40 }}>
                <input
                  type="checkbox"
                  checked={selectedIds.size > 0 && selectedIds.size === filtered.length}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedIds(new Set(filtered.map(p => p.id)));
                    } else {
                      setSelectedIds(new Set());
                    }
                  }}
                  style={{ cursor: 'pointer' }}
                />
              </th>
              {['🔔', 'Ticker', 'City', 'Side', 'Cost', 'Qty', 'Mark ¢', 'Fcst ¢', 'Edge', 'Unrl. P&L', 'Model', 'Expiry', 'Age'].map((h, i) => (
                <th key={h} style={{ padding: '12px 16px', textAlign: i >= 4 && i <= 9 ? 'right' : 'left', fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((p, i) => {
              const hasAlert = alerts.some(a => a.ticker === p.ticker);
              const upnl = (p.mark - p.cost / p.qty) * p.qty;
              const upnlColor = !p.markIsLive ? 'var(--text-faint)' : upnl >= 0 ? '#16a34a' : '#ef4444';
              const upnlLabel = (upnl >= 0 ? '+' : '-') + '$' + Math.abs(upnl).toFixed(2);
              const today = new Date().toISOString().slice(0, 10);
              const overdue = p.expiry && today > p.expiry;
              const daysOut = p.expiry ? Math.ceil((new Date(p.expiry) - new Date(new Date().toDateString())) / 86400000) : 0;
              // Show a countdown using close_time (exact UTC market close) when available.
              // Falls back gracefully to showing nothing when the field is absent (old trades).
              const closeMs = p.close_time ? new Date(p.close_time).getTime() : null;
              const msLeft = closeMs != null ? closeMs - Date.now() : null;
              const hoursLeft = msLeft != null ? Math.floor(msLeft / 3600000) : null;
              const timeLeftLabel = msLeft == null ? null
                : msLeft < 0 ? 'closed'
                : hoursLeft >= 24 ? `${Math.floor(hoursLeft / 24)}d`
                : hoursLeft >= 1 ? `${hoursLeft}h`
                : `${Math.round(msLeft / 60000)}m`;
              return (
                <tr key={i} onClick={() => setSelectedPos(selectedPos === p ? null : p)} style={{
                  borderBottom: '1px solid var(--bg-muted)', cursor: 'pointer',
                  background: selectedPos === p ? 'var(--bg-subtle)' : 'transparent',
                }}>
                  <td style={{ padding: '14px 16px', textAlign: 'center' }} onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selectedIds.has(p.id)}
                      onChange={(e) => {
                        const next = new Set(selectedIds);
                        if (e.target.checked) next.add(p.id);
                        else next.delete(p.id);
                        setSelectedIds(next);
                      }}
                      style={{ cursor: 'pointer' }}
                    />
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'center' }} onClick={e => { e.stopPropagation(); setAlertsPanelOpen(true); }}>
                    <button style={{
                      background: hasAlert ? 'rgba(59,130,246,0.12)' : 'transparent',
                      border: 'none', fontSize: 16, cursor: 'pointer', padding: '2px 6px', borderRadius: 4,
                      color: hasAlert ? '#3b82f6' : 'var(--text-faint)',
                    }} title={hasAlert ? 'Has active alerts' : 'Add alert'}>🔔</button>
                  </td>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#3b82f6' }}>
                    <a
                      href={kalshiMarketUrl(p.ticker)}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: '#3b82f6', textDecoration: 'none', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}
                    >
                      {p.ticker} ↗
                    </a>
                  </td>
                  <td style={{ padding: '14px 16px', fontWeight: 600 }}>{normCity(p.city)}</td>
                  <td style={{ padding: '14px 16px' }}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 999,
                      background: p.side === 'yes' ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
                      color: p.side === 'yes' ? '#16a34a' : '#ef4444', fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                    }}>{p.side}</span>
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>${p.cost.toFixed(2)}</td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>{p.qty}</td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)' }}>{(p.mark * 100).toFixed(0)}c</td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>{(p.fcst * 100).toFixed(0)}c</td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', color: '#16a34a', fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>+{(p.edge * 100).toFixed(1)}%</td>
                  <td title={!p.markIsLive ? 'Mark price not live — showing entry price' : undefined}
                    style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', fontSize: 11, fontWeight: 600, color: upnlColor }}>
                    {upnlLabel}
                  </td>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-muted)' }}>{p.model || '—'}</td>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>
                    {!p.expiry
                      ? <span style={{ color: 'var(--text-faint)' }}>-</span>
                      : <span title={overdue ? 'Past expiry - needs settlement' : undefined}
                          style={{ color: overdue ? '#ef4444' : daysOut <= 1 ? '#f59e0b' : 'var(--text-muted)', fontWeight: overdue ? 700 : 'inherit' }}>
                          {overdue ? '! ' : ''}{p.expiry}
                        </span>
                    }
                    {timeLeftLabel != null && (
                      <div style={{
                        fontSize: 10,
                        color: msLeft < 0 ? '#ef4444' : msLeft < 7200000 ? '#f59e0b' : 'var(--text-faint)',
                        marginTop: 2,
                      }}>
                        {msLeft < 0 ? 'past close' : `closes in ${timeLeftLabel}`}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-faint)' }}>{p.age_h}h</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      {selectedPos && (
        <section style={{ marginTop: 18, background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px 24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
            <div>
              <h3 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>{normCity(selectedPos.city)} · {selectedPos.ticker}</h3>
              <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
                Opened {selectedPos.age_h}h ago · {selectedPos.model} forecast · closes {
                  selectedPos.close_time
                    ? new Date(selectedPos.close_time).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC', timeZoneName: 'short' })
                    : selectedPos.expiry
                }
                {selectedPos.expiry && new Date().toISOString().slice(0, 10) > selectedPos.expiry &&
                  <span style={{ color: '#ef4444', fontWeight: 700, marginLeft: 6 }}>- PAST EXPIRY</span>
                }
              </p>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {closeMsg && <span style={{ fontSize: 12, fontWeight: 600, color: closeMsg.startsWith('✓') ? '#16a34a' : '#ef4444' }}>{closeMsg}</span>}
              <button onClick={() => handleClose(selectedPos)} style={{
                padding: '6px 14px', borderRadius: 7, border: '1px solid #ef4444',
                background: 'rgba(239,68,68,0.08)', color: '#ef4444',
                fontSize: 12, fontWeight: 600, cursor: 'pointer',
              }}>Close Position</button>
              <button onClick={() => setSelectedPos(null)} style={{ padding: '6px 12px', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 12, cursor: 'pointer', color: 'var(--text)' }}>Dismiss</button>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16 }}>
            {[
              { label: 'Side',           value: selectedPos.side.toUpperCase() },
              { label: 'Cost basis',     value: '$' + selectedPos.cost.toFixed(2) },
              { label: 'Quantity',       value: selectedPos.qty + ' contracts' },
              { label: 'Current mark',   value: selectedPos.mark.toFixed(2) },
              { label: 'Unrealized P&L', value: (() => { const u = (selectedPos.mark - selectedPos.cost / selectedPos.qty) * selectedPos.qty; return (u >= 0 ? '+' : '-') + '$' + Math.abs(u).toFixed(2); })(), color: (() => { const u = (selectedPos.mark - selectedPos.cost / selectedPos.qty) * selectedPos.qty; return u >= 0 ? '#16a34a' : '#ef4444'; })() },
            ].map((item) => (
              <div key={item.label}>
                <div style={{ color: 'var(--text-faint)', fontSize: 11, marginBottom: 4 }}>{item.label}</div>
                <div style={{ fontWeight: 600, fontSize: 15, fontFamily: 'ui-monospace, monospace', color: item.color || 'inherit' }}>{item.value}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Confirm close modal */}
      {confirmClose && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
        }} onClick={() => setConfirmClose(null)}>
          <div onClick={e => e.stopPropagation()} style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 14, padding: '24px 28px', minWidth: 320, maxWidth: 400,
          }}>
            <h3 style={{ margin: '0 0 10px', fontSize: 16, fontWeight: 700 }}>Close position?</h3>
            <p style={{ margin: '0 0 18px', color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.5 }}>
              Close <strong style={{ color: '#3b82f6' }}>{confirmClose.ticker}</strong> at mark price <strong>{(confirmClose.mark * 100).toFixed(0)}¢</strong>?
            </p>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button onClick={() => setConfirmClose(null)} style={{
                padding: '9px 18px', borderRadius: 8, border: '1px solid var(--border)',
                background: 'var(--bg-card)', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13, cursor: 'pointer',
              }}>Cancel</button>
              <button onClick={handleCloseConfirm} style={{
                padding: '9px 20px', borderRadius: 8, border: 'none',
                background: '#ef4444', color: 'white', fontWeight: 700, fontSize: 13, cursor: 'pointer',
              }}>Close</button>
            </div>
          </div>
        </div>
      )}

      {/* Position alerts panel */}
      {alertsPanelOpen && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 200,
          background: 'rgba(0,0,0,0.35)', display: 'flex', justifyContent: 'flex-end',
        }} onClick={() => setAlertsPanelOpen(false)}>
          <div style={{
            width: 360, background: 'var(--bg-card)', height: '100%',
            borderLeft: '1px solid var(--border)', padding: '24px 20px',
            overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 16,
          }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Position Alerts</h3>
              <button onClick={() => setAlertsPanelOpen(false)}
                style={{ background: 'transparent', border: 'none', fontSize: 18, cursor: 'pointer', color: 'var(--text-muted)', padding: '2px 6px' }}>×</button>
            </div>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
              Alerts are stored locally in your browser. The bot does not act on them — they're for your awareness only.
            </p>

            {/* Add new alert */}
            <div style={{ background: 'var(--bg-subtle)', borderRadius: 10, padding: '14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' }}>Add alert</div>
              <select value={newAlertTicker} onChange={e => setNewAlertTicker(e.target.value)}
                style={{ padding: '8px 10px', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 12, color: 'var(--text)' }}>
                <option value="">Pick position…</option>
                {M.positions.map(p => <option key={p.ticker} value={p.ticker}>{p.ticker}</option>)}
              </select>
              <div style={{ display: 'flex', gap: 8 }}>
                <select value={newAlertDir} onChange={e => setNewAlertDir(e.target.value)}
                  style={{ padding: '8px 10px', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 12, color: 'var(--text)', flex: '0 0 auto' }}>
                  <option value="above">Mark above</option>
                  <option value="below">Mark below</option>
                </select>
                <input type="number" placeholder="e.g. 65" value={newAlertThreshold} onChange={e => setNewAlertThreshold(e.target.value)}
                  style={{ flex: 1, padding: '8px 10px', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 12, color: 'var(--text)' }} />
              </div>
              <button onClick={addAlert} disabled={!newAlertTicker || !newAlertThreshold}
                style={{ padding: '8px', borderRadius: 7, border: 'none', background: '#3b82f6', color: 'white', fontWeight: 600, fontSize: 12, cursor: 'pointer', opacity: (!newAlertTicker || !newAlertThreshold) ? 0.5 : 1 }}>
                Save alert
              </button>
            </div>

            {/* Existing alerts */}
            {alerts.length === 0
              ? <p style={{ fontSize: 12, color: 'var(--text-faint)', textAlign: 'center', marginTop: 20 }}>No alerts set.</p>
              : alerts.map((a, i) => (
                <div key={i} style={{ background: 'var(--bg-subtle)', borderRadius: 10, padding: '12px 14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, fontFamily: 'ui-monospace, monospace', color: '#3b82f6' }}>{a.ticker}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                      Mark {a.dir} {a.threshold}¢
                    </div>
                  </div>
                  <button onClick={() => removeAlert(i)}
                    style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 16, padding: '2px 6px' }}>×</button>
                </div>
              ))
            }
          </div>
        </div>
      )}
    </main>
  );
}
