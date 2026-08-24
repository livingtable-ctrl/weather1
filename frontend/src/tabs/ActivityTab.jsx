import React, { useState, useContext, useMemo } from 'react';
import { DataContext } from '../DataContext.js';

// Level config: accent is used for the left border and badge; bg is the row tint on hover/error rows.
const LEVEL = {
  error: { accent: '#ef4444', bg: 'rgba(239,68,68,0.05)', color: '#ef4444', label: 'ERROR', icon: '✕' },
  warn:  { accent: '#f59e0b', bg: 'rgba(245,158,11,0.05)', color: '#ca8a04', label: 'WARN',  icon: '⚠' },
  info:  { accent: '#3b82f6', bg: 'transparent',           color: '#64748b', label: 'INFO',  icon: 'i' },
  good:  { accent: '#22c55e', bg: 'rgba(34,197,94,0.05)',  color: '#16a34a', label: 'OK',    icon: '✓' },
};

const FILTERS = ['all', 'error', 'warn', 'info', 'good'];

export default function ActivityTab() {
  const M = useContext(DataContext);
  const [levelFilter, setLevelFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');

  const allAlerts = M.alerts || [];

  const counts = useMemo(() => ({
    error: allAlerts.filter(e => e.level === 'error').length,
    warn:  allAlerts.filter(e => e.level === 'warn').length,
    info:  allAlerts.filter(e => e.level === 'info').length,
    good:  allAlerts.filter(e => e.level === 'good').length,
  }), [allAlerts]);

  const events = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return allAlerts.filter(e => {
      if (levelFilter !== 'all' && e.level !== levelFilter) return false;
      if (q && !(e.text || '').toLowerCase().includes(q)) return false;
      return true;
    });
  }, [allAlerts, levelFilter, searchQuery]);

  return (
    <main style={{ maxWidth: 1000, margin: '0 auto', padding: '24px 28px 40px' }}>

      {/* ── Header ── */}
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>Activity log</h1>
        <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
          Cron runs, trades, circuit breakers, alerts.
        </p>
      </div>

      {/* ── Count chips + search + filter bar ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>

        {/* Live count chips — click to filter */}
        <div style={{ display: 'flex', gap: 8 }}>
          {counts.error > 0 && (
            <button onClick={() => setLevelFilter('error')} style={{
              display: 'flex', alignItems: 'center', gap: 5,
              padding: '5px 11px', borderRadius: 20, cursor: 'pointer',
              border: levelFilter === 'error' ? '1px solid #ef4444' : '1px solid rgba(239,68,68,0.3)',
              background: levelFilter === 'error' ? 'rgba(239,68,68,0.12)' : 'rgba(239,68,68,0.07)',
              color: '#ef4444', fontSize: 12, fontWeight: 600,
            }}>
              <span>✕</span> {counts.error} error{counts.error !== 1 ? 's' : ''}
            </button>
          )}
          {counts.warn > 0 && (
            <button onClick={() => setLevelFilter('warn')} style={{
              display: 'flex', alignItems: 'center', gap: 5,
              padding: '5px 11px', borderRadius: 20, cursor: 'pointer',
              border: levelFilter === 'warn' ? '1px solid #f59e0b' : '1px solid rgba(245,158,11,0.3)',
              background: levelFilter === 'warn' ? 'rgba(245,158,11,0.12)' : 'rgba(245,158,11,0.07)',
              color: '#ca8a04', fontSize: 12, fontWeight: 600,
            }}>
              <span>⚠</span> {counts.warn} warning{counts.warn !== 1 ? 's' : ''}
            </button>
          )}
          {counts.error === 0 && counts.warn === 0 && (
            <span style={{ fontSize: 12, color: '#16a34a', fontWeight: 600 }}>✓ No errors or warnings</span>
          )}
        </div>

        {/* Text search — filters by message content */}
        <input
          type="text"
          placeholder="Search messages…"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          style={{
            padding: '5px 11px', borderRadius: 20, fontSize: 12,
            border: '1px solid var(--border)', background: 'var(--bg-card)',
            color: 'var(--text)', outline: 'none', width: 200,
          }}
        />

        {/* Level filter pills */}
        <div style={{ display: 'flex', gap: 4 }}>
          {FILTERS.map(f => {
            const cfg = LEVEL[f];
            const active = levelFilter === f;
            return (
              <button key={f} onClick={() => setLevelFilter(f)} style={{
                padding: '5px 13px', borderRadius: 20, fontSize: 11, fontWeight: 600, cursor: 'pointer',
                border: active
                  ? `1px solid ${cfg ? cfg.accent : '#3b82f6'}`
                  : '1px solid var(--border)',
                background: active
                  ? cfg ? `${cfg.bg || 'rgba(59,130,246,0.08)'}` : 'rgba(59,130,246,0.08)'
                  : 'var(--bg-card)',
                color: active
                  ? cfg ? cfg.color : '#3b82f6'
                  : 'var(--text-muted)',
                transition: 'all 0.12s',
              }}>
                {f === 'all' ? 'ALL' : cfg.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Log list ── */}
      <section style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 14,
        overflow: 'hidden',
      }}>
        {events.length === 0 ? (
          <div style={{ padding: '48px 24px', textAlign: 'center', color: 'var(--text-faint)', fontSize: 13 }}>
            {levelFilter === 'all'
              ? 'No activity yet — events appear here when the bot runs.'
              : `No ${LEVEL[levelFilter]?.label ?? levelFilter} events.`}
          </div>
        ) : events.map((ev, i) => {
          const cfg = LEVEL[ev.level] || LEVEL.info;
          const isError = ev.level === 'error';
          return (
            <div key={i} style={{
              display: 'grid',
              // columns: [left-accent gap] [time] [badge] [message]
              gridTemplateColumns: '4px 56px 54px 1fr',
              gap: '0 12px',
              alignItems: 'start',
              padding: '11px 18px 11px 0',
              borderBottom: i < events.length - 1 ? '1px solid var(--bg-muted)' : 'none',
              background: isError ? 'rgba(239,68,68,0.03)' : 'transparent',
            }}>

              {/* Colored left accent bar */}
              <div style={{
                gridColumn: 1,
                alignSelf: 'stretch',
                background: cfg.accent,
                opacity: 0.7,
                borderRadius: 2,
                minHeight: 20,
              }} />

              {/* Timestamp */}
              <span style={{
                gridColumn: 2,
                fontSize: 11,
                fontFamily: 'ui-monospace, monospace',
                color: 'var(--text-faint)',
                paddingTop: 2,
                letterSpacing: '0.02em',
              }}>
                {ev.ts}
              </span>

              {/* Level badge */}
              <span style={{
                gridColumn: 3,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 3,
                fontSize: 10,
                fontWeight: 700,
                padding: '2px 7px',
                borderRadius: 5,
                background: `${cfg.accent}22`,
                color: cfg.color,
                letterSpacing: '0.04em',
                paddingTop: 2,
              }}>
                {cfg.icon} {cfg.label}
              </span>

              {/* Message */}
              <span style={{
                gridColumn: 4,
                fontSize: 13,
                color: isError ? '#fca5a5' : 'var(--text)',
                lineHeight: 1.5,
                wordBreak: 'break-word',
              }}>
                {ev.text}
              </span>
            </div>
          );
        })}
      </section>

      {events.length > 0 && (
        <p style={{ margin: '10px 0 0', fontSize: 11, color: 'var(--text-faint)', textAlign: 'right' }}>
          {events.length} event{events.length !== 1 ? 's' : ''}
          {levelFilter !== 'all' ? ` · filtered to ${LEVEL[levelFilter]?.label}` : ''}
        </p>
      )}
    </main>
  );
}
