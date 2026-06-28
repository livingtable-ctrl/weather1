# Category H: Dashboard UX — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elevate the dashboard with actionable UX improvements: EMOS calibration status card (H3), portfolio EV card (H7), keyboard shortcuts (H1), live/paper indicator (H2), signal drill-down (H6), weather alert display (H11), model disagreement indicator (H8), and reliability diagram (H9 — covered in D4 plan).

**Architecture:** All changes target the React/Vite frontend at `weather app site V_3 (3)/src/`. Rebuild with `npm run build` and the output goes to `static/dist/`. H3, H7, H8 are the highest-value UX additions. H1 (keyboard shortcuts) is a quick win. H2 (live/paper indicator) is purely cosmetic but operationally important.

**Tech Stack:** React 18, Vite, plain JSX (no TypeScript).

**Dashboard structure:**
- `src/App.jsx` — tab routing and global header
- `src/tabs/SignalsTab.jsx` — signal opportunities
- `src/tabs/PositionsTab.jsx` — open positions
- `src/tabs/TradesTab.jsx` — closed trade history
- `src/tabs/AnalyticsTab.jsx` — charts and metrics
- `src/useData.js` — data fetching hooks
- `src/shared.jsx` — shared components and helpers

**Build command:** `cd "weather app site V_3 (3)" && npm run build`

---

## H2: Live / Paper Mode Indicator

**Problem:** The dashboard shows trade data but nowhere indicates whether the bot is in LIVE mode (real Kalshi API) or PAPER mode. An operator might not know which mode is active without checking the server logs.

**Files:**
- Modify: `web_app.py` — add `kalshi_env` to `/api/status`
- Modify: `weather app site V_3 (3)/src/App.jsx` — add indicator badge in global header

- [ ] **Step 1: Expose `kalshi_env` from `/api/status`**

In `web_app.py`, find the `/api/status` route. Add to the returned dict:

```python
import os
"kalshi_env": os.getenv("KALSHI_ENV", "demo"),
"is_live": os.getenv("KALSHI_ENV", "demo").lower() == "prod",
```

- [ ] **Step 2: Add mode badge to `App.jsx`**

Find the header/nav section in `App.jsx`. After the app title, add:

```jsx
{/* Live/Paper mode indicator — shown prominently at all times */}
{data.status && (
  <span style={{
    marginLeft: 12,
    padding: '2px 8px',
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: '0.05em',
    background: data.status.is_live ? 'rgba(239,68,68,0.15)' : 'rgba(34,197,94,0.15)',
    color: data.status.is_live ? 'var(--color-red)' : 'var(--color-green)',
    border: `1px solid ${data.status.is_live ? 'var(--color-red)' : 'var(--color-green)'}`,
  }}>
    {data.status.is_live ? '● LIVE' : '◌ PAPER'}
  </span>
)}
```

- [ ] **Step 3: Rebuild and verify**

```
cd "weather app site V_3 (3)"
npm run build
```

Open dashboard in browser. The header should now show `● LIVE` (red) or `◌ PAPER` (green) depending on `KALSHI_ENV`.

- [ ] **Step 4: Commit**

```
git add web_app.py "weather app site V_3 (3)/src/App.jsx" static/dist/
git commit -m "feat(dashboard): live/paper mode indicator badge in global header"
```

---

## H3: EMOS Calibration Status Card

**Problem:** The Analytics tab shows Brier score but no indication of EMOS training status — whether `emos_params.json` exists, when it was last trained, and what the fitted parameters are. The operator needs to know if EMOS is live.

**Files:**
- Modify: `web_app.py` — add `/api/emos-status` endpoint
- Modify: `weather app site V_3 (3)/src/tabs/AnalyticsTab.jsx` — add EMOS status card

- [ ] **Step 1: Add `/api/emos-status` to `web_app.py`**

```python
@_app.route("/api/emos-status")
@_require_auth
def api_emos_status():
    """Return EMOS parameter status — whether trained, params, and training date."""
    from paths import EMOS_PARAMS_PATH
    import json

    if not EMOS_PARAMS_PATH.exists():
        return {
            "trained": False,
            "params": None,
            "message": "Not trained. Run: py main.py emos-train",
        }
    try:
        data = json.loads(EMOS_PARAMS_PATH.read_text())
        return {
            "trained": True,
            "params": {
                "a": round(data.get("a", 0), 4),
                "b": round(data.get("b", 0), 4),
                "c": round(data.get("c", 0), 4),
                "d": round(data.get("d", 0), 4),
                "n": data.get("n", 0),
                "mean_crps": data.get("mean_crps"),
            },
            "fitted_at": data.get("fitted_at"),
            "message": f"EMOS active (n={data.get('n', 0)} training rows)",
        }
    except Exception as exc:
        return {"trained": False, "error": str(exc), "message": "Error reading emos_params.json"}
```

- [ ] **Step 2: Add fetch to `useData.js`**

In `useData.js`, alongside other API fetches, add:

```javascript
const [emosStatus, setEmosStatus] = useState(null);

useEffect(() => {
  fetch('/api/emos-status')
    .then(r => r.json())
    .then(setEmosStatus)
    .catch(() => setEmosStatus({ trained: false, message: 'Unavailable' }));
}, []);

// Include emosStatus in the returned object
```

- [ ] **Step 3: Add EMOS status card to `AnalyticsTab.jsx`**

```jsx
function EmosStatusCard({ emos }) {
  if (!emos) return null;
  const cardStyle = {
    padding: '12px 16px',
    borderRadius: 6,
    background: 'var(--bg-surface)',
    border: `1px solid ${emos.trained ? 'var(--color-green)' : 'var(--border)'}`,
    marginBottom: 12,
  };
  return (
    <div style={cardStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{
          fontSize: 11, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
          background: emos.trained ? 'rgba(34,197,94,0.15)' : 'rgba(107,114,128,0.15)',
          color: emos.trained ? 'var(--color-green)' : 'var(--text-dim)',
        }}>
          {emos.trained ? 'EMOS ACTIVE' : 'EMOS NOT TRAINED'}
        </span>
        <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>{emos.message}</span>
      </div>
      {emos.trained && emos.params && (
        <div style={{ fontSize: 11, color: 'var(--text-dim)', fontFamily: 'monospace' }}>
          μ = {emos.params.a} + {emos.params.b}·μ_ens
          {' | '}
          σ = √({emos.params.c} + {emos.params.d}·σ²_ens)
          {' | '}
          n={emos.params.n}
          {emos.params.mean_crps != null && ` | CRPS=${emos.params.mean_crps.toFixed(3)}`}
        </div>
      )}
      {emos.trained && emos.fitted_at && (
        <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 2 }}>
          Fitted: {new Date(emos.fitted_at).toLocaleString()}
        </div>
      )}
      {!emos.trained && (
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
          Raw ensemble exceedance fractions in use (uncalibrated). Run emos-train to fix calibration.
        </div>
      )}
    </div>
  );
}
```

In `AnalyticsTab`, render it near the Brier score section:

```jsx
<EmosStatusCard emos={emosStatus} />
```

- [ ] **Step 4: Rebuild and verify**

```
cd "weather app site V_3 (3)"
npm run build
```

Open Analytics tab. Card shows green "EMOS ACTIVE" with params after running `py main.py emos-train`, or gray "EMOS NOT TRAINED" before that.

- [ ] **Step 5: Commit**

```
git add web_app.py "weather app site V_3 (3)/src/tabs/AnalyticsTab.jsx" "weather app site V_3 (3)/src/useData.js" static/dist/
git commit -m "feat(dashboard): EMOS calibration status card in Analytics tab"
```

---

## H7: Portfolio Expected Value Card

**Problem:** The dashboard shows open positions but no summary of their aggregate expected value (the sum of cost × model_edge). This is the most actionable single number for an operator assessing current risk.

**Files:**
- Modify: `web_app.py` — add portfolio EV to `/api/status` (covered in Plan B, item B3; reuse here for frontend)
- Modify: `weather app site V_3 (3)/src/tabs/PositionsTab.jsx` — add EV summary at top of tab

*(Prerequisite: `get_portfolio_expected_value()` must be added to `paper.py` per Plan B, item B3. Implement B3 first.)*

- [ ] **Step 1: Verify the backend field exists**

After completing Plan B's B3 (portfolio EV in paper.py), confirm that `/api/status` returns:

```json
{
  "portfolio_ev": 12.50,
  "portfolio_ev_roi_pct": 4.2,
  "portfolio_cost": 298.00
}
```

Use `curl http://localhost:5000/api/status` to verify.

- [ ] **Step 2: Add EV summary card to `PositionsTab.jsx`**

```jsx
function PortfolioEvCard({ status }) {
  if (!status || status.portfolio_ev == null) return null;
  const ev = status.portfolio_ev;
  const roi = status.portfolio_ev_roi_pct;
  const cost = status.portfolio_cost;

  return (
    <div style={{
      display: 'flex', gap: 16, padding: '10px 16px',
      background: 'var(--bg-surface)', borderRadius: 6,
      border: '1px solid var(--border)', marginBottom: 12,
    }}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Expected Profit</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: ev >= 0 ? 'var(--color-green)' : 'var(--color-red)' }}>
          {ev >= 0 ? '+' : ''}{ev.toFixed(2)}
        </div>
      </div>
      <div>
        <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>EV ROI</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: roi >= 0 ? 'var(--color-green)' : 'var(--color-red)' }}>
          {roi >= 0 ? '+' : ''}{roi.toFixed(1)}%
        </div>
      </div>
      <div>
        <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Deployed</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)' }}>
          ${cost.toFixed(2)}
        </div>
      </div>
    </div>
  );
}
```

In `PositionsTab`, above the positions table:

```jsx
<PortfolioEvCard status={status} />
```

- [ ] **Step 3: Rebuild and verify**

```
cd "weather app site V_3 (3)"
npm run build
```

Open Positions tab. The EV summary card should appear above the position list.

- [ ] **Step 4: Commit**

```
git add "weather app site V_3 (3)/src/tabs/PositionsTab.jsx" static/dist/
git commit -m "feat(dashboard): portfolio expected value summary card in Positions tab"
```

---

## H1: Keyboard Shortcuts

**Problem:** Navigating between tabs requires clicking. Experienced operators benefit from keyboard shortcuts (1=Signals, 2=Positions, 3=Trades, 4=Analytics).

**Files:**
- Modify: `weather app site V_3 (3)/src/App.jsx` — add keyboard event listener

- [ ] **Step 1: Add keyboard shortcut handler to `App.jsx`**

```jsx
// In App.jsx, inside the main component:
import { useEffect } from 'react';

// Add inside the component:
useEffect(() => {
  const handler = (e) => {
    // Ignore if user is typing in an input
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    const TAB_KEYS = { '1': 'signals', '2': 'positions', '3': 'trades', '4': 'analytics' };
    if (TAB_KEYS[e.key]) {
      setActiveTab(TAB_KEYS[e.key]);
    }
    // R to refresh data
    if (e.key === 'r' || e.key === 'R') {
      refreshData();
    }
  };
  window.addEventListener('keydown', handler);
  return () => window.removeEventListener('keydown', handler);
}, []);
```

- [ ] **Step 2: Add keyboard shortcut hints to tab labels**

For each tab button, add a small keyboard shortcut hint:

```jsx
<button onClick={() => setActiveTab('signals')}>
  Signals <kbd style={{ fontSize: 9, opacity: 0.5, marginLeft: 4 }}>1</kbd>
</button>
```

- [ ] **Step 3: Rebuild and verify**

```
cd "weather app site V_3 (3)"
npm run build
```

Open dashboard. Press `1`, `2`, `3`, `4` — should switch tabs. Press `R` — should refresh data.

- [ ] **Step 4: Commit**

```
git add "weather app site V_3 (3)/src/App.jsx" static/dist/
git commit -m "feat(dashboard): keyboard shortcuts (1-4 for tabs, R to refresh)"
```

---

## H6: Signal Drill-Down Panel

**Problem:** Signals show ticker, edge, and Kelly fraction but not the model inputs (ensemble temp, NWS forecast, market price, threshold). Operators can't quickly assess the signal quality without looking at logs.

**Files:**
- Modify: `weather app site V_3 (3)/src/tabs/SignalsTab.jsx` — add expandable row with model details

*(Prerequisite: D1 forecast attribution must be done first — the per-source probability fields must be in the API response.)*

- [ ] **Step 1: Add expand toggle state to `SignalsTab.jsx`**

```jsx
const [expandedTicker, setExpandedTicker] = useState(null);

// In the signal row:
<tr
  key={opp.ticker}
  onClick={() => setExpandedTicker(expandedTicker === opp.ticker ? null : opp.ticker)}
  style={{ cursor: 'pointer', background: expandedTicker === opp.ticker ? 'var(--bg-hover)' : undefined }}
>
```

- [ ] **Step 2: Render the expanded drill-down panel**

After each signal row, conditionally render:

```jsx
{expandedTicker === opp.ticker && (
  <tr>
    <td colSpan={8} style={{ padding: '8px 16px', background: 'var(--bg-hover)' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, fontSize: 12 }}>
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase' }}>Market Mid</div>
          <div style={{ fontWeight: 600 }}>{(opp.market_mid * 100).toFixed(1)}%</div>
        </div>
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase' }}>Model Prob</div>
          <div style={{ fontWeight: 600 }}>{(opp.our_prob * 100).toFixed(1)}%</div>
        </div>
        {opp.forecast_temp_f != null && (
          <div>
            <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase' }}>Forecast Temp</div>
            <div style={{ fontWeight: 600 }}>{opp.forecast_temp_f.toFixed(1)}°F</div>
          </div>
        )}
        {opp.threshold != null && (
          <div>
            <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase' }}>Threshold</div>
            <div style={{ fontWeight: 600 }}>{opp.threshold}°F</div>
          </div>
        )}
        {opp.ensemble_prob != null && (
          <div>
            <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase' }}>Ensemble</div>
            <div>{(opp.ensemble_prob * 100).toFixed(0)}%</div>
          </div>
        )}
        {opp.nws_prob != null && (
          <div>
            <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase' }}>NWS</div>
            <div>{(opp.nws_prob * 100).toFixed(0)}%</div>
          </div>
        )}
        {opp.clim_prob != null && (
          <div>
            <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase' }}>Climatology</div>
            <div>{(opp.clim_prob * 100).toFixed(0)}%</div>
          </div>
        )}
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase' }}>Method</div>
          <div>{opp.blend_method || opp.method || '—'}</div>
        </div>
      </div>
      {opp.model_disagreement_flag && (
        <div style={{ marginTop: 8, color: 'var(--color-yellow)', fontSize: 11 }}>
          ⚠ Model disagreement: NWS vs ensemble gap = {opp.model_disagreement_f}°F — reduced confidence
        </div>
      )}
    </td>
  </tr>
)}
```

- [ ] **Step 3: Rebuild and verify**

```
cd "weather app site V_3 (3)"
npm run build
```

Click a signal row. The drill-down panel should expand showing forecast temp, model prob breakdown, and disagreement flag.

- [ ] **Step 4: Commit**

```
git add "weather app site V_3 (3)/src/tabs/SignalsTab.jsx" static/dist/
git commit -m "feat(dashboard): signal drill-down panel (expand row to see model inputs and source breakdown)"
```

---

## H8: Model Disagreement Indicator in Positions Tab

*(Covered in D2 plan — plan D2 adds the backend field. This step adds it to Positions tab.)*

After D2 is complete and `model_disagreement_flag` / `model_disagreement_f` are in the trade record:

- [ ] **Step 1: Add disagreement indicator to `PositionsTab.jsx` row**

```jsx
{trade.model_disagreement_flag && (
  <span
    title={`NWS and ensemble disagreed by ${trade.model_disagreement_f}°F at entry`}
    style={{ color: 'var(--color-yellow)', fontSize: 10, marginLeft: 4 }}
  >
    ⚠ {trade.model_disagreement_f}°F
  </span>
)}
```

- [ ] **Step 2: Rebuild and commit**

```
cd "weather app site V_3 (3)"
npm run build
```

```
git add "weather app site V_3 (3)/src/tabs/PositionsTab.jsx" static/dist/
git commit -m "feat(dashboard): show model disagreement indicator on open positions"
```

---

## H11: Weather Alert Display

**Problem:** NWS issues Excessive Heat Warnings, Freeze Warnings, and Winter Storm Watches that are directly relevant to open positions. The dashboard doesn't show these.

**Files:**
- Modify: `web_app.py` — add `/api/weather-alerts` endpoint that fetches from NWS alerts API
- Modify: `weather app site V_3 (3)/src/tabs/PositionsTab.jsx` — show alert banner when relevant cities have active alerts

- [ ] **Step 1: Add `/api/weather-alerts` to `web_app.py`**

```python
@_app.route("/api/weather-alerts")
@_require_auth
def api_weather_alerts():
    """Fetch NWS active weather alerts for cities with open positions.

    Calls the free NWS Alerts API (no key required).
    Returns list of {event, headline, city, severity, expires} for active alerts.
    """
    import requests
    from paper import load_paper_trades

    open_trades = [t for t in load_paper_trades() if not t.get("settled") and t.get("won") is None]
    cities = list({t.get("city", "") for t in open_trades if t.get("city")})
    if not cities:
        return {"alerts": []}

    from weather_markets import _CITY_COORDS  # or wherever city→lat/lon map lives
    alerts = []
    for city in cities[:8]:  # limit to 8 cities to avoid too many API calls
        city_info = _CITY_COORDS.get(city.upper())
        if not city_info:
            continue
        try:
            resp = requests.get(
                "https://api.weather.gov/alerts/active",
                params={"point": f"{city_info['lat']},{city_info['lon']}"},
                headers={"User-Agent": "KalshiWeatherBot/1.0 (thesadcup@gmail.com)"},
                timeout=5,
            )
            resp.raise_for_status()
            features = resp.json().get("features", [])
            for f in features[:2]:  # max 2 alerts per city
                props = f.get("properties", {})
                severity = props.get("severity", "Unknown")
                if severity in ("Minor", "Unknown"):
                    continue  # only surface Moderate, Severe, Extreme
                alerts.append({
                    "city": city,
                    "event": props.get("event", ""),
                    "headline": props.get("headline", ""),
                    "severity": severity,
                    "expires": props.get("expires", ""),
                })
        except Exception:
            continue

    return {"alerts": alerts}
```

- [ ] **Step 2: Add alert banner to `PositionsTab.jsx`**

```jsx
function WeatherAlertBanner({ alerts }) {
  if (!alerts || alerts.length === 0) return null;
  return (
    <div style={{
      background: 'rgba(239,68,68,0.10)',
      border: '1px solid var(--color-red)',
      borderRadius: 6, padding: '8px 14px',
      marginBottom: 12, fontSize: 12,
    }}>
      <strong style={{ color: 'var(--color-red)' }}>⚠ Active Weather Alerts</strong>
      {alerts.map((a, i) => (
        <div key={i} style={{ marginTop: 4, color: 'var(--text)' }}>
          <strong>{a.city}</strong> — {a.event}
          {a.headline && <span style={{ color: 'var(--text-dim)' }}> — {a.headline}</span>}
        </div>
      ))}
    </div>
  );
}
```

Add `WeatherAlertBanner` fetch to `useData.js` (polling every 15 minutes) and render above the positions table:

```jsx
<WeatherAlertBanner alerts={weatherAlerts} />
```

- [ ] **Step 3: Rebuild and commit**

```
cd "weather app site V_3 (3)"
npm run build
```

```
git add web_app.py "weather app site V_3 (3)/src/tabs/PositionsTab.jsx" "weather app site V_3 (3)/src/useData.js" static/dist/
git commit -m "feat(dashboard): NWS weather alert banner for cities with open positions"
```

---

## H9: Reliability Diagram Chart

*Covered by plan D4 (Per-City Reliability Diagram). Implement D4 first — the chart component `ReliabilityDiagramChart` defined there can be reused in the Analytics tab without duplication.*

---

## H4: EMOS Status in Header (Quick-Glance)

After H3 (EMOS card in Analytics) is done, add a small EMOS indicator to the global header for quick visibility:

```jsx
{emosStatus && !emosStatus.trained && (
  <span style={{
    marginLeft: 8, fontSize: 10, padding: '1px 5px',
    background: 'rgba(107,114,128,0.2)', color: 'var(--text-dim)',
    borderRadius: 3, fontWeight: 500,
  }} title="EMOS not trained — run py main.py emos-train">
    EMOS ✗
  </span>
)}
```

*No separate commit — add to the same commit as H3.*

---

## H5: Position Building Indicator (Post-Graduation)

When position building (C4) is implemented, add a "▲ Building" badge to positions where the bot has added to a position since initial entry. This is a single CSS badge on the position row — no backend change needed if the trade record includes a `builds` count field.
