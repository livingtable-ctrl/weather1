import React, { useState, useContext, useMemo } from 'react';
import { DataContext } from '../DataContext.js';
import { normCity, fmtEdge, outcomeBadge } from '../shared.jsx';

export default function TradesTab() {
  const M = useContext(DataContext);
  const [page, setPage] = useState(0);
  const [cityFilter, setCityFilter] = useState('');
  const [sideFilter, setSideFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState(''); // '' | 'threshold' | 'between' | 'sameday'
  const [sortKey, setSortKey] = useState('date');
  const PAGE_SIZE = 10;

  const cities = useMemo(() => [...new Set(M.closedTrades.map(t => t.city))].sort(), [M.closedTrades]);

  const filtered = useMemo(() => {
    const rows = M.closedTrades.filter(t => {
      if (cityFilter && t.city !== cityFilter) return false;
      if (sideFilter && t.side !== sideFilter) return false;
      if (typeFilter) {
        const isBetween   = t.ticker && /-B\d/.test(t.ticker);
        const isSameDay   = t.days_out === 0;
        if (typeFilter === 'between'   && !isBetween) return false;
        if (typeFilter === 'threshold' && (isBetween || isSameDay)) return false;
        if (typeFilter === 'sameday'   && !isSameDay) return false;
      }
      return true;
    });
    if (sortKey === 'pnl_desc') return [...rows].sort((a, b) => (b.pnl ?? 0) - (a.pnl ?? 0));
    if (sortKey === 'pnl_asc')  return [...rows].sort((a, b) => (a.pnl ?? 0) - (b.pnl ?? 0));
    return [...rows].sort((a, b) => (b.entered_at || '').localeCompare(a.entered_at || ''));
  }, [cityFilter, sideFilter, typeFilter, sortKey, M.closedTrades]);

  const paginated = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const wins = M.closedTrades.filter(t => t.pnl > 0).length;
  const losses = M.closedTrades.filter(t => t.pnl != null && t.pnl < 0).length;

  function handleExportCSV() {
    const headers = ['Ticker', 'City', 'Side', 'Entry ¢', 'Quantity', 'Cost', 'Net Edge', 'Outcome', 'P&L', 'Entered At', 'Settled At', 'Hold Days'];
    const rows = M.closedTrades.map(t => {
      const holdDays = (t.entered_at && t.settled_at)
        ? ((new Date(t.settled_at) - new Date(t.entered_at)) / 86400000).toFixed(1)
        : '';
      return [
        t.ticker, t.city, t.side,
        t.entry_price != null ? (t.entry_price * 100).toFixed(0) : '',
        t.quantity ?? '',
        t.cost != null ? t.cost.toFixed(2) : '',
        t.net_edge != null ? (t.net_edge * 100).toFixed(2) + '%' : '',
        t.outcome ?? '',
        t.pnl != null ? t.pnl.toFixed(2) : '',
        t.entered_at ?? '',
        t.settled_at ?? '',
        holdDays,
      ].map(v => `"${String(v).replace(/"/g, '""')}"`).join(',');
    });
    const csv = [headers.join(','), ...rows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `trades_${new Date().toISOString().slice(0,10)}.csv`; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 18 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em' }}>Trade History</h1>
          <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
            {filtered.length} settled · {wins} wins · {losses} losses
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <select value={cityFilter} onChange={e => { setCityFilter(e.target.value); setPage(0); }}
            style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 13, cursor: 'pointer', color: 'var(--text)' }}>
            <option value="">All cities</option>
            {cities.map(c => <option key={c} value={c}>{normCity(c)}</option>)}
          </select>
          <select value={sideFilter} onChange={e => { setSideFilter(e.target.value); setPage(0); }}
            style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 13, cursor: 'pointer', color: 'var(--text)' }}>
            <option value="">All sides</option>
            <option value="yes">YES</option>
            <option value="no">NO</option>
          </select>
          <select value={typeFilter} onChange={e => { setTypeFilter(e.target.value); setPage(0); }}
            style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 13, cursor: 'pointer', color: 'var(--text)' }}>
            <option value="">All types</option>
            <option value="threshold">Above/Below (-T)</option>
            <option value="between">Between (-B)</option>
            <option value="sameday">Same-day</option>
          </select>
          <select value={sortKey} onChange={e => { setSortKey(e.target.value); setPage(0); }}
            style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 13, cursor: 'pointer', color: 'var(--text)' }}>
            <option value="date">Sort by Date</option>
            <option value="pnl_desc">Sort by P&L ↓</option>
            <option value="pnl_asc">Sort by P&L ↑</option>
          </select>
          <button onClick={handleExportCSV} title="Export to CSV"
            style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 13, cursor: 'pointer', color: 'var(--text)', fontWeight: 500 }}>
            ↓ CSV
          </button>
        </div>
      </div>

      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden', marginBottom: 18 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 12 }}>
              {['Ticker', 'City', 'Type', 'Side', 'Entry', 'Net Edge', 'Outcome', 'P&L', 'Hold', 'Entered'].map((h, i) => (
                <th key={h} style={{ padding: '12px 16px', textAlign: [4, 5, 7, 8].includes(i) ? 'right' : 'left', fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paginated.map((t, i) => {
              const badge = outcomeBadge(t.outcome, t.pnl);
              // net_edge may be stored as ratio (real data) or absent (mock)
              const netEdgeDisplay = t.net_edge != null ? fmtEdge(t.net_edge) : '—';
              return (
                <tr key={i} style={{ borderBottom: '1px solid var(--bg-muted)' }}>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#3b82f6' }}>{t.ticker}</td>
                  <td style={{ padding: '14px 16px', fontWeight: 600 }}>{normCity(t.city)}</td>
                  <td style={{ padding: '14px 16px' }}>
                    {(() => {
                      // Parse market type from ticker: -B = between range, -T = above/below threshold.
                      // days_out=0 indicates a same-day METAR-locked trade regardless of ticker type.
                      const isSameDay = t.days_out === 0;
                      const isBetween = !isSameDay && t.ticker && /-B\d/.test(t.ticker);
                      const label = isSameDay ? 'SD' : isBetween ? 'B' : 'T';
                      const title = isSameDay ? 'Same-day (METAR-locked)'
                        : isBetween ? 'Between range market'
                        : 'Above/Below threshold market';
                      const bg = isSameDay ? 'rgba(59,130,246,0.12)'
                        : isBetween ? 'rgba(139,92,246,0.12)'
                        : 'rgba(16,185,129,0.12)';
                      const color = isSameDay ? '#3b82f6' : isBetween ? '#8b5cf6' : '#10b981';
                      return (
                        <span title={title} style={{
                          display: 'inline-block', padding: '2px 7px', borderRadius: 999,
                          background: bg, color, fontSize: 10, fontWeight: 700,
                        }}>{label}</span>
                      );
                    })()}
                  </td>
                  <td style={{ padding: '14px 16px' }}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 999,
                      background: t.side === 'yes' ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
                      color: t.side === 'yes' ? '#16a34a' : '#ef4444',
                      fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                    }}>{t.side}</span>
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>
                    {t.entry_price != null ? (t.entry_price * 100).toFixed(0) + '¢' : '—'}
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)', fontSize: 12 }}>
                    {netEdgeDisplay}
                  </td>
                  <td style={{ padding: '14px 16px' }}>
                    <span style={{ display: 'inline-block', padding: '2px 8px', borderRadius: 999, background: badge.bg, color: badge.color, fontSize: 10, fontWeight: 600 }}>
                      {badge.label}
                    </span>
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', fontWeight: 700, color: t.pnl == null ? 'var(--text-faint)' : t.pnl >= 0 ? '#16a34a' : '#ef4444' }}>
                    {t.pnl == null ? '—' : (t.pnl >= 0 ? '+' : '') + '$' + t.pnl.toFixed(2)}
                  </td>
                  <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-faint)' }}>
                    {(t.entered_at && t.settled_at)
                      ? Math.ceil((new Date(t.settled_at) - new Date(t.entered_at)) / 86400000) + 'd'
                      : '—'}
                  </td>
                  <td style={{ padding: '14px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-faint)' }}>
                    {t.entered_at ? new Date(t.entered_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      {totalPages > 1 && (
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
          {Array.from({ length: totalPages }, (_, i) => (
            <button key={i} onClick={() => setPage(i)} style={{
              padding: '6px 12px', borderRadius: 7, border: '1px solid var(--border)',
              background: page === i ? '#3b82f6' : 'var(--bg-card)',
              color: page === i ? 'white' : 'var(--text)', fontWeight: 500, fontSize: 12, cursor: 'pointer',
            }}>{i + 1}</button>
          ))}
        </div>
      )}
    </main>
  );
}
