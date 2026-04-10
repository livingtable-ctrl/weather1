# Dashboard Modernization Design
**Date**: 2026-04-10
**Status**: Approved

---

## Overview

Modernize the Kalshi trading bot dashboard from a single-file Flask app with inline HTML strings to a proper Flask app with Jinja2 templates and static assets. Add 5 new pages covering risk, trades, signals, forecast quality, and expanded analytics. Modernize the UI with a sidebar layout, dark/light theme toggle, and Plotly.js charts.

---

## Architecture

### File Structure

```
web_app.py                  ← routes only, no HTML strings
templates/
  base.html                 ← sidebar, nav, dark/light toggle, Plotly CDN
  dashboard.html
  analytics.html
  risk.html
  trades.html
  signals.html
  forecast.html
static/
  style.css                 ← CSS custom properties for dark/light themes
  dashboard.js
  analytics.js
  risk.js
  trades.js
  signals.js
  forecast.js
```

### Key Principles

- `base.html` defines the sidebar, top bar with theme toggle, and `{% block content %}` slot
- Each page template extends `base.html` and fills that slot
- `web_app.py` keeps all existing routes and API endpoints unchanged; adds 5 new page routes and 6 new API endpoints
- All existing API endpoints (`/api/stream`, `/api/analytics`, `/api/balance_history`, etc.) remain unchanged
- No Flask blueprints — single `web_app.py` is sufficient for a local dashboard

---

## UI Layout

### Sidebar

Fixed left sidebar, 220px wide. Collapses to 60px (icon-only) on screens below 768px; hamburger menu overlay on mobile.

```
┌─────────────────────────────────────────────┐
│ ☁ Kalshi Bot          [☀️/🌙]  [●LIVE]      │
├──────────┬──────────────────────────────────┤
│ 📊 Dashboard           │                    │
│ 📈 Analytics           │   page content     │
│ ⚠️  Risk               │                    │
│ 🏦 Trades              │                    │
│ 🔭 Signals             │                    │
│ 🌤️  Forecast            │                    │
│                        │                    │
│ ──────────────         │                    │
│ ⚙️  Settings (stub)     │                    │
└──────────┴──────────────────────────────────┘
```

Active nav item highlighted with accent color. Page title in top-left of content area. Live SSE dot + last-updated timestamp in top-right.

### Dark/Light Theme

CSS custom properties defined in `:root` (dark defaults) and overridden under `[data-theme="light"]`. Toggle button saves preference to `localStorage`. No JavaScript frameworks — one `style.css` file handles both themes.

```css
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #c9d1d9;
  --accent: #58a6ff;
  --pos: #3fb950;
  --neg: #f85149;
}
[data-theme="light"] {
  --bg: #ffffff;
  --surface: #f6f8fa;
  --border: #d0d7de;
  --text: #24292f;
  --accent: #0969da;
  --pos: #1a7f37;
  --neg: #cf222e;
}
```

### Charts

All charts use **Plotly.js** (loaded from CDN in `base.html`). Replaces Chart.js for all new charts. Existing balance history chart migrated to Plotly for consistency.

---

## Pages

### Dashboard (`/`)

Reorganized layout, same data as today plus additions:

- **Stat cards row**: Balance, Open Positions, Win Rate, Brier Score
- **Fear/Greed gauge**: 0–100 Plotly indicator, color-coded red→amber→green. Data from `fear_greed_index()`.
- **Graduation progress bar**: Two sub-bars — trades completed (N/30) and win rate (X%/55%). Turns green when both met. Data from `graduation_check()`.
- **Balance history chart**: Existing chart, migrated to Plotly, range selector preserved.
- **Live markets strip**: Existing SSE feed showing top 3 opportunities.

### Analytics (`/analytics`)

Full model health dashboard:

- **Calibration curve**: Plotly scatter — predicted probability buckets (x) vs actual outcome rate (y), with diagonal reference line (perfect calibration). Data from `get_market_calibration()`.
- **Brier score over time**: Plotly line chart, weekly resolution, last 12 weeks. Data from new `get_brier_over_time(weeks=12)` tracker function.
- **ROC curve**: Plotly line with AUC labeled in legend. Data from existing `get_roc_auc()`.
- **P&L attribution**: Plotly horizontal bar charts — one per grouping: by city, by condition type, by dominant forecast source. Data from `get_component_attribution()` and existing attribution functions.
- **Existing analytics content** kept and reformatted into the new layout: confusion matrix (from `get_confusion_matrix()`), edge decay curve (from `get_edge_decay_curve()`), calibration by city table (from `get_calibration_by_city()`), Brier by days-out bar chart (from `get_brier_by_days_out()`), seasonal calibration table.

### Risk (`/risk`)

Portfolio exposure at a glance:

- **Exposure by city**: Plotly bar chart, sorted descending by dollar exposure. Data from `get_city_date_exposure()` aggregated by city.
- **Directional bias**: Plotly donut — YES $ vs NO $ open exposure. Data from `get_directional_exposure()`.
- **Expiry clustering**: Plotly bar — open positions grouped by expiry date. Shows concentration risk. Data from `get_expiry_date_clustering()`.
- **Risk cards**: Oldest position age, total exposure vs limit, correlated event count. Data from `get_total_exposure()`, `check_aged_positions()`, `check_correlated_event_exposure()`.

### Trades (`/trades`)

Operational trading view:

- **Open positions table**: Ticker, city, condition, entry price, current implied prob (from last SSE snapshot), MTM P&L, days until expiry, edge at entry. Sortable by P&L and expiry.
- **Slippage & fees card**: Cumulative entry vs mid-price improvement/slippage. Data from `get_price_improvement_stats()`.
- **Closed trade history table**: Moved from existing `/history` page. Filterable by city, condition type, date range. 25 per page, paginated.

### Signals (`/signals`)

Scan history and alert log:

- **Cron log table**: Last 200 entries from `data/cron.log` (JSONL). Columns: timestamp, ticker, city, signal type, net edge, outcome (if settled). Filterable by signal type and city.
- **Alert feed**: Last 50 system alerts — circuit breaker trips, backup failures, loss streak pauses, large loss events. Source: `data/cron.log` entries where `signal` is `"ALERT"` or `level` is `"WARNING"`/`"ERROR"`. If no such field exists in cron.log, filter for entries where `net_edge` is absent (non-opportunity log lines). No new log file required.

### Forecast (`/forecast`)

Model inputs and data quality:

- **City heat map**: Plotly heatmap — cities (rows) × condition types (columns), colored by current edge. Green = positive edge, red = negative. Data from `get_calibration_by_city()`.
- **Ensemble agreement**: Plotly bar — per-city ensemble std dev. Short bars = models agree (high confidence). Data from tracker ensemble stats.
- **Source reliability scorecard**: Table — NWS / ensemble / climatology success rate per city over last 7 days. Data from `get_calibration_by_city()` filtered by `analyzed_at` date.

---

## New API Endpoints

| Endpoint | Method | Returns | Data Source |
|----------|--------|---------|-------------|
| `/api/brier_history` | GET | `[{week, brier}]` last 12 weeks | New `tracker.get_brier_over_time(weeks=12)` |
| `/api/risk` | GET | Exposure, directional bias, expiry clustering | `paper.get_city_date_exposure()`, `get_directional_exposure()`, `get_expiry_date_clustering()` |
| `/api/trades` | GET | Open + closed trades with MTM | `paper.get_open_trades()`, `paper.get_trade_history()` |
| `/api/signals` | GET | Last 200 cron.log entries | Read `data/cron.log` JSONL, last 200 lines |
| `/api/forecast_quality` | GET | Heat map data + source reliability | `tracker.get_calibration_by_city()`, `get_ensemble_member_accuracy()` |
| `/api/graduation` | GET | `{trades_done, win_rate, ready}` | `paper.graduation_check()` |

### New Tracker Function

`get_brier_over_time(weeks: int = 12) -> list[dict]`

Groups settled predictions by ISO week number, computes mean Brier score per week. Returns `[{"week": "2025-W40", "brier": 0.21}, ...]` sorted ascending.

---

## Testing

- **Existing tests**: All 280 passing tests remain green. No changes to `paper.py`, `tracker.py`, or `weather_markets.py` logic.
- **New route smoke tests** (6): Each page route (`/`, `/analytics`, `/risk`, `/trades`, `/signals`, `/forecast`) returns HTTP 200 with correct page title in HTML.
- **New API endpoint tests** (6): Each `/api/*` endpoint returns HTTP 200 with correct JSON shape, mocking underlying data functions.
- **Total new tests**: ~12, added to `tests/test_web_app.py`.
- **No frontend JS tests**: JS files are thin Plotly/fetch wrappers; browser testing not warranted for a local dashboard.

---

## Out of Scope

- Real-time trade execution UI
- User authentication
- Multi-user support
- WebSocket (SSE already in place for real-time)
- Persistent alert storage (alert feed reads from log file only)
- Settings page implementation (stub nav item only)
