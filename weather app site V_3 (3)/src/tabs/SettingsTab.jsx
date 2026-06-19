import React, { useState, useEffect, useContext, useRef } from 'react';
import { DataContext } from '../DataContext.js';
import { authHeader } from '../useData.js';

export default function SettingsTab() {
  const M = useContext(DataContext);
  const s = M.stats;
  const [overrideReason, setOverrideReason] = useState('');
  const [overrideDuration, setOverrideDuration] = useState(60);
  const [overrideMsg, setOverrideMsg] = useState('');
  const { cronState, handleRunCron, handleCancelCron } = M;
  const cronLogRef = useRef(null);
  const [reportMsg, setReportMsg] = useState('');
  const backupAgeHours = M.backupStatus?.last_backup_at
    ? (Date.now() - new Date(M.backupStatus.last_backup_at)) / 3600000
    : Infinity;
  const backupStale = backupAgeHours > 24;

  function handleDownloadReport() {
    setReportMsg('Generating…');
    fetch('/api/weekly-report', { headers: authHeader() })
      .then(r => {
        if (!r.ok) return r.json().then(d => { throw new Error(d.error || 'Failed'); });
        return r.blob().then(blob => {
          const ct = r.headers.get('content-type') || '';
          const ext = ct.includes('pdf') ? '.pdf' : '.html';
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url; a.download = `weekly_report${ext}`; a.click();
          URL.revokeObjectURL(url);
          setReportMsg('✓ Downloaded');
          setTimeout(() => setReportMsg(''), 3000);
        });
      })
      .catch(e => { setReportMsg(`✗ ${e.message}`); setTimeout(() => setReportMsg(''), 4000); });
  }

  // Config params — all read from /api/config (M.config); stats fallback for max_daily_spend
  const configRows = [
    { key: 'strategy',          label: 'Sizing strategy',     value: M.config?.strategy || s.strategy || '—' },
    { key: 'env',               label: 'Environment',         value: M.config?.env       || s.env       || '—' },
    { key: 'max_daily_spend',     label: 'Max daily spend',     value: (M.config?.max_daily_spend ?? s.max_daily_spend) != null ? '$' + (M.config?.max_daily_spend ?? s.max_daily_spend) : '—' },
    { key: 'max_same_day_spend', label: 'Max same-day spend',  value: M.config?.max_same_day_spend != null ? '$' + M.config.max_same_day_spend : '—' },
    { key: 'min_edge',          label: 'Min edge threshold',  value: M.config?.min_edge != null ? (M.config.min_edge * 100).toFixed(1) + '%' : '—' },
    { key: 'strong_edge',       label: 'Strong edge',         value: M.config?.strong_edge != null ? (M.config.strong_edge * 100).toFixed(1) + '%' : '—' },
    { key: 'drawdown_halt_pct', label: 'Drawdown halt %',     value: M.config?.drawdown_halt_pct != null ? (M.config.drawdown_halt_pct * 100).toFixed(1) + '%' : '—' },
    { key: 'max_days_out',      label: 'Max days out',        value: M.config?.max_days_out != null ? M.config.max_days_out + ' days' : '—' },
  ];

  function handleSetOverride() {
    if (!overrideReason.trim()) { setOverrideMsg('Reason required.'); return; }
    fetch('/api/override', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader() },
      body: JSON.stringify({ reason: overrideReason.trim(), duration_minutes: overrideDuration }),
    })
      .then(r => r.json())
      .then(d => {
        setOverrideMsg(d.error ? `✗ ${d.error}` : `✓ Override set for ${overrideDuration} min`);
        setOverrideReason('');
        setTimeout(() => setOverrideMsg(''), 4000);
      })
      .catch(() => { setOverrideMsg('✗ Request failed'); setTimeout(() => setOverrideMsg(''), 3000); });
  }

  // Auto-scroll log to bottom when new lines arrive
  useEffect(() => {
    if (cronLogRef.current) cronLogRef.current.scrollTop = cronLogRef.current.scrollHeight;
  }, [cronState?.log?.length]);

  function handleClearOverride() {
    fetch('/api/override', {
      method: 'DELETE',
      headers: authHeader(),
    })
      .then(r => r.json())
      .then(d => {
        setOverrideMsg(d.error ? `✗ ${d.error}` : '✓ Override cleared');
        setTimeout(() => setOverrideMsg(''), 3000);
      })
      .catch(() => { setOverrideMsg('✗ Request failed'); setTimeout(() => setOverrideMsg(''), 3000); });
  }

  return (
    <main style={{ maxWidth: 1000, margin: '0 auto', padding: '24px 28px 40px' }}>
      <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Settings</h1>
      <p style={{ margin: '0 0 24px', color: 'var(--text-muted)', fontSize: 13 }}>
        Bot configuration, manual overrides, and A/B test status.
      </p>

      {/* Config */}
      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden', marginBottom: 18 }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Bot configuration</h3>
          <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>Live values from /api/config</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 }}>
          {configRows.map((row, i) => (
            <div key={row.key} style={{
              padding: '14px 20px', borderBottom: '1px solid var(--bg-muted)',
              borderRight: i % 2 === 0 ? '1px solid var(--bg-muted)' : 'none',
            }}>
              <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 4 }}>{row.label}</div>
              <div style={{ fontWeight: 600, fontFamily: 'ui-monospace, monospace', fontSize: 14 }}>{row.value}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Weekly report */}
      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '16px 20px', marginBottom: 18, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 3 }}>Weekly report</h3>
          <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: 12 }}>Download a PDF summary of recent trades, P&L, and forecast accuracy.</p>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {reportMsg && <span style={{ fontSize: 12, color: reportMsg.startsWith('✓') ? '#16a34a' : reportMsg === 'Generating…' ? 'var(--text-muted)' : '#ef4444', fontWeight: 600 }}>{reportMsg}</span>}
          <button onClick={handleDownloadReport} disabled={reportMsg === 'Generating…'} style={{
            padding: '9px 18px', borderRadius: 8, border: '1px solid var(--border)',
            background: 'var(--bg-subtle)', color: 'var(--text)', fontWeight: 600, fontSize: 13,
            cursor: reportMsg === 'Generating…' ? 'not-allowed' : 'pointer',
          }}>Download report</button>
        </div>
      </section>

      {/* Manual override */}
      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Manual override</h3>
        <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 16, lineHeight: 1.4 }}>
          Override the bot's trading gate for a fixed window. Use when you want to force-allow trades despite a drawdown halt or cooldown. Requires a reason for the audit log.
        </p>

        {s.override_until && (
          <div style={{ padding: '10px 14px', borderRadius: 8, background: 'rgba(234,179,8,0.08)', border: '1px solid rgba(234,179,8,0.3)', color: '#92400e', fontSize: 12, marginBottom: 14 }}>
            ⚠ Override active until {new Date(s.override_until).toLocaleTimeString()}
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 10, alignItems: 'end' }}>
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>Reason</label>
            <input value={overrideReason} onChange={e => setOverrideReason(e.target.value)}
              placeholder="e.g. Testing new edge threshold manually"
              style={{ width: '100%', padding: '9px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-subtle)', fontSize: 13, color: 'var(--text)', outline: 'none', boxSizing: 'border-box' }} />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>Duration (min)</label>
            <input type="number" min="5" max="480" value={overrideDuration} onChange={e => setOverrideDuration(+e.target.value)}
              style={{ width: 90, padding: '9px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-subtle)', fontSize: 13, color: 'var(--text)', outline: 'none' }} />
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={handleSetOverride} style={{ padding: '9px 18px', borderRadius: 8, border: 'none', background: '#3b82f6', color: 'white', fontWeight: 600, fontSize: 13, cursor: 'pointer' }}>Set override</button>
            <button onClick={handleClearOverride} style={{ padding: '9px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13, cursor: 'pointer' }}>Clear</button>
          </div>
        </div>
        {overrideMsg && <div style={{ marginTop: 10, fontSize: 12, color: '#16a34a' }}>{overrideMsg}</div>}
      </section>

      {/* A/B tests */}
      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>A/B tests</h3>
        <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
          Active experiments. Variant is assigned per-trade at entry time.
        </p>
        {M.abTests && M.abTests.length > 0 ? (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 12 }}>
                {['Test', 'Variant', 'Trades', 'Edge (realized)'].map(h => (
                  <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {M.abTests.map((t, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--bg-muted)' }}>
                  <td style={{ padding: '12px 14px', fontWeight: 600 }}>{t.name}</td>
                  <td style={{ padding: '12px 14px', fontFamily: 'ui-monospace, monospace' }}>{t.variant}</td>
                  <td style={{ padding: '12px 14px', fontFamily: 'ui-monospace, monospace' }}>{t.trades ?? 0}</td>
                  <td style={{ padding: '12px 14px', fontFamily: 'ui-monospace, monospace', color: 'var(--text-muted)' }}>
                    {t.edge_realized != null ? (t.edge_realized * 100).toFixed(1) + '%' : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-faint)', fontSize: 13 }}>
            No A/B tests active
          </div>
        )}
      </section>

      {/* Backup status */}
      {M.backupStatus && (
        <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '16px 20px', marginBottom: 18 }}>
          <h3 style={{ margin: '0 0 10px', fontSize: 15, fontWeight: 600 }}>Backup status</h3>
          <div style={{ display: 'flex', gap: 24, fontSize: 13, flexWrap: 'wrap' }}>
            <div>
              <span style={{ color: backupStale ? '#ca8a04' : 'var(--text-muted)', fontSize: 11 }}>Last backup</span>
              <div style={{ fontWeight: 600, fontFamily: 'ui-monospace, monospace', marginTop: 2 }}>
                {M.backupStatus.last_backup_at
                  ? <>
                      {new Date(M.backupStatus.last_backup_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                      {backupStale && <span style={{ marginLeft: 6, color: '#ca8a04', fontSize: 11 }}>⚠ {Math.floor(backupAgeHours)}h ago</span>}
                    </>
                  : <span style={{ color: '#ef4444' }}>Never</span>}
              </div>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>Backup count</span>
              <div style={{ fontWeight: 600, fontFamily: 'ui-monospace, monospace', marginTop: 2 }}>{M.backupStatus.backup_count ?? 0}</div>
            </div>
            {M.backupStatus.backup_size_mb != null && (
              <div>
                <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>Latest size</span>
                <div style={{ fontWeight: 600, fontFamily: 'ui-monospace, monospace', marginTop: 2 }}>{M.backupStatus.backup_size_mb} MB</div>
              </div>
            )}
            {M.backupStatus.data_mtime && (
              <div>
                <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>Data last modified</span>
                <div style={{ fontWeight: 600, fontFamily: 'ui-monospace, monospace', marginTop: 2 }}>
                  {new Date(M.backupStatus.data_mtime).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Cron scan */}
      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px', marginBottom: 18 }}>

        {/* Kill switch warning — shown inline so user doesn't have to scroll to fix it */}
        {s.kill_switch && (
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '12px 16px', borderRadius: 10, marginBottom: 16,
            background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.3)',
          }}>
            <div>
              <span style={{ fontWeight: 700, color: '#ef4444', fontSize: 13 }}>Kill switch is active</span>
              <span style={{ color: 'var(--text-muted)', fontSize: 12, marginLeft: 10 }}>
                The scan will run but no trades will be placed until you resume.
              </span>
            </div>
            <button
              onClick={() => { if (window.confirm('Resume trading?')) fetch('/api/resume', { method: 'POST', headers: authHeader() }).then(() => M.refresh()); }}
              style={{
                padding: '7px 16px', borderRadius: 7, border: '1px solid #16a34a',
                background: 'rgba(34,197,94,0.08)', color: '#16a34a',
                fontWeight: 600, fontSize: 12, cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0, marginLeft: 16,
              }}>
              Resume trading
            </button>
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: cronState.log.length ? 14 : 0 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Cron scan</h3>
            <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: 12 }}>
              {cronState.status === 'running' && (s.kill_switch ? 'Scanning markets — no trades will fire until kill switch is cleared.' : 'Scan in progress — signals will update when complete.')}
              {cronState.status === 'done'    && 'Scan complete. Signals refreshed.'}
              {cronState.status === 'error'   && 'Scan finished with errors — see log below.'}
              {cronState.status === 'cancelled' && 'Scan cancelled.'}
              {(cronState.status === 'idle')  && (() => {
                const meta = M.signalsMeta;
                if (!meta?.generatedAt) return 'Run a market scan to refresh signals and place paper trades if edges are found.';
                // Server always sends UTC; if no timezone suffix, append Z so the browser
                // doesn't parse as local time and produce a negative age.
                const ts = meta.generatedAt;
                const utcTs = (ts.includes('+') || ts.endsWith('Z')) ? ts : ts + 'Z';
                const ageMin = Math.round((Date.now() - new Date(utcTs)) / 60000);
                const label = ageMin < 60 ? `${ageMin}m ago` : `${Math.floor(ageMin / 60)}h ${ageMin % 60}m ago`;
                return `Last scan: ${label}. Run again to refresh signals.`;
              })()}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {cronState.status === 'running' && (
              <button onClick={handleCancelCron} style={{
                padding: '10px 16px', borderRadius: 8, border: '1px solid #ef4444',
                background: 'transparent', color: '#ef4444',
                fontWeight: 600, fontSize: 13, cursor: 'pointer',
              }}>Cancel</button>
            )}
            <button
              onClick={handleRunCron}
              disabled={cronState.status === 'running'}
              style={{
                padding: '10px 20px', borderRadius: 8, border: 'none',
                background: cronState.status === 'running' ? 'var(--bg-muted)' : '#3b82f6',
                color: cronState.status === 'running' ? 'var(--text-muted)' : 'white',
                fontWeight: 600, fontSize: 13,
                cursor: cronState.status === 'running' ? 'not-allowed' : 'pointer',
              }}>
              {cronState.status === 'running' ? 'Running…' : 'Run scan'}
            </button>
          </div>
        </div>
        {cronState.log.length > 0 && (
          <div ref={cronLogRef} style={{
            background: 'var(--bg-subtle)', border: '1px solid var(--border)',
            borderRadius: 8, padding: '10px 14px',
            maxHeight: 320, overflowY: 'auto',
            fontFamily: 'ui-monospace, monospace', fontSize: 11.5,
            lineHeight: 1.6, color: 'var(--text-muted)',
            whiteSpace: 'pre-wrap', wordBreak: 'break-all',
          }}>
            {cronState.log.map((line, i) => {
              const isError = /error|traceback|exception/i.test(line);
              const isWarn  = /warning|warn/i.test(line);
              const isTrade = /placed|trade|BUY|SELL|order/i.test(line);
              const color = isError ? '#ef4444' : isWarn ? '#f59e0b' : isTrade ? '#22c55e' : 'inherit';
              return <div key={i} style={{ color }}>{line}</div>;
            })}
            {cronState.status === 'running' && (
              <div style={{ color: '#3b82f6', marginTop: 4 }}>▌</div>
            )}
          </div>
        )}
      </section>

      {/* Kill switch */}
      <section style={{ background: 'var(--bg-card)', border: '1px solid #ef4444', borderRadius: 14, padding: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: '#ef4444', marginBottom: 4 }}>Kill switch</h3>
            <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: 12 }}>
              Halt all new orders immediately. Use the resume button or restart the bot to re-enable.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button onClick={() => { if (window.confirm('Engage kill switch?')) fetch('/api/halt', { method: 'POST', headers: authHeader() }); }}
              style={{ padding: '10px 20px', borderRadius: 8, border: 'none', background: '#ef4444', color: 'white', fontWeight: 600, fontSize: 13, cursor: 'pointer' }}>
              Halt
            </button>
            <button onClick={() => { if (window.confirm('Resume trading?')) fetch('/api/resume', { method: 'POST', headers: authHeader() }); }}
              style={{ padding: '10px 20px', borderRadius: 8, border: '1px solid #16a34a', background: 'transparent', color: '#16a34a', fontWeight: 600, fontSize: 13, cursor: 'pointer' }}>
              Resume
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}
