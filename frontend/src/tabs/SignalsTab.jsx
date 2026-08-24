import React, { useState, useEffect, useContext, useMemo } from 'react';
import { DataContext } from '../DataContext.js';
import { authHeader } from '../useData.js';
import { normCity, kalshiMarketUrl, sideAwareEntryPrice, buildPaperOrderBody, summarizeBulkResults, effectiveSelection, fmtSigned, oppKey, pruneExpired, filterRejected } from '../shared.jsx';

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

  // batch-45 M-7: Reject previously just showed a toast and returned -- no
  // request sent, nothing persisted, so the row reappeared identically on
  // the next scan while the "✗ Rejected" toast implied a recorded decision.
  // Uses localStorage (unlike placedSet's sessionStorage) *deliberately*: a
  // dismissal is a soft, reversible preference that should survive a browser
  // restart so it actually stops reappearing (the whole point of this fix);
  // placedSet instead records a real, already-durably-tracked-server-side
  // order, where sessionStorage only needs to prevent a same-session double-
  // submit. TTL expiry keeps a dismissal from hiding a ticker+date forever.
  const REJECTED_KEY = 'kalshi-rejected-signals';
  const REJECT_TTL_MS = 24 * 3600 * 1000;
  const [rejectedMap, setRejectedMap] = useState(() => {
    try {
      const raw = JSON.parse(localStorage.getItem(REJECTED_KEY) || '{}');
      const pruned = pruneExpired(raw);
      if (Object.keys(pruned).length !== Object.keys(raw).length) {
        localStorage.setItem(REJECTED_KEY, JSON.stringify(pruned));
      }
      return pruned;
    } catch { return {}; }
  });

  // opus review MEDIUM (batch-45): pruning only ran once at mount, so on a
  // long-open tab (this dashboard polls every 60s and is meant to be left
  // open) the TTL never actually fired -- filterRejected's own now-vs-expiry
  // check (below) already makes an expired entry stop suppressing its row,
  // but the map itself still needs to shrink periodically or it grows
  // unbounded across a long session. Re-prune every time a fresh poll lands.
  useEffect(() => {
    setRejectedMap(prev => {
      const pruned = pruneExpired(prev);
      if (Object.keys(pruned).length === Object.keys(prev).length) return prev;
      try { localStorage.setItem(REJECTED_KEY, JSON.stringify(pruned)); } catch {}
      return pruned;
    });
  }, [M.opportunities]);

  // Missing state that was referenced but never declared in the original file
  const [expandedId, setExpandedId] = useState(null);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [bulkActionMsg, setBulkActionMsg] = useState('');
  // {rows: [{opp, qty}], excludedCount} snapshotted at click time, or null.
  // NOT a boolean -- see handleBulkApprove's comment on why a re-derived
  // live list at confirm time is unsafe.
  const [bulkConfirmPending, setBulkConfirmPending] = useState(null);

  // Show every candidate the bot evaluated — no edge filter.
  // passes_threshold comes from the backend (cron.py gate logic).
  // The slider is a secondary visual highlight for manual exploration.
  // batch-45 M-7: a dismissed (rejected), not-yet-expired signal is excluded
  // here so Reject actually removes it from view instead of leaving the row
  // unchanged. filterRejected checks expiry at call time, not just presence
  // in rejectedMap (opus review MEDIUM) -- correct even between the periodic
  // re-prunes above.
  const filtered = useMemo(
    () => filterRejected(M.opportunities, rejectedMap),
    [M.opportunities, rejectedMap]
  );
  // opus review LOW (batch-45): no indicator previously told the operator
  // signals were being hidden at all -- see the "N dismissed" chip + Clear
  // affordance in the header below.
  const rejectedCount = M.opportunities.length - filtered.length;
  const sameDayOpps  = useMemo(() => filtered.filter(o => (o.days_out ?? 1) === 0), [filtered]);
  const multiDayOpps = useMemo(() => filtered.filter(o => (o.days_out ?? 1) > 0),  [filtered]);

  // C-3 fix: selectedIds itself is never pruned when M.opportunities changes
  // (e.g. a poll drops a ticker that's no longer a candidate) -- intersect
  // against what's currently on screen (both same-day and multi-day tables
  // combined, which together equal `filtered`) everywhere a count/checkbox/
  // action-target is displayed or acted on, same fix as PositionsTab.jsx.
  const effSelectedIds = useMemo(
    () => effectiveSelection(selectedIds, filtered.map(o => o.ticker)),
    [selectedIds, filtered]
  );

  useEffect(() => {
    const handler = () => { setSelectedOpp(null); setConfirmPending(null); setBulkConfirmPending(null); };
    document.addEventListener('kalshi:escape', handler);
    return () => document.removeEventListener('kalshi:escape', handler);
  }, []);

  function handleAction(opp, action) {
    if (action === 'reject') {
      const key = oppKey(opp);
      setRejectedMap(prev => {
        const next = { ...prev, [key]: Date.now() + REJECT_TTL_MS };
        try { localStorage.setItem(REJECTED_KEY, JSON.stringify(next)); } catch {}
        return next;
      });
      setActionMsg(`✗ ${opp.ticker} rejected`);
      setTimeout(() => setActionMsg(''), 2500);
      return;
    }
    // approve → show confirmation dialog first, sized via bulkOrderQty
    // (opus review LOW-12: this and the bulk-approve path used to hand-
    // duplicate the same sizing expression as two separate copies).
    setConfirmPending({ opp, qty: bulkOrderQty(opp) });
  }

  function handleConfirm() {
    if (!confirmPending) return;
    const { opp, qty } = confirmPending;
    setConfirmPending(null);
    fetch('/api/paper-order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader() },
      body: JSON.stringify(buildPaperOrderBody(opp, qty)),
    })
      .then(r => r.json())
      .then(d => {
        setActionMsg(d.error ? `✗ ${d.error}` : `✓ ${opp.ticker} placed`);
        setTimeout(() => setActionMsg(''), 3000);
        if (!d.error) {
          const key = oppKey(opp);
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

  // C-1 fix: the eligible set for bulk-approve mirrors the single-approve
  // path's own guard exactly -- same edge_pct > 0 filter as the row-level
  // Approve button's `disabled` condition, resolved against effSelectedIds
  // (currently-visible selections) not the raw, possibly-stale selection.
  // opus review MEDIUM-4: also excludes anything already in placedSet --
  // without this, ticking a row's checkbox, single-approving it via the
  // row button, then clicking "Approve All" while the (still-ticked, still
  // in M.opportunities) row is included would place a SECOND order on the
  // same ticker; check_position_limits has no already-open-on-this-ticker
  // guard of its own.
  function bulkEligibleOpps() {
    return filtered.filter(o =>
      effSelectedIds.has(o.ticker) &&
      (o.edge_pct || 0) > 0 &&
      !placedSet.has(oppKey(o))
    );
  }

  // batch-26: divide kelly_dollars by the side-aware entry price, not the
  // raw YES-space mid — for a NO signal the mid overstates the price paid,
  // undersizing the default quantity. Shared by handleAction and bulk
  // approve (opus review LOW-12: these were two hand-duplicated copies).
  function bulkOrderQty(opp) {
    const sp = sideAwareEntryPrice(opp);
    return parseInt(qtyMap[opp.ticker] ?? (opp.kelly_qty || (opp.kelly_dollars > 0 && sp > 0 ? Math.max(1, Math.floor(opp.kelly_dollars / sp)) : 1)) ?? 1, 10) || 1;
  }

  // Bulk approve: open one confirmation modal (listing every eligible order
  // and the combined total cost) before anything is submitted -- gives bulk
  // approve real parity with the single-approve path's own confirm step,
  // instead of firing orders straight off a checkbox click.
  function handleBulkApprove() {
    const eligible = bulkEligibleOpps();
    if (eligible.length === 0) {
      // opus review LOW-A: since bulkEligibleOpps() also excludes
      // already-placed tickers (MEDIUM-4), this path is now reachable for
      // a selection that DOES have positive edge but was already placed --
      // the old "no positive edge" wording would be factually wrong there.
      setBulkActionMsg('✗ No selected signals are eligible (no positive edge, or already placed)');
      setTimeout(() => setBulkActionMsg(''), 3000);
      return;
    }
    // opus review MEDIUM-3: snapshot the exact rows the modal displays and
    // will submit, instead of a boolean flag that re-derives
    // bulkEligibleOpps() again at confirm time. Without this, a 60s poll
    // (useData.js) landing while the modal is open could change what
    // "eligible" resolves to -- e.g. resurrect a ticker via the
    // non-destructive C-3 selection model, or shift a qty/price -- so the
    // operator's click could submit orders the modal never actually showed
    // them. The single-approve path's confirmPending already avoids this
    // exact class of bug by snapshotting {opp, qty} the same way.
    setBulkConfirmPending({
      rows: eligible.map(opp => ({ opp, qty: bulkOrderQty(opp) })),
      excludedCount: effSelectedIds.size - eligible.length,
    });
  }

  function handleBulkConfirm() {
    if (!bulkConfirmPending) return;
    const { rows } = bulkConfirmPending;
    setBulkConfirmPending(null);
    setBulkActionMsg(`Placing ${rows.length} orders...`);

    Promise.allSettled(rows.map(({ opp, qty }) =>
      fetch('/api/paper-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeader() },
        body: JSON.stringify(buildPaperOrderBody(opp, qty)),
      }).then(r => r.json()).then(d => ({ opp, d }))
    )).then(results => {
      // C-1 fix: inspect what each response actually said, not an
      // unconditional "all placed" toast -- a rejected fetch (network
      // failure) or a fulfilled response carrying {error} both count as
      // failed, and only a genuine success writes to placedSet (so a
      // second click can't re-submit an order that already went through).
      const { succeeded, failed } = summarizeBulkResults(results, v => v.d?.error);
      const successKeys = results
        .filter(r => r.status === 'fulfilled' && !r.value.d?.error)
        .map(r => oppKey(r.value.opp));
      if (successKeys.length) {
        setPlacedSet(prev => {
          const next = new Set([...prev, ...successKeys]);
          try { sessionStorage.setItem(PLACED_KEY, JSON.stringify([...next])); } catch {}
          return next;
        });
      }
      setBulkActionMsg(failed > 0 ? `✓ ${succeeded} placed / ✗ ${failed} failed` : `✓ ${succeeded} placed`);
      setSelectedIds(prev => {
        const next = new Set(prev);
        rows.forEach(({ opp }) => next.delete(opp.ticker));
        return next;
      });
      M.refresh();
      setTimeout(() => setBulkActionMsg(''), 4000);
    }).catch(() => {
      // opus review LOW-B: Promise.allSettled itself never rejects, but a
      // throw inside the .then body above (realistically M.refresh()) was
      // previously caught by Promise.all's .catch() -- allSettled dropped
      // that safety net. Without this, an uncaught rejection here would
      // leave the "Placing N orders..." toast pinned with no error shown
      // and no timeout ever clearing it.
      setBulkActionMsg('✗ Bulk approve failed');
      setTimeout(() => setBulkActionMsg(''), 3000);
    });
  }

  // Bulk reject: persist a dismissal for every selected (visible) signal —
  // same rejectedMap mechanism as the single-row Reject button — then clear
  // the selection.
  function handleBulkReject() {
    const count = effSelectedIds.size;
    const toReject = filtered.filter(o => effSelectedIds.has(o.ticker));
    setRejectedMap(prev => {
      const next = { ...prev };
      const exp = Date.now() + REJECT_TTL_MS;
      toReject.forEach(o => { next[oppKey(o)] = exp; });
      try { localStorage.setItem(REJECTED_KEY, JSON.stringify(next)); } catch {}
      return next;
    });
    setSelectedIds(prev => {
      const next = new Set(prev);
      effSelectedIds.forEach(id => next.delete(id));
      return next;
    });
    setBulkActionMsg(`✗ Rejected ${count} signal${count !== 1 ? 's' : ''}`);
    setTimeout(() => setBulkActionMsg(''), 2500);
  }

  // opus review LOW (batch-45): Reject had no undo and no way to see what
  // was hidden -- clears every dismissal at once so a misclick (the ✗ button
  // sits 6px from ✓ Approve, no confirmation) or a "let me see everything
  // again" moment isn't stuck waiting out the 24h TTL.
  function handleClearRejections() {
    setRejectedMap({});
    try { localStorage.removeItem(REJECTED_KEY); } catch {}
  }

  // Shared row renderer — used by both Same-Day and Multi-Day sections.
  // Defined inside the component so it closes over state (expandedId, selectedIds, etc.)
  // without needing to thread them as props.
  function renderRows(opps) {
    return opps.map((o) => {
      const side = o.side.toLowerCase();
      const stars = o.stars || '★';
      const starColor = stars.length >= 2 ? '#16a34a' : stars.length === 1 ? '#ca8a04' : 'var(--text-faint)';
      const kelly = o.kelly_dollars > 0 ? '$' + o.kelly_dollars.toFixed(2) : '—';
      const placed = placedSet.has(oppKey(o));
      const isExpanded = expandedId === o.ticker;
      const belowThreshold = o.passes_threshold === false || (o.passes_threshold === undefined && o.edge_pct < minEdge);
      const edgeFmt = fmtSigned(o.edge_pct, 1);
      return (
        <React.Fragment key={o.ticker}>
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
            <td style={{ padding: '12px 16px', fontFamily: 'ui-monospace, monospace', fontSize: 11, color: '#3b82f6' }}>
              <a
                href={kalshiMarketUrl(o.ticker)}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: '#3b82f6', textDecoration: 'none', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}
              >
                {o.ticker} ↗
              </a>
              {o.model_disagreement_flag && (
                <span
                  title={`NWS & ensemble disagree by ${o.model_disagreement_f}°F`}
                  style={{ marginLeft: 6, fontSize: 10, color: '#f59e0b',
                           background: 'rgba(245,158,11,0.12)', padding: '1px 4px', borderRadius: 3 }}
                >
                  ⚠ {o.model_disagreement_f}°F gap
                </span>
              )}
            </td>
            <td style={{ padding: '12px 16px', fontWeight: 600 }}>{normCity(o.city)}</td>
            <td style={{ padding: '12px 16px' }}>
              <span style={{ display: 'inline-block', padding: '2px 8px', borderRadius: 999, background: side === 'yes' ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)', color: side === 'yes' ? '#16a34a' : '#ef4444', fontSize: 10, fontWeight: 600, textTransform: 'uppercase' }}>{side}</span>
            </td>
            <td style={{ padding: '12px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)' }}>{o.forecast_prob.toFixed(1)}%</td>
            <td style={{ padding: '12px 16px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)' }}>{o.market_prob.toFixed(1)}%</td>
            <td style={{ padding: '12px 16px', textAlign: 'right', color: edgeFmt.color, fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>{edgeFmt.text}</td>
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
                  const sp = sideAwareEntryPrice(o);
                  const kellyQty = o.kelly_qty || (o.kelly_dollars > 0 && sp > 0 ? Math.max(1, Math.floor(o.kelly_dollars / sp)) : 1);
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
              <td colSpan="13" style={{ padding: '16px 24px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 12 }}>
                  <div>
                    <div style={{ color: 'var(--text-faint)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>Market Mid</div>
                    <div style={{ fontWeight: 600, fontSize: 14, fontFamily: 'ui-monospace, monospace' }}>{o.market_prob.toFixed(1)}%</div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--text-faint)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>Model Prob</div>
                    <div style={{ fontWeight: 600, fontSize: 14, fontFamily: 'ui-monospace, monospace', color: '#16a34a' }}>{o.forecast_prob.toFixed(1)}%</div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--text-faint)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>Edge</div>
                    <div style={{ fontWeight: 700, fontSize: 14, fontFamily: 'ui-monospace, monospace', color: edgeFmt.color }}>
                      {edgeFmt.text}
                    </div>
                  </div>
                  {o.kelly_dollars > 0 && (
                    <div>
                      <div style={{ color: 'var(--text-faint)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>Kelly $</div>
                      <div style={{ fontWeight: 600, fontSize: 14, fontFamily: 'ui-monospace, monospace' }}>${o.kelly_dollars.toFixed(2)}</div>
                    </div>
                  )}
                  {o.forecast_temp != null && (
                    <div>
                      <div style={{ color: 'var(--text-faint)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>Forecast Temp</div>
                      <div style={{ fontWeight: 600, fontSize: 14, fontFamily: 'ui-monospace, monospace' }}>{Number(o.forecast_temp).toFixed(1)}°F</div>
                    </div>
                  )}
                  {o.condition?.threshold != null && (
                    <div>
                      <div style={{ color: 'var(--text-faint)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>Threshold</div>
                      <div style={{ fontWeight: 600, fontSize: 14, fontFamily: 'ui-monospace, monospace' }}>{o.condition.threshold}°F</div>
                    </div>
                  )}
                  {o.ensemble_prob != null && (
                    <div>
                      <div style={{ color: 'var(--text-faint)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>Ensemble</div>
                      <div style={{ fontSize: 13, fontFamily: 'ui-monospace, monospace' }}>{o.ensemble_prob.toFixed(0)}%</div>
                    </div>
                  )}
                  {o.nws_prob != null && (
                    <div>
                      <div style={{ color: 'var(--text-faint)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>NWS</div>
                      <div style={{ fontSize: 13, fontFamily: 'ui-monospace, monospace' }}>{o.nws_prob.toFixed(0)}%</div>
                    </div>
                  )}
                  {o.clim_prob != null && (
                    <div>
                      <div style={{ color: 'var(--text-faint)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>Climatology</div>
                      <div style={{ fontSize: 13, fontFamily: 'ui-monospace, monospace' }}>{o.clim_prob.toFixed(0)}%</div>
                    </div>
                  )}
                  {(() => {
                    const td = o.target_date || o.expiry;
                    if (!td) return null;
                    const days = Math.ceil((new Date(td) - new Date()) / 86400000);
                    return (
                      <div>
                        <div style={{ color: 'var(--text-faint)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>Days Out</div>
                        <div style={{ fontWeight: 600, fontSize: 14, fontFamily: 'ui-monospace, monospace' }}>{days}d</div>
                      </div>
                    );
                  })()}
                  {o.method && (
                    <div>
                      <div style={{ color: 'var(--text-faint)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>Method</div>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{o.method}</div>
                    </div>
                  )}
                </div>
                <div style={{ padding: '10px 12px', background: 'var(--bg-card)', borderRadius: 7, border: '1px solid var(--border)', fontSize: 12, color: 'var(--text-muted)' }}>
                  <strong>Market:</strong> {o.ticker} · <strong>Side:</strong> {o.side.toUpperCase()} · <strong>Risk:</strong> {o.time_risk}
                  {o.near_threshold && <span style={{ marginLeft: 12, color: '#ca8a04' }}>⚠ Near threshold</span>}
                  {o.is_hedge && <span style={{ marginLeft: 12 }}>↔ Hedges existing position</span>}
                </div>
                {o.model_disagreement_flag && (
                  <div style={{ marginTop: 8, fontSize: 11, color: '#d97706' }}>
                    ⚠ Model disagreement: NWS vs ensemble gap = {o.model_disagreement_f}°F — reduced confidence
                  </div>
                )}
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
            {rejectedCount > 0 && (
              <span style={{ marginLeft: 10 }}>
                · {rejectedCount} dismissed{' '}
                <button onClick={handleClearRejections} style={{
                  background: 'none', border: 'none', padding: 0, color: '#3b82f6',
                  fontSize: 13, cursor: 'pointer', textDecoration: 'underline',
                }}>Clear</button>
              </span>
            )}
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
      {effSelectedIds.size > 0 && (
        <div style={{
          position: 'fixed', bottom: 20, left: '50%', transform: 'translateX(-50%)',
          background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 12,
          padding: '12px 20px', boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
          display: 'flex', gap: 16, alignItems: 'center', zIndex: 100,
        }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>{effSelectedIds.size} selected</span>
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
          <button onClick={() => setSelectedIds(prev => {
            const next = new Set(prev);
            effSelectedIds.forEach(id => next.delete(id));
            return next;
          })} style={{
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

      {/* opus review MEDIUM (batch-45): filtered.length===0 now also happens
          when every candidate was dismissed, not just when the scan produced
          nothing -- distinguish the two so rejecting everything doesn't make
          the page falsely claim there's no scan data (the exact "dashboard
          tells the operator something untrue" class of bug this batch targets). */}
      {filtered.length === 0 && rejectedCount > 0 && (
        <section style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 14, padding: '40px 24px', marginBottom: 18,
          textAlign: 'center',
        }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>✗</div>
          <h3 style={{ margin: '0 0 8px', fontSize: 16, fontWeight: 600 }}>All signals dismissed</h3>
          <p style={{ margin: '0 0 20px', color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.5, maxWidth: 400, marginLeft: 'auto', marginRight: 'auto' }}>
            All {rejectedCount} candidate{rejectedCount !== 1 ? 's' : ''} from the last scan {rejectedCount !== 1 ? 'were' : 'was'} rejected. They'll reappear after 24h, or clear now to see them again.
          </p>
          <button onClick={handleClearRejections} style={{
            padding: '9px 18px', borderRadius: 8, border: '1px solid var(--border)',
            background: 'var(--bg-subtle)', color: 'var(--text)', fontWeight: 600, fontSize: 13, cursor: 'pointer',
          }}>Clear dismissed signals</button>
        </section>
      )}

      {filtered.length === 0 && rejectedCount === 0 && (
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
              { label: 'Edge',            ...(() => { const f = fmtSigned(selectedOpp.edge_pct, 1); return { value: f.text, color: f.color }; })() },
              { label: 'Forecast p',      value: selectedOpp.forecast_prob.toFixed(1) + '%' },
              { label: 'Market p',        value: selectedOpp.market_prob.toFixed(1) + '%' },
              { label: 'Kelly $',         value: selectedOpp.kelly_dollars > 0 ? '$' + selectedOpp.kelly_dollars.toFixed(2) : '—' },
              { label: 'Kelly contracts', value: (() => { const sp2 = sideAwareEntryPrice(selectedOpp); const kq = selectedOpp.kelly_qty || (selectedOpp.kelly_dollars > 0 && sp2 > 0 ? Math.max(1, Math.floor(selectedOpp.kelly_dollars / sp2)) : 0); return kq > 0 ? kq + ' cts' : '—'; })() },
            ].map(item => (
              <div key={item.label}>
                <div style={{ color: 'var(--text-faint)', fontSize: 11, marginBottom: 4 }}>{item.label}</div>
                <div style={{ fontWeight: 600, fontSize: 15, fontFamily: 'ui-monospace, monospace', color: item.color || 'inherit' }}>{item.value}</div>
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
              // batch-26: cost/price shown must match what handleConfirm will
              // actually submit (the side-aware ask price), not the YES mid.
              const entryPrice = sideAwareEntryPrice(confirmPending.opp);
              const cost = confirmPending.qty * entryPrice;
              const remaining = (M.stats.balance || 0) - M.positions.reduce((a, p) => a + p.cost, 0) - cost;
              return (
                <p style={{ margin: '0 0 18px', color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.5 }}>
                  Place <strong>{confirmPending.qty} contract{confirmPending.qty !== 1 ? 's' : ''}</strong> of{' '}
                  <strong style={{ color: '#3b82f6' }}>{confirmPending.opp.ticker}</strong>{' '}
                  <strong style={{ color: confirmPending.opp.side === 'yes' ? '#16a34a' : '#ef4444' }}>
                    {(confirmPending.opp.side || 'YES').toUpperCase()}
                  </strong>{' '}
                  at <strong>{(entryPrice * 100).toFixed(1)}¢</strong>?
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

      {/* Bulk confirmation modal — C-1: lists every eligible order and the
          combined total cost before any request fires, same as single-approve.
          opus review MEDIUM-3: renders ONLY from the bulkConfirmPending
          snapshot taken at click time (handleBulkApprove) -- never
          re-derives bulkEligibleOpps() here, so a poll landing while the
          modal is open can't change what gets submitted out from under
          what the operator is looking at. */}
      {bulkConfirmPending && bulkConfirmPending.rows.length > 0 && (() => {
        const { rows: snapshotRows, excludedCount } = bulkConfirmPending;
        const rows = snapshotRows.map(({ opp, qty }) => {
          const price = sideAwareEntryPrice(opp);
          return { opp, price, qty, cost: price * qty };
        });
        const totalCost = rows.reduce((a, r) => a + r.cost, 0);
        const remaining = (M.stats.balance || 0) - M.positions.reduce((a, p) => a + p.cost, 0) - totalCost;
        return (
          <div
            onKeyDown={e => { if (e.key === 'Enter') handleBulkConfirm(); }}
            style={{
              position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
            }} onClick={() => setBulkConfirmPending(null)}>
            <div onClick={e => e.stopPropagation()} style={{
              background: 'var(--bg-card)', border: '1px solid var(--border)',
              borderRadius: 14, padding: '24px 28px', minWidth: 380, maxWidth: 480,
            }}>
              <h3 style={{ margin: '0 0 6px', fontSize: 16, fontWeight: 700 }}>Confirm {rows.length} trade{rows.length !== 1 ? 's' : ''}</h3>
              <div style={{ maxHeight: 220, overflowY: 'auto', margin: '10px 0 14px', border: '1px solid var(--border)', borderRadius: 8 }}>
                {rows.map(({ opp, price, qty, cost }) => (
                  <div key={opp.ticker} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '8px 12px', fontSize: 12, borderBottom: '1px solid var(--bg-muted)',
                  }}>
                    <span style={{ fontFamily: 'ui-monospace, monospace' }}>
                      {opp.ticker} <span style={{ color: opp.side === 'yes' ? '#16a34a' : '#ef4444' }}>{(opp.side || 'yes').toUpperCase()}</span>
                    </span>
                    <span style={{ color: 'var(--text-muted)' }}>{qty}× @ {(price * 100).toFixed(1)}¢ = ${cost.toFixed(2)}</span>
                  </div>
                ))}
              </div>
              <p style={{ margin: '0 0 18px', color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.5 }}>
                Total cost: <strong>${totalCost.toFixed(2)}</strong>.
                {excludedCount > 0 && <> {excludedCount} selected signal{excludedCount !== 1 ? 's' : ''} excluded (no positive edge, or already placed).</>}
                <br />
                <span style={{ fontSize: 12, color: remaining < 10 ? '#ef4444' : 'var(--text-faint)' }}>
                  Balance after: <strong>${remaining.toFixed(2)}</strong>
                </span>
              </p>
              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                <button onClick={() => setBulkConfirmPending(null)} style={{
                  padding: '9px 18px', borderRadius: 8, border: '1px solid var(--border)',
                  background: 'var(--bg-card)', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13, cursor: 'pointer',
                }}>Cancel</button>
                <button onClick={handleBulkConfirm} style={{
                  padding: '9px 20px', borderRadius: 8, border: 'none',
                  background: '#16a34a', color: 'white', fontWeight: 700, fontSize: 13, cursor: 'pointer',
                }}>Place {rows.length} order{rows.length !== 1 ? 's' : ''}</button>
              </div>
            </div>
          </div>
        );
      })()}
    </main>
  );
}
