import React, { useContext } from 'react';
import { DataContext } from '../DataContext.js';
import { normCity } from '../shared.jsx';

export default function ForecastTab() {
  const M = useContext(DataContext);
  return (
    <main style={{ maxWidth: 1360, margin: '0 auto', padding: '24px 28px 40px' }}>
      <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Forecast</h1>
      <p style={{ margin: '0 0 24px', color: 'var(--text-muted)', fontSize: 13 }}>
        Today &amp; tomorrow forecasts, city calibration, model ensemble spread.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, marginBottom: 18 }}>
        {[['Today', M.todayForecasts], ['Tomorrow', M.tomorrowForecasts]].map(([label, data]) => (
          <section key={label} style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden' }}>
            <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)' }}>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>{label}</h3>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)', fontSize: 11 }}>
                  {['City', 'High', 'Range', 'Precip', 'Models'].map(h => (
                    <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontWeight: 500, borderBottom: '1px solid var(--border)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(data).map(([city, f]) => {
                  const spread = f.high_range[1] - f.high_range[0];
                  return (
                    <tr key={city} style={{ borderBottom: '1px solid var(--bg-muted)' }}>
                      <td style={{ padding: '10px 14px', fontWeight: 600 }}>{normCity(city)}</td>
                      <td style={{ padding: '10px 14px', fontFamily: 'ui-monospace, monospace' }}>{f.high_f.toFixed(1)}°F</td>
                      <td style={{ padding: '10px 14px', fontFamily: 'ui-monospace, monospace', color: spread <= 2 ? '#16a34a' : spread <= 5 ? '#ca8a04' : '#ef4444' }}>
                        {f.high_range[0].toFixed(0)}–{f.high_range[1].toFixed(0)}°
                        <span style={{ fontSize: 10, opacity: 0.75, marginLeft: 4 }}>({spread.toFixed(0)}°)</span>
                      </td>
                      <td style={{ padding: '10px 14px', color: f.precip_in > 0.01 ? '#ca8a04' : 'var(--text-faint)', fontSize: 11 }}>
                        {f.precip_in > 0.01 ? f.precip_in.toFixed(2) + '"' : 'Dry'}
                      </td>
                      <td style={{ padding: '10px 14px', color: f.models_used >= 3 ? '#16a34a' : '#ca8a04', fontSize: 11 }}>{f.models_used}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        ))}
      </div>

      <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px' }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>City calibration · Brier score</h3>
        <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 14, lineHeight: 1.4 }}>
          Lower = better. Target ≤0.20 per city. Accumulates after 10+ settled trades.
        </p>
        {Object.keys(M.cityBrier || {}).length === 0 && (
          <p style={{ color: 'var(--text-faint)', fontSize: 12, fontStyle: 'italic' }}>
            No data yet — requires 10+ settled trades per city.
          </p>
        )}
        {Object.entries(M.cityBrier || {}).sort((a, b) => Number(a[1]) - Number(b[1])).map(([city, brier]) => {
          const b = brier != null ? Number(brier) : null;
          const color = b == null ? '#8b949e' : b < 0.20 ? '#16a34a' : b < 0.30 ? '#ca8a04' : '#ef4444';
          // Cities over 0.25 get a 3% sliver so the row isn't visually blank.
          const pct = b != null ? Math.max(3, Math.min(100, ((0.25 - b) / 0.25) * 100)) : 0;
          return (
            <div key={city} style={{ marginBottom: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5 }}>
                <span style={{ fontWeight: 600 }}>{normCity(city)}</span>
                <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, fontWeight: 700, color }}>
                  {b != null ? b.toFixed(3) : '—'}
                </span>
              </div>
              <div style={{ height: 6, background: 'var(--bg-muted)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: pct + '%', height: '100%', background: color }} />
              </div>
            </div>
          );
        })}
      </section>
    </main>
  );
}
