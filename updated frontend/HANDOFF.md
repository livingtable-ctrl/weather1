# Kalshi Weather Bot — Frontend Handoff

This package is a complete UI prototype for the Kalshi weather trading bot dashboard. It is designed to **replace the existing Flask templates** in the original `weather1` repo while keeping the Python backend, model code, and API contracts intact.

---

## TL;DR for Claude Code

1. The new UI is a **single React app** loaded via Babel in the browser. No build step is strictly required, but you may want to migrate to Vite + a real bundle for production.
2. The new dashboard expects **the same `/api/*` endpoints** the Flask app already exposes. Don't rebuild the backend — wire the frontend to it.
3. Replace `templates/dashboard.html` (and friends) with `full-prototype.html`. Move `full-prototype-v2.jsx` and `mock-data.js` into `static/`.
4. Swap `window.MOCK` (in `mock-data.js`) for live data fetched from the existing endpoints + SSE stream.

---

## File map

| File | Purpose | Action |
|---|---|---|
| `full-prototype.html` | App shell — loads React, Babel, mock-data, and the JSX bundle | Move to `templates/index.html`, serve from Flask |
| `full-prototype-v2.jsx` | The full app (all 7 tabs, theme, routing) | Move to `static/app.jsx`. Replace `window.MOCK` reads with API calls. |
| `mock-data.js` | **Spec for the data shape the UI expects** | Delete after wiring; use as the contract document |
| `reference/` | Original Flask templates and JS — for diffing what changed | Keep for reference; don't ship |
| `Kalshi Bot Dashboard.html` | Design canvas with 4 visual variations side-by-side | Design artifact only — not for production |

---

## Data contracts

The UI reads from a single `window.MOCK` object today. Each top-level key maps to an existing or to-be-built API endpoint.

| `window.MOCK.*` key | Source endpoint (existing in `web_app.py`) | Notes |
|---|---|---|
| `stats` | SSE stream `/stream` (current) | balance, win_rate, brier, open_count, settled_count, graduation gates |
| `stats.graduation` | `/api/graduation` | trades_done / pnl / brier vs gates |
| `positions` | `/api/positions` (or extend `/stream`) | array of open contracts with city/ticker/side/cost/qty/mark/fcst/edge/age_h |
| `closedTrades` | `/api/trades` | settled trade history with realized P&L |
| `opportunities` | `/api/opportunities` (new — derive from forecast vs market) | top scanner picks; UI expects `stars`, `kelly_dollars`, `near_threshold`, `is_hedge` flags |
| `circuitBreakers` | `/api/circuit-status` | array of {name, status, threshold, current_value} |
| `cityBrier` | `/api/calibration` | per-city Brier scores for the heatmap |
| `modelAccuracy` | `/api/model-accuracy` (new — aggregate) | per-source (NBM/GFS/HRRR/ICON/ENSEMBLE) Brier + edge_realized |
| `balanceHistory` | `/api/balance-history` | daily equity walk for the hero chart |
| `alerts` | `/api/alerts` (new) | recent system events (orders filled, breakers tripped, model drift) |
| `forecastToday`, `forecastTomorrow` | `/api/forecast?day=0\|1` | per-city ensemble forecast + spread + market price |
| `agedPositions`, `correlatedEvents` | derived client-side from `positions` | risk warnings — could move server-side |
| `priceImprovement` | `/api/execution-quality` (new) | avg_improvement_cents, positive_pct |
| `auc` | `/api/calibration` (extend) | overall ROC AUC |

**Endpoints already in `web_app.py`** (preserve as-is): `/stream`, `/api/graduation`, `/api/circuit-status`, `/api/balance-history`, `/api/positions`, `/api/trades`, `/api/calibration`.

**New endpoints needed**: `/api/opportunities`, `/api/model-accuracy`, `/api/alerts`, `/api/forecast`, `/api/execution-quality`.

---

## Wiring strategy

Recommended order:

1. **Render with mock data first.** Confirm the new HTML/JSX serves from Flask correctly. (~30 min)
2. **Replace `stats` and `balanceHistory`** with the existing SSE stream. This gets the Overview tab live. (~1 hr)
3. **Wire `positions` and `closedTrades`** from existing endpoints. Positions tab and Trades tab go live. (~1 hr)
4. **Wire `circuitBreakers`, `graduation`, `cityBrier`** from existing endpoints. Risk and Calibration tabs go live. (~1 hr)
5. **Build the new endpoints** (`/api/opportunities`, `/api/model-accuracy`, `/api/forecast`, `/api/alerts`, `/api/execution-quality`). Most are aggregations of data already in `kalshi_paper.db` or computed in `forecast.py` — should be straightforward. (~3-4 hrs)
6. **Replace `window.MOCK` with a state hook** that fetches all endpoints on mount and subscribes to SSE for live updates.

```js
// Suggested replacement for `const M = window.MOCK;`
const [data, setData] = useState(null);
useEffect(() => {
  Promise.all([
    fetch('/api/positions').then(r => r.json()),
    fetch('/api/trades').then(r => r.json()),
    // ...etc
  ]).then(([positions, trades, /* ... */]) => {
    setData({ positions, closedTrades: trades, /* ... */ });
  });
  const sse = new EventSource('/stream');
  sse.onmessage = (e) => {
    const update = JSON.parse(e.data);
    setData(d => ({ ...d, stats: { ...d.stats, ...update } }));
  };
  return () => sse.close();
}, []);
if (!data) return <LoadingSkeleton />;
const M = data; // rest of component code unchanged
```

---

## Backend modules added since this prototype was designed

The Python backend has grown significantly. The prototype data shapes still align, but these new systems should be surfaced in the dashboard:

| Module | What it does | Suggested UI placement |
|---|---|---|
| `ab_test.py` | A/B experiment framework (run `python main.py ab-summary`) | New section in **Analytics** tab — show active experiments, lift, p-value |
| `notify.py` | Discord/email/desktop/Pushover/ntfy notifications | New **Notifications** subsection in settings + recent-sends log |
| `main.py override` (set/clear/status, TTL minutes) | Temporary pause separate from kill switch | Sibling button next to **Kill switch** with countdown + reason |
| `settlement_monitor.py` | Settlement lag signal detection | New **Lag** card in Risk tab |
| `alerts.py` (anomaly + black swan auto-halt) | Auto-halt triggers on anomalous market conditions | Banner above Overview when an auto-halt is active; show trigger reason |
| `cloud_backup.py` | OneDrive/Drive sync of `data/` after every cron | Footer indicator: "Last backup: 12 min ago ✓" |
| `execution_log.py` | Audit log of every order placed/filled/cancelled | New **Audit** tab or drawer accessible from any trade row |
| `feature_importance.py` | Per-source importance for current model | Add to Calibration / Analytics — small bar chart |
| `consistency.py` | Cross-market consistency checks | Risk tab — flag inconsistent prices across related markets |
| `forecast_cache.py` | Forecast caching layer | Settings: cache TTL + manual invalidate button |
| `kalshi_ws.py` | WebSocket order book (real-time mid prices) | Connection status indicator in nav (next to "● Live") |
| Multiple notification channels (`NOTIFY_CHANNELS=desktop,discord,pushover,ntfy,email`) | Per-channel toggles | Settings → Notifications, one row per channel |

### Settings page — now more important

The original handoff flagged a settings page as a known gap. Given the backend additions, this is now **the highest-priority new screen**. It should expose:

- Strategy mode (`kelly` / `fixed_pct` / `fixed_dollars`) + per-mode params
- All `MIN_EDGE`, `PAPER_MIN_EDGE`, `MAX_*` thresholds from `.env`
- Notification channels (toggle each)
- Kill switch + override pause (with TTL)
- Cloud backup path + status
- Drift/calibration thresholds

`config.py` and `.env.example` document the full surface — wire the UI to read/write these via a new `/api/config` GET/PATCH endpoint.

---

## Known gaps the design did NOT address

These need to be designed AFTER real data is wired, because mock data hides the real complexity:

1. **Empty states** — what does the dashboard look like for a brand-new bot with no settled trades yet?
2. **Loading skeletons** — instant mock data hides the real fetch delay.
3. **Error states** — Kalshi API down, weather feed stale, DB locked.
4. **Kill switch confirm flow** — the button currently does nothing. Needs a confirm dialog and a "killed" state.
5. **Settings page** — there's no UI to change Kelly fraction, edge threshold, position cap, or paper-vs-live mode.
6. **Trade approval flow** — if not fully autonomous, the Signals tab needs approve/reject actions.
7. **Mobile** — tables overflow badly. Operator dashboards are 90% desktop, but a phone-friendly Overview-only view would help.

Recommend tackling 4 and 5 before going live; 1-3 once you see what the real loading/error patterns look like.

---

## Architecture notes

- **No build system.** The app uses unpkg-pinned React 18.3.1 + Babel standalone, transpiled in-browser. Fine for prototyping; replace with Vite for production (faster cold start, better errors, code splitting).
- **Theme** is light/dark via CSS custom properties on `<html>`. Stored in `localStorage` as `kalshi-theme`.
- **State** is local to `<App>`. No Redux/Zustand needed — the data shape is flat and read-mostly.
- **Charts** are hand-rolled SVG (no Plotly). Smaller bundle, more visual control. Rebuild with Recharts/Visx if you need interactivity beyond hover.

---

## Questions for the user before starting

1. Will you migrate to a real build system (Vite/Next), or keep the Babel-in-browser approach?
2. Which of the "known gaps" above should be in scope for v1?
3. Is the bot fully autonomous, or do you want approve/reject buttons on Signals?
4. Live trading toggle — design the gate now, or assume paper-only for v1?
