# Dashboard Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modernize the Kalshi dashboard from inline-HTML Flask to Jinja2 templates + static assets, with a sidebar layout, dark/light theme toggle, and 4 new pages (Risk, Trades, Signals, Forecast).

**Architecture:** All page routes become thin `render_template()` calls; data loading moves to existing and new `/api/*` endpoints; JavaScript files (one per page) use Plotly.js to render charts by fetching those endpoints. CSS custom properties handle dark/light theming without a JS framework.

**Tech Stack:** Flask, Jinja2, Plotly.js (CDN at `https://cdn.plot.ly/plotly-2.32.0.min.js`), vanilla JS, SQLite (via tracker.py), no new Python dependencies.

---

## File Map

**New files:**
- `static/style.css` — CSS custom properties for dark/light themes, sidebar layout, stat cards, tables
- `static/dashboard.js` — SSE stat cards, fear/greed gauge, graduation bars, Plotly balance chart
- `static/analytics.js` — calibration curve, Brier history, ROC, P&L attribution, city cal table
- `static/risk.js` — city exposure bar, directional donut, expiry clustering bar
- `static/trades.js` — open positions table, closed trade history (paginated, filterable)
- `static/signals.js` — cron log table (filterable), alert feed
- `static/forecast.js` — city heat map, source reliability scorecard, ensemble std dev bar
- `templates/base.html` — sidebar nav, top bar, theme toggle, Plotly CDN, `{% block content %}`
- `templates/dashboard.html` — stat cards, fear/greed gauge, graduation bars, balance chart, markets strip
- `templates/analytics.html` — Brier history, calibration curve, ROC, attribution, city cal table
- `templates/risk.html` — risk stat cards, city exposure bar, directional donut, expiry chart
- `templates/trades.html` — open positions table, closed trade history with filters + pagination
- `templates/signals.html` — alert feed, cron log table with filters
- `templates/forecast.html` — city heat map, source reliability table, ensemble std dev bar

**Modified files:**
- `web_app.py` — add `render_template` import; thin-ify `/` and `/analytics` routes; add `/risk`, `/trades`, `/signals`, `/forecast` page routes; add `/api/graduation`, `/api/brier_history`, `/api/risk`, `/api/trades`, `/api/signals`, `/api/forecast_quality` endpoints
- `tracker.py` — add `get_brier_over_time(weeks: int = 12) -> list[dict]`
- `tests/test_web_app.py` — add 12 new tests (6 route smoke + 6 API shape)
- `tests/test_tracker.py` — add 1 test for `get_brier_over_time`

**Key facts about the existing codebase:**
- `web_app.py` uses `render_template_string` with inline HTML today. Flask auto-discovers `templates/` and `static/` in the same directory as `web_app.py` (the project root), so no `template_folder` argument needed.
- `paper.fear_greed_index()` returns `(score: int, label: str)` — it's in `paper.py`, not `tracker.py`.
- `paper.graduation_check()` returns `{"settled": N, "win_rate": X, "total_pnl": Y, "roi": Z}` or `None`.
- `paper.get_city_date_exposure(city, target_date_str)` takes per-city parameters — the `/api/risk` endpoint aggregates from `get_open_trades()` directly.
- No `get_trade_history()` exists — use `get_all_trades()` filtered by `t.get("settled")`.
- The DARK_STYLE, VIEWPORT, and NAV constants in `web_app.py` must be kept — `/analyze` and `/history` routes still use them.

---

### Task 1: static/style.css

**Files:**
- Create: `static/style.css`

- [ ] **Step 1: Create static/style.css**

```css
/* static/style.css */
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #c9d1d9;
  --text-muted: #8b949e;
  --accent: #58a6ff;
  --pos: #3fb950;
  --neg: #f85149;
  --warn: #e3b341;
  --sidebar-w: 220px;
}
[data-theme="light"] {
  --bg: #ffffff;
  --surface: #f6f8fa;
  --border: #d0d7de;
  --text: #24292f;
  --text-muted: #57606a;
  --accent: #0969da;
  --pos: #1a7f37;
  --neg: #cf222e;
  --warn: #9a6700;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
body {
  display: flex;
  background: var(--bg);
  color: var(--text);
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 14px;
}

/* Sidebar */
.sidebar {
  width: var(--sidebar-w);
  min-height: 100vh;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  position: fixed;
  top: 0; left: 0; bottom: 0;
  z-index: 100;
}
.sidebar-logo {
  padding: 18px 16px 14px;
  font-size: 1.1em;
  font-weight: bold;
  color: var(--accent);
  border-bottom: 1px solid var(--border);
}
.sidebar-nav { flex: 1; padding: 12px 0; }
.sidebar-nav a {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 18px;
  color: var(--text-muted);
  text-decoration: none;
  font-size: 0.9em;
  transition: background 0.15s, color 0.15s;
}
.sidebar-nav a:hover, .sidebar-nav a.active {
  background: rgba(88,166,255,0.1);
  color: var(--accent);
}
.sidebar-footer {
  padding: 14px 18px;
  border-top: 1px solid var(--border);
  font-size: 0.82em;
  color: var(--text-muted);
}

/* Main content */
.main {
  margin-left: var(--sidebar-w);
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 24px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  position: sticky;
  top: 0;
  z-index: 50;
}
.topbar-title { font-size: 1.15em; font-weight: bold; color: var(--text); }
.topbar-right { display: flex; align-items: center; gap: 14px; }
.live-indicator { display: flex; align-items: center; gap: 6px; font-size: 0.82em; color: var(--text-muted); }
.live-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--pos);
  animation: blink 1.5s infinite;
}
.live-dot.stale { background: var(--warn); }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }

#theme-toggle {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-muted);
  border-radius: 6px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 0.82em;
}

.content { padding: 24px; flex: 1; }

/* Stat cards */
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 14px;
  margin-bottom: 24px;
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
}
.stat-label { color: var(--text-muted); font-size: 0.78em; text-transform: uppercase; letter-spacing: 0.05em; }
.stat-value { font-size: 1.6em; font-weight: bold; margin-top: 6px; }

/* Tables */
table { width: 100%; border-collapse: collapse; margin-bottom: 24px; font-size: 0.88em; }
th { background: var(--surface); color: var(--text-muted); padding: 8px 12px; text-align: left; border-bottom: 2px solid var(--border); }
td { padding: 7px 12px; border-bottom: 1px solid var(--border); }
tr:hover { background: var(--surface); }

/* Chart containers */
.chart-wrap { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 20px; }

/* Progress bars */
.progress-wrap { margin-bottom: 10px; }
.progress-label { display: flex; justify-content: space-between; font-size: 0.82em; color: var(--text-muted); margin-bottom: 4px; }
.progress-bar-bg { background: var(--border); border-radius: 4px; height: 10px; }
.progress-bar-fill { height: 10px; border-radius: 4px; background: var(--accent); transition: width 0.4s; }
.progress-bar-fill.complete { background: var(--pos); }

/* Badges */
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }
.badge-green { background: #1a3a1f; color: var(--pos); }
.badge-red { background: #3a1a1a; color: var(--neg); }

/* Utility */
.pos { color: var(--pos); }
.neg { color: var(--neg); }
.neu { color: var(--text-muted); }
.section { margin-bottom: 28px; }
h2 { font-size: 1.05em; color: var(--text-muted); margin-bottom: 14px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* Pagination */
.pagination { display: flex; gap: 8px; margin-top: 12px; }
.pagination button { background: var(--surface); border: 1px solid var(--border); color: var(--text); border-radius: 4px; padding: 4px 10px; cursor: pointer; font-size: 0.82em; }
.pagination button.active { background: var(--accent); color: #fff; border-color: var(--accent); }

/* Mobile */
@media (max-width: 768px) {
  .sidebar { transform: translateX(-100%); }
  .sidebar.open { transform: translateX(0); }
  .main { margin-left: 0; }
  .content { padding: 16px; }
  .stats { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 480px) {
  .stats { grid-template-columns: 1fr; }
  table { display: block; overflow-x: auto; }
}
```

- [ ] **Step 2: Verify the file exists**

```bash
ls static/style.css
```

Expected: file listed, no error.

- [ ] **Step 3: Commit**

```bash
git add static/style.css
git commit -m "feat: add CSS custom properties for dark/light theme (dashboard modernization)"
```

---

### Task 2: templates/base.html

**Files:**
- Create: `templates/base.html`

- [ ] **Step 1: Create templates/base.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}Kalshi Bot{% endblock %} — Kalshi Bot</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
  <script src="https://cdn.plot.ly/plotly-2.32.0.min.js" charset="utf-8"></script>
  <script>
    // Apply saved theme before paint to avoid flash
    (function () {
      var t = localStorage.getItem('theme');
      if (t) document.documentElement.setAttribute('data-theme', t);
    })();
  </script>
</head>
<body>
  <aside class="sidebar" id="sidebar">
    <div class="sidebar-logo">&#9729; Kalshi Bot</div>
    <nav class="sidebar-nav">
      <a href="/">&#128202; Dashboard</a>
      <a href="/analytics">&#128200; Analytics</a>
      <a href="/risk">&#9888;&#65039; Risk</a>
      <a href="/trades">&#127974; Trades</a>
      <a href="/signals">&#128301; Signals</a>
      <a href="/forecast">&#127780;&#65039; Forecast</a>
    </nav>
    <div class="sidebar-footer">
      <a href="/analyze">&#9881;&#65039; Analyze (live)</a>
    </div>
  </aside>

  <div class="main">
    <header class="topbar">
      <span class="topbar-title" id="topbar-title">{% block page_title %}{% endblock %}</span>
      <div class="topbar-right">
        <div class="live-indicator">
          <span class="live-dot" id="global-live-dot"></span>
          <span id="global-live-ts">—</span>
        </div>
        <button id="theme-toggle" onclick="toggleTheme()">&#9680; Theme</button>
      </div>
    </header>

    <div class="content">
      {% block content %}{% endblock %}
    </div>
  </div>

  <script>
    // Mark active nav link by matching pathname
    (function () {
      var path = window.location.pathname;
      document.querySelectorAll('.sidebar-nav a').forEach(function (a) {
        if (a.pathname === path) a.classList.add('active');
      });
    })();

    // Theme toggle — no page reload, instant via data-theme attribute
    function toggleTheme() {
      var cur = document.documentElement.getAttribute('data-theme');
      var next = cur === 'light' ? null : 'light';
      if (next) {
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('theme', next);
      } else {
        document.documentElement.removeAttribute('data-theme');
        localStorage.removeItem('theme');
      }
    }

    // Mobile: clicking the page title toggles the sidebar
    document.getElementById('topbar-title').style.cursor = 'pointer';
    document.getElementById('topbar-title').addEventListener('click', function () {
      document.getElementById('sidebar').classList.toggle('open');
    });
  </script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 2: Verify templates directory**

```bash
ls templates/base.html
```

Expected: file listed.

- [ ] **Step 3: Commit**

```bash
git add templates/base.html
git commit -m "feat: add base.html with sidebar, dark/light toggle, Plotly CDN"
```

---

### Task 3: Refactor web_app.py + dashboard.html + dashboard.js

**Files:**
- Modify: `web_app.py` (add `render_template` import; replace `/` route body)
- Create: `templates/dashboard.html`
- Create: `static/dashboard.js`
- Modify: `tests/test_web_app.py` (add smoke test)

The `/` route currently builds a large HTML string inline. This task replaces that with `render_template('dashboard.html')`. All data loading moves to JS, which calls `/api/stream` (SSE, existing) and `/api/graduation` (new, Task 6) and `/api/balance_history` (existing).

- [ ] **Step 1: Write the failing smoke test**

Add to `tests/test_web_app.py`:

```python
def test_dashboard_route_returns_200_with_title(client):
    """Dashboard page returns 200 and contains 'Dashboard'."""
    r = client.get("/")
    assert r.status_code == 200
    assert b"Dashboard" in r.data
```

- [ ] **Step 2: Run test to confirm it currently passes (existing inline HTML)**

```bash
pytest tests/test_web_app.py::test_dashboard_route_returns_200_with_title -v
```

Note: it will PASS with the existing inline HTML. After step 4 it must still PASS via the template.

- [ ] **Step 3: Add `render_template` to the Flask import block inside `_build_app`**

Find this block in `web_app.py`:

```python
    try:
        from flask import (
            Flask,
            Response,
            jsonify,
            render_template_string,
            stream_with_context,
        )
    except ImportError:
        return None
```

Replace with:

```python
    try:
        from flask import (
            Flask,
            Response,
            jsonify,
            render_template,
            render_template_string,
            stream_with_context,
        )
    except ImportError:
        return None
```

- [ ] **Step 4: Replace the entire `index()` function body with a thin render_template call**

Find the `@app.route("/")` decorated function (it starts with `def index():` and contains hundreds of lines building an `html = f"""..."""` string). Replace the entire function (from `@app.route("/")` through the final `return render_template_string(html)`) with:

```python
    @app.route("/")
    def index():
        return render_template("dashboard.html")
```

Do NOT remove the `DARK_STYLE`, `VIEWPORT`, or `NAV` constants — they are still used by `/analyze` and `/history`.

- [ ] **Step 5: Create templates/dashboard.html**

```html
{% extends "base.html" %}

{% block title %}Dashboard{% endblock %}
{% block page_title %}Dashboard{% endblock %}

{% block content %}
<!-- Stat cards — populated by SSE (/api/stream) and /api/graduation -->
<div class="stats">
  <div class="stat-card">
    <div class="stat-label">Paper Balance</div>
    <div class="stat-value pos" id="stat-balance">—</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Open Positions</div>
    <div class="stat-value" id="stat-open">—</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Win Rate</div>
    <div class="stat-value" id="stat-winrate">—</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Brier Score</div>
    <div class="stat-value" id="stat-brier">—</div>
  </div>
</div>

<p class="live-indicator" style="margin-bottom:20px">
  <span class="live-dot" id="dash-dot"></span>
  <span id="dash-updated">Connecting…</span>
  <span id="dash-ts" style="margin-left:8px;font-size:0.82em;color:var(--text-muted)"></span>
</p>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:24px">
  <!-- Fear/Greed gauge -->
  <div class="chart-wrap">
    <h2>Fear / Greed Index</h2>
    <div id="fear-greed-chart" style="height:200px"></div>
  </div>
  <!-- Graduation progress -->
  <div class="chart-wrap">
    <h2>Graduation Progress</h2>
    <div class="progress-wrap">
      <div class="progress-label">
        <span>Trades completed</span>
        <span id="grad-trades-label">—/30</span>
      </div>
      <div class="progress-bar-bg">
        <div class="progress-bar-fill" id="grad-trades-bar" style="width:0%"></div>
      </div>
    </div>
    <div class="progress-wrap" style="margin-top:12px">
      <div class="progress-label">
        <span>Win rate</span>
        <span id="grad-wr-label">—/55%</span>
      </div>
      <div class="progress-bar-bg">
        <div class="progress-bar-fill" id="grad-wr-bar" style="width:0%"></div>
      </div>
    </div>
    <p id="grad-status" style="margin-top:14px;font-size:0.88em;color:var(--text-muted)"></p>
  </div>
</div>

<!-- Balance history chart -->
<div class="chart-wrap section">
  <h2>Balance History</h2>
  <div style="margin-bottom:10px">
    <button onclick="loadBalanceChart('')" data-range="" class="range-btn" style="background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:4px;padding:3px 10px;cursor:pointer;font-size:0.82em;margin-right:4px">Default</button>
    <button onclick="loadBalanceChart('1mo')" data-range="1mo" class="range-btn" style="background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:4px;padding:3px 10px;cursor:pointer;font-size:0.82em;margin-right:4px">1mo</button>
    <button onclick="loadBalanceChart('3mo')" data-range="3mo" class="range-btn" style="background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:4px;padding:3px 10px;cursor:pointer;font-size:0.82em;margin-right:4px">3mo</button>
    <button onclick="loadBalanceChart('1yr')" data-range="1yr" class="range-btn" style="background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:4px;padding:3px 10px;cursor:pointer;font-size:0.82em;margin-right:4px">1yr</button>
    <button onclick="loadBalanceChart('all')" data-range="all" class="range-btn" style="background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:4px;padding:3px 10px;cursor:pointer;font-size:0.82em">All</button>
  </div>
  <div id="balance-chart" style="height:220px"></div>
</div>

<!-- Live markets strip -->
<div class="section">
  <h2>Top Opportunities</h2>
  <div id="markets-strip">
    <p class="neu">Waiting for live data…</p>
  </div>
</div>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', filename='dashboard.js') }}"></script>
{% endblock %}
```

- [ ] **Step 6: Create static/dashboard.js**

```javascript
// static/dashboard.js
(function () {
  'use strict';

  // --- SSE: live data for stat cards and markets strip ---
  var _lastSseTs = null;
  var dashDot = document.getElementById('dash-dot');
  var dashUpdated = document.getElementById('dash-updated');
  var dashTs = document.getElementById('dash-ts');

  setInterval(function () {
    if (_lastSseTs === null) return;
    var secs = Math.round((Date.now() - _lastSseTs) / 1000);
    if (dashTs) dashTs.textContent = secs < 5 ? 'just now' : secs + 's ago';
    if (dashDot) dashDot.classList.toggle('stale', secs > 30);
  }, 1000);

  var es = new EventSource('/api/stream');
  es.onmessage = function (e) {
    try {
      _lastSseTs = Date.now();
      var d = JSON.parse(e.data);
      if (dashUpdated) dashUpdated.textContent = 'Live';
      var el;
      if (d.balance !== undefined) {
        el = document.getElementById('stat-balance');
        if (el) el.textContent = '$' + d.balance.toFixed(2);
      }
      if (d.open_count !== undefined) {
        el = document.getElementById('stat-open');
        if (el) el.textContent = d.open_count;
      }
      if (d.brier !== null && d.brier !== undefined) {
        el = document.getElementById('stat-brier');
        if (el) el.textContent = d.brier.toFixed(4);
      }
      if (d.markets) renderMarketsStrip(d.markets);
    } catch (err) {}
  };

  function renderMarketsStrip(markets) {
    var el = document.getElementById('markets-strip');
    if (!el) return;
    if (!markets.length) {
      el.innerHTML = '<p class="neu">No opportunities right now.</p>';
      return;
    }
    var html = '<table><tr><th>Ticker</th><th>Yes Ask</th><th>Edge</th></tr>';
    markets.forEach(function (m) {
      var edgeCls = m.edge >= 0 ? 'pos' : 'neg';
      var edgeStr = (m.edge >= 0 ? '+' : '') + (m.edge * 100).toFixed(1) + '%';
      html += '<tr><td>' + m.ticker + '</td><td>' + (m.yes_ask || '—') + '</td>'
        + '<td class="' + edgeCls + '">' + edgeStr + '</td></tr>';
    });
    html += '</table>';
    el.innerHTML = html;
  }

  // --- Graduation bars + Fear/Greed gauge ---
  function loadGraduation() {
    fetch('/api/graduation').then(function (r) { return r.json(); }).then(function (d) {
      // Win rate stat card
      var wr = document.getElementById('stat-winrate');
      if (wr) {
        wr.textContent = (d.win_rate !== null && d.win_rate !== undefined)
          ? (d.win_rate * 100).toFixed(1) + '%' : '—';
      }

      // Trades progress bar
      var done = d.trades_done || 0;
      var tradesLabel = document.getElementById('grad-trades-label');
      var tradesBar = document.getElementById('grad-trades-bar');
      if (tradesLabel) tradesLabel.textContent = done + '/30';
      if (tradesBar) {
        tradesBar.style.width = Math.min(100, (done / 30) * 100) + '%';
        tradesBar.classList.toggle('complete', done >= 30);
      }

      // Win rate progress bar
      var winRate = d.win_rate || 0;
      var wrLabel = document.getElementById('grad-wr-label');
      var wrBar = document.getElementById('grad-wr-bar');
      if (wrLabel) wrLabel.textContent = (winRate * 100).toFixed(1) + '%/55%';
      if (wrBar) {
        wrBar.style.width = Math.min(100, (winRate / 0.55) * 100) + '%';
        wrBar.classList.toggle('complete', winRate >= 0.55);
      }

      // Status message
      var gradStatus = document.getElementById('grad-status');
      if (gradStatus) {
        gradStatus.textContent = d.ready ? '✓ Ready to go live' : 'Keep building track record…';
        gradStatus.style.color = d.ready ? 'var(--pos)' : 'var(--text-muted)';
      }

      // Fear/Greed gauge
      renderFearGreed(d.fear_greed_score || 0, d.fear_greed_label || '');
    }).catch(function () {});
  }

  function renderFearGreed(score, label) {
    var el = document.getElementById('fear-greed-chart');
    if (!el || typeof Plotly === 'undefined') return;
    Plotly.newPlot(el, [{
      type: 'indicator',
      mode: 'gauge+number',
      value: score,
      title: { text: label, font: { color: 'var(--text-muted)', size: 13 } },
      gauge: {
        axis: { range: [0, 100], tickcolor: 'var(--text-muted)' },
        bar: { color: score < 40 ? '#f85149' : score < 65 ? '#e3b341' : '#3fb950' },
        bgcolor: 'var(--surface)',
        bordercolor: 'var(--border)',
        steps: [
          { range: [0, 40], color: '#3a1a1a' },
          { range: [40, 65], color: '#3a3a1a' },
          { range: [65, 100], color: '#1a3a1f' }
        ]
      }
    }], {
      paper_bgcolor: 'transparent',
      font: { color: 'var(--text)', family: 'Consolas' },
      margin: { t: 30, b: 10, l: 20, r: 20 }
    }, { responsive: true });
  }

  // --- Balance history chart (Plotly replaces Chart.js) ---
  function loadBalanceChart(range) {
    var url = '/api/balance_history' + (range ? '?range=' + range : '');
    fetch(url).then(function (r) { return r.json(); }).then(function (data) {
      var el = document.getElementById('balance-chart');
      if (!el || typeof Plotly === 'undefined') return;
      Plotly.newPlot(el, [{
        x: data.labels,
        y: data.values,
        type: 'scatter',
        mode: 'lines',
        line: { color: 'var(--accent)', width: 2 },
        fill: 'tozeroy',
        fillcolor: 'rgba(88,166,255,0.08)'
      }], {
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { color: 'var(--text)', family: 'Consolas' },
        xaxis: { showticklabels: false, showgrid: false, zeroline: false },
        yaxis: { tickprefix: '$', gridcolor: 'var(--border)', zeroline: false },
        margin: { t: 10, b: 20, l: 55, r: 10 },
        showlegend: false
      }, { responsive: true });

      document.querySelectorAll('.range-btn').forEach(function (b) {
        b.style.opacity = b.dataset.range === range ? '1' : '0.5';
      });
    }).catch(function () {});
  }

  // Init
  loadGraduation();
  loadBalanceChart('');
}());
```

- [ ] **Step 7: Run the smoke test**

```bash
pytest tests/test_web_app.py::test_dashboard_route_returns_200_with_title -v
```

Expected: PASS (Flask finds `templates/dashboard.html` which extends `base.html` containing "Dashboard").

- [ ] **Step 8: Commit**

```bash
git add web_app.py templates/dashboard.html static/dashboard.js tests/test_web_app.py
git commit -m "feat: convert dashboard route to Jinja2 template with Plotly balance chart"
```

---

### Task 4: analytics.html + analytics.js

**Files:**
- Modify: `web_app.py` (thin-ify `/analytics` route)
- Create: `templates/analytics.html`
- Create: `static/analytics.js`
- Modify: `tests/test_web_app.py` (add smoke test)

- [ ] **Step 1: Write the failing smoke test**

Add to `tests/test_web_app.py`:

```python
def test_analytics_route_returns_200_with_title(client):
    """Analytics page returns 200 and contains 'Analytics'."""
    r = client.get("/analytics")
    assert r.status_code == 200
    assert b"Analytics" in r.data
```

- [ ] **Step 2: Run test to confirm it passes before the refactor**

```bash
pytest tests/test_web_app.py::test_analytics_route_returns_200_with_title -v
```

- [ ] **Step 3: Replace the `analytics_page()` function body with a thin render_template call**

Find the `@app.route("/analytics")` decorated function (it starts `def analytics_page():` and loads `brier_score`, `get_brier_by_days_out`, etc. with lots of inline HTML). Replace the entire function with:

```python
    @app.route("/analytics")
    def analytics_page():
        return render_template("analytics.html")
```

- [ ] **Step 4: Create templates/analytics.html**

```html
{% extends "base.html" %}

{% block title %}Analytics{% endblock %}
{% block page_title %}Analytics{% endblock %}

{% block content %}
<div class="stats" style="margin-bottom:24px">
  <div class="stat-card">
    <div class="stat-label">Brier Score</div>
    <div class="stat-value" id="an-brier">—</div>
  </div>
</div>

<div class="chart-wrap section">
  <h2>Brier Score Over Time (last 12 weeks)</h2>
  <div id="brier-history-chart" style="height:200px"></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:24px">
  <div class="chart-wrap">
    <h2>Calibration Curve</h2>
    <div id="calibration-chart" style="height:220px"></div>
  </div>
  <div class="chart-wrap">
    <h2>ROC Curve</h2>
    <div id="roc-chart" style="height:220px"></div>
  </div>
</div>

<div class="chart-wrap section">
  <h2>P&amp;L Attribution by Source</h2>
  <div id="attribution-chart" style="height:220px"></div>
</div>

<div class="chart-wrap section">
  <h2>Brier Score by Days Out</h2>
  <div id="brier-days-chart" style="height:200px"></div>
</div>

<div class="section">
  <h2>Calibration by City</h2>
  <div id="city-cal-table"></div>
</div>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', filename='analytics.js') }}"></script>
{% endblock %}
```

- [ ] **Step 5: Create static/analytics.js**

```javascript
// static/analytics.js
(function () {
  'use strict';

  var LAYOUT_BASE = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: 'var(--text)', family: 'Consolas', size: 12 },
    margin: { t: 20, b: 40, l: 55, r: 20 }
  };

  function loadAnalytics() {
    fetch('/api/analytics').then(function (r) { return r.json(); }).then(function (d) {
      // Brier stat card
      var brierEl = document.getElementById('an-brier');
      if (brierEl && d.brier !== null && d.brier !== undefined) {
        brierEl.textContent = d.brier.toFixed(4);
      }

      // Calibration curve: predicted prob buckets vs actual outcome rate
      var calBuckets = d.model_calibration_buckets;
      if (calBuckets) {
        var xCal = calBuckets.map(function (b) { return b.predicted_prob; });
        var yCal = calBuckets.map(function (b) { return b.actual_rate; });
        var calEl = document.getElementById('calibration-chart');
        if (calEl && typeof Plotly !== 'undefined') {
          Plotly.newPlot(calEl, [
            { x: [0, 1], y: [0, 1], type: 'scatter', mode: 'lines', name: 'Perfect',
              line: { color: 'var(--text-muted)', dash: 'dash', width: 1 } },
            { x: xCal, y: yCal, type: 'scatter', mode: 'markers+lines', name: 'Model',
              marker: { color: 'var(--accent)', size: 7 }, line: { color: 'var(--accent)' } }
          ], Object.assign({}, LAYOUT_BASE, {
            xaxis: { title: 'Predicted Prob', gridcolor: 'var(--border)', zeroline: false, range: [0, 1] },
            yaxis: { title: 'Actual Rate', gridcolor: 'var(--border)', zeroline: false, range: [0, 1] }
          }), { responsive: true });
        }
      }

      // ROC curve with AUC in legend
      var roc = d.roc_auc;
      if (roc && roc.fpr && roc.tpr) {
        var rocEl = document.getElementById('roc-chart');
        if (rocEl && typeof Plotly !== 'undefined') {
          Plotly.newPlot(rocEl, [
            { x: [0, 1], y: [0, 1], type: 'scatter', mode: 'lines', name: 'Random',
              line: { color: 'var(--text-muted)', dash: 'dash', width: 1 } },
            { x: roc.fpr, y: roc.tpr, type: 'scatter', mode: 'lines',
              name: 'Model (AUC=' + (roc.auc || 0).toFixed(3) + ')',
              line: { color: 'var(--accent)', width: 2 } }
          ], Object.assign({}, LAYOUT_BASE, {
            xaxis: { title: 'FPR', gridcolor: 'var(--border)', zeroline: false, range: [0, 1] },
            yaxis: { title: 'TPR', gridcolor: 'var(--border)', zeroline: false, range: [0, 1] }
          }), { responsive: true });
        }
      }

      // P&L attribution: horizontal bar per source by Brier score
      var attr = d.component_attribution;
      if (attr) {
        var sources = Object.keys(attr);
        var brierVals = sources.map(function (s) { return (attr[s] || {}).brier_score || 0; });
        var attrEl = document.getElementById('attribution-chart');
        if (attrEl && typeof Plotly !== 'undefined') {
          Plotly.newPlot(attrEl, [{
            type: 'bar', orientation: 'h',
            x: brierVals, y: sources,
            marker: { color: 'var(--accent)' }
          }], Object.assign({}, LAYOUT_BASE, {
            xaxis: { title: 'Brier Score', gridcolor: 'var(--border)', zeroline: false },
            yaxis: { gridcolor: 'var(--border)' }
          }), { responsive: true });
        }
      }

      // Brier by days out: bar chart colored by quality
      var bd = d.brier_by_days;
      if (bd) {
        var dKeys = Object.keys(bd).sort(function (a, b) { return +a - +b; });
        var dVals = dKeys.map(function (k) { return bd[k]; });
        var bdEl = document.getElementById('brier-days-chart');
        if (bdEl && typeof Plotly !== 'undefined') {
          Plotly.newPlot(bdEl, [{
            type: 'bar',
            x: dKeys.map(function (k) { return k + ' days'; }),
            y: dVals,
            marker: { color: dVals.map(function (v) {
              return v < 0.25 ? 'var(--pos)' : v < 0.35 ? 'var(--warn)' : 'var(--neg)';
            })}
          }], Object.assign({}, LAYOUT_BASE, {
            xaxis: { gridcolor: 'var(--border)' },
            yaxis: { title: 'Brier', gridcolor: 'var(--border)', zeroline: false }
          }), { responsive: true });
        }
      }

      // City calibration table
      var cities = d.city_calibration;
      if (cities) {
        var html = '<table><tr><th>City</th><th>N</th><th>Brier</th><th>Bias</th></tr>';
        Object.keys(cities).sort().forEach(function (city) {
          var c = cities[city] || {};
          html += '<tr><td>' + city + '</td><td>' + (c.n || 0) + '</td>'
            + '<td>' + (c.brier !== undefined ? c.brier.toFixed(4) : '—') + '</td>'
            + '<td>' + (c.bias !== undefined ? c.bias.toFixed(4) : '—') + '</td></tr>';
        });
        html += '</table>';
        var tblEl = document.getElementById('city-cal-table');
        if (tblEl) tblEl.innerHTML = html;
      }
    }).catch(function () {});
  }

  function loadBrierHistory() {
    fetch('/api/brier_history').then(function (r) { return r.json(); }).then(function (data) {
      var el = document.getElementById('brier-history-chart');
      if (!el || typeof Plotly === 'undefined' || !data.length) return;
      Plotly.newPlot(el, [{
        x: data.map(function (d) { return d.week; }),
        y: data.map(function (d) { return d.brier; }),
        type: 'scatter', mode: 'lines+markers',
        line: { color: 'var(--accent)', width: 2 },
        marker: { color: 'var(--accent)', size: 6 }
      }], Object.assign({}, LAYOUT_BASE, {
        xaxis: { gridcolor: 'var(--border)', zeroline: false },
        yaxis: { title: 'Brier', gridcolor: 'var(--border)', zeroline: false }
      }), { responsive: true });
    }).catch(function () {});
  }

  loadAnalytics();
  loadBrierHistory();
}());
```

- [ ] **Step 6: Run the smoke test**

```bash
pytest tests/test_web_app.py::test_analytics_route_returns_200_with_title -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web_app.py templates/analytics.html static/analytics.js tests/test_web_app.py
git commit -m "feat: convert analytics route to Jinja2 template with Plotly charts"
```

---

### Task 5: tracker.get_brier_over_time()

**Files:**
- Modify: `tracker.py` (add function after `brier_score` around line 538)
- Modify: `tests/test_tracker.py` (add test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tracker.py`:

```python
def test_get_brier_over_time_returns_list():
    """get_brier_over_time returns a list of {week, brier} dicts or empty list."""
    from tracker import get_brier_over_time
    result = get_brier_over_time(weeks=12)
    assert isinstance(result, list)
    for item in result:
        assert "week" in item
        assert "brier" in item
        assert isinstance(item["brier"], float)
        assert 0.0 <= item["brier"] <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_tracker.py::test_get_brier_over_time_returns_list -v
```

Expected: FAIL with `ImportError` or `AttributeError`.

- [ ] **Step 3: Add get_brier_over_time to tracker.py**

Add this function after the `brier_score` function (around line 538):

```python
def get_brier_over_time(weeks: int = 12) -> list[dict]:
    """Return mean Brier score per ISO week for the last `weeks` weeks.

    Joins settled predictions with outcomes, groups by strftime('%Y-W%W', predicted_at),
    computes mean (our_prob - settled_yes)^2 per week.

    Returns [{"week": "2025-W40", "brier": 0.21}, ...] sorted ascending.
    Returns an empty list if no settled predictions exist in the window.
    """
    import datetime

    init_db()
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(weeks=weeks)
    ).isoformat()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT
                strftime('%Y-W%W', p.predicted_at) AS week,
                AVG(
                    (p.our_prob - o.settled_yes) * (p.our_prob - o.settled_yes)
                ) AS brier
            FROM predictions p
            JOIN outcomes o ON o.ticker = p.ticker
            WHERE p.predicted_at >= ?
              AND p.our_prob IS NOT NULL
            GROUP BY week
            ORDER BY week
            """,
            (cutoff,),
        ).fetchall()
    return [{"week": row["week"], "brier": round(row["brier"], 4)} for row in rows]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_tracker.py::test_get_brier_over_time_returns_list -v
```

Expected: PASS (empty list is valid when no data).

- [ ] **Step 5: Run full tracker tests to check for regressions**

```bash
pytest tests/test_tracker.py -v
```

Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add tracker.py tests/test_tracker.py
git commit -m "feat: add tracker.get_brier_over_time() for weekly Brier score history"
```

---

### Task 6: /api/graduation + /api/brier_history endpoints

**Files:**
- Modify: `web_app.py` (add two new API routes inside `_build_app`)
- Modify: `tests/test_web_app.py` (add two API shape tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_web_app.py`:

```python
def test_api_graduation_returns_correct_shape(client):
    """/api/graduation returns trades_done, win_rate, ready, fear_greed_score, fear_greed_label."""
    with (
        patch("paper.get_performance", return_value={"settled": 10, "win_rate": 0.5, "total_pnl": -20.0, "roi": -0.02}),
        patch("paper.graduation_check", return_value=None),
        patch("paper.fear_greed_index", return_value=(55, "Neutral")),
    ):
        r = client.get("/api/graduation")
        assert r.status_code == 200
        d = r.get_json()
        assert d["trades_done"] == 10
        assert d["win_rate"] == 0.5
        assert d["ready"] is False
        assert d["fear_greed_score"] == 55
        assert d["fear_greed_label"] == "Neutral"


def test_api_brier_history_returns_list(client):
    """/api/brier_history returns a JSON list of {week, brier} dicts."""
    with patch("tracker.get_brier_over_time", return_value=[{"week": "2025-W40", "brier": 0.21}]):
        r = client.get("/api/brier_history")
        assert r.status_code == 200
        d = r.get_json()
        assert isinstance(d, list)
        assert d[0]["week"] == "2025-W40"
        assert d[0]["brier"] == 0.21
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_web_app.py::test_api_graduation_returns_correct_shape tests/test_web_app.py::test_api_brier_history_returns_list -v
```

Expected: FAIL with 404.

- [ ] **Step 3: Add /api/graduation endpoint to web_app.py inside `_build_app`**

Add after the existing `/api/analytics` route:

```python
    @app.route("/api/graduation")
    def api_graduation():
        try:
            from paper import fear_greed_index, get_performance, graduation_check
        except ImportError as e:
            return jsonify({"error": str(e)}), 500
        perf = get_performance()
        gc = graduation_check()
        fg_score, fg_label = fear_greed_index()
        return jsonify({
            "trades_done": perf.get("settled", 0),
            "win_rate": perf.get("win_rate"),
            "ready": gc is not None,
            "fear_greed_score": fg_score,
            "fear_greed_label": fg_label,
        })
```

- [ ] **Step 4: Add /api/brier_history endpoint to web_app.py inside `_build_app`**

```python
    @app.route("/api/brier_history")
    def api_brier_history():
        try:
            from tracker import get_brier_over_time
            return jsonify(get_brier_over_time(weeks=12))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_web_app.py::test_api_graduation_returns_correct_shape tests/test_web_app.py::test_api_brier_history_returns_list -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web_app.py tests/test_web_app.py
git commit -m "feat: add /api/graduation and /api/brier_history endpoints"
```

---

### Task 7: Risk page — /api/risk + risk.html + risk.js

**Files:**
- Modify: `web_app.py` (add `/risk` route + `/api/risk` endpoint)
- Create: `templates/risk.html`
- Create: `static/risk.js`
- Modify: `tests/test_web_app.py` (add 2 tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_web_app.py`:

```python
def test_risk_route_returns_200_with_title(client):
    """Risk page returns 200 and contains 'Risk'."""
    r = client.get("/risk")
    assert r.status_code == 200
    assert b"Risk" in r.data


def test_api_risk_returns_correct_shape(client):
    """/api/risk returns city_exposure, directional, expiry_clustering, total_exposure."""
    with (
        patch("paper.get_open_trades", return_value=[
            {"city": "NYC", "side": "yes", "cost": 10.0, "target_date": "2025-12-01", "ticker": "X"},
        ]),
        patch("paper.get_total_exposure", return_value=0.1),
        patch("paper.check_aged_positions", return_value=[]),
        patch("paper.check_correlated_event_exposure", return_value=[]),
        patch("paper.get_expiry_date_clustering", return_value=[]),
    ):
        r = client.get("/api/risk")
        assert r.status_code == 200
        d = r.get_json()
        assert "city_exposure" in d
        assert "directional" in d
        assert "expiry_clustering" in d
        assert "total_exposure" in d
        assert d["directional"]["yes"] == 10.0
        assert d["directional"]["no"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_web_app.py::test_risk_route_returns_200_with_title tests/test_web_app.py::test_api_risk_returns_correct_shape -v
```

Expected: FAIL with 404.

- [ ] **Step 3: Add /risk route and /api/risk endpoint to web_app.py inside `_build_app`**

```python
    @app.route("/risk")
    def risk_page():
        return render_template("risk.html")

    @app.route("/api/risk")
    def api_risk():
        try:
            from paper import (
                check_aged_positions,
                check_correlated_event_exposure,
                get_expiry_date_clustering,
                get_open_trades,
                get_total_exposure,
            )
        except ImportError as e:
            return jsonify({"error": str(e)}), 500

        trades = get_open_trades()

        # Aggregate city exposure and directional bias from open trades
        city_exp: dict[str, float] = {}
        yes_exp = 0.0
        no_exp = 0.0
        for t in trades:
            city = t.get("city") or "Unknown"
            cost = float(t.get("cost") or 0.0)
            city_exp[city] = city_exp.get(city, 0.0) + cost
            if t.get("side") == "yes":
                yes_exp += cost
            else:
                no_exp += cost

        city_exposure = sorted(
            [{"city": c, "exposure": round(v, 4)} for c, v in city_exp.items()],
            key=lambda x: x["exposure"],
            reverse=True,
        )

        return jsonify({
            "city_exposure": city_exposure,
            "directional": {"yes": round(yes_exp, 4), "no": round(no_exp, 4)},
            "expiry_clustering": get_expiry_date_clustering(),
            "total_exposure": round(get_total_exposure(), 4),
            "aged_positions": check_aged_positions(),
            "correlated_events": check_correlated_event_exposure(),
        })
```

- [ ] **Step 4: Create templates/risk.html**

```html
{% extends "base.html" %}
{% block title %}Risk{% endblock %}
{% block page_title %}Risk{% endblock %}

{% block content %}
<div class="stats" style="margin-bottom:24px">
  <div class="stat-card">
    <div class="stat-label">Total Exposure</div>
    <div class="stat-value" id="risk-total-exp">—</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Aged Positions</div>
    <div class="stat-value" id="risk-aged">—</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Correlated Events</div>
    <div class="stat-value" id="risk-corr">—</div>
  </div>
</div>

<div style="display:grid;grid-template-columns:2fr 1fr;gap:20px;margin-bottom:24px">
  <div class="chart-wrap">
    <h2>Exposure by City</h2>
    <div id="city-exposure-chart" style="height:260px"></div>
  </div>
  <div class="chart-wrap">
    <h2>Directional Bias</h2>
    <div id="directional-chart" style="height:260px"></div>
  </div>
</div>

<div class="chart-wrap section">
  <h2>Expiry Clustering (dates with 2+ positions settling)</h2>
  <div id="expiry-chart" style="height:200px"></div>
</div>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', filename='risk.js') }}"></script>
{% endblock %}
```

- [ ] **Step 5: Create static/risk.js**

```javascript
// static/risk.js
(function () {
  'use strict';

  var LAYOUT = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: 'var(--text)', family: 'Consolas', size: 12 },
    margin: { t: 20, b: 40, l: 80, r: 20 }
  };

  function loadRisk() {
    fetch('/api/risk').then(function (r) { return r.json(); }).then(function (d) {
      // Risk stat cards
      var tExp = document.getElementById('risk-total-exp');
      if (tExp) tExp.textContent = (d.total_exposure * 100).toFixed(1) + '%';
      var aged = document.getElementById('risk-aged');
      if (aged) aged.textContent = (d.aged_positions || []).length;
      var corr = document.getElementById('risk-corr');
      if (corr) corr.textContent = (d.correlated_events || []).length;

      // City exposure horizontal bar chart (sorted descending by spec)
      var ce = d.city_exposure || [];
      var ceEl = document.getElementById('city-exposure-chart');
      if (ceEl && ce.length && typeof Plotly !== 'undefined') {
        Plotly.newPlot(ceEl, [{
          type: 'bar', orientation: 'h',
          x: ce.map(function (c) { return c.exposure; }),
          y: ce.map(function (c) { return c.city; }),
          marker: { color: 'var(--accent)' }
        }], Object.assign({}, LAYOUT, {
          xaxis: { title: '$', gridcolor: 'var(--border)', zeroline: false },
          yaxis: { gridcolor: 'var(--border)', automargin: true }
        }), { responsive: true });
      } else if (ceEl && !ce.length) {
        ceEl.innerHTML = '<p class="neu" style="padding:20px">No open positions.</p>';
      }

      // Directional bias donut
      var dir = d.directional || {};
      var dirEl = document.getElementById('directional-chart');
      if (dirEl && typeof Plotly !== 'undefined') {
        Plotly.newPlot(dirEl, [{
          type: 'pie', hole: 0.5,
          labels: ['YES', 'NO'],
          values: [dir.yes || 0, dir.no || 0],
          marker: { colors: ['#3fb950', '#f85149'] },
          textinfo: 'label+percent'
        }], Object.assign({}, LAYOUT, { margin: { t: 20, b: 20, l: 20, r: 20 } }), { responsive: true });
      }

      // Expiry clustering bar chart — each bar = a date with 2+ positions
      var ec = d.expiry_clustering || [];
      var ecEl = document.getElementById('expiry-chart');
      if (ecEl && ec.length && typeof Plotly !== 'undefined') {
        Plotly.newPlot(ecEl, [{
          type: 'bar',
          x: ec.map(function (e) { return e.date; }),
          y: ec.map(function (e) { return e.count; }),
          text: ec.map(function (e) { return '$' + e.total_cost.toFixed(2); }),
          marker: { color: ec.map(function (e) {
            return e.count >= 4 ? 'var(--neg)' : e.count >= 3 ? 'var(--warn)' : 'var(--accent)';
          })}
        }], Object.assign({}, LAYOUT, {
          xaxis: { gridcolor: 'var(--border)' },
          yaxis: { title: 'Position Count', gridcolor: 'var(--border)', zeroline: false, dtick: 1 }
        }), { responsive: true });
      } else if (ecEl && !ec.length) {
        ecEl.innerHTML = '<p class="neu" style="padding:20px">No expiry concentration risk.</p>';
      }
    }).catch(function () {});
  }

  loadRisk();
}());
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_web_app.py::test_risk_route_returns_200_with_title tests/test_web_app.py::test_api_risk_returns_correct_shape -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web_app.py templates/risk.html static/risk.js tests/test_web_app.py
git commit -m "feat: add Risk page with city exposure, directional bias, expiry clustering"
```

---

### Task 8: Trades page — /api/trades + trades.html + trades.js

**Files:**
- Modify: `web_app.py` (add `/trades` route + `/api/trades` endpoint)
- Create: `templates/trades.html`
- Create: `static/trades.js`
- Modify: `tests/test_web_app.py` (add 2 tests)

Note: `paper.get_trade_history()` does not exist. Use `paper.get_all_trades()` filtered by `t.get("settled")`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_web_app.py`:

```python
def test_trades_route_returns_200_with_title(client):
    """Trades page returns 200 and contains 'Trades'."""
    r = client.get("/trades")
    assert r.status_code == 200
    assert b"Trades" in r.data


def test_api_trades_returns_correct_shape(client):
    """/api/trades returns open and closed keys as lists."""
    with (
        patch("paper.get_open_trades", return_value=[
            {"id": 1, "ticker": "T1", "city": "NYC", "side": "yes",
             "entry_price": 0.6, "cost": 10.0, "target_date": "2025-12-01"}
        ]),
        patch("paper.get_all_trades", return_value=[
            {"id": 1, "ticker": "T1", "settled": False, "city": "NYC", "side": "yes"},
            {"id": 2, "ticker": "T2", "settled": True, "pnl": 5.0, "city": "LA",
             "side": "no", "outcome": "no"},
        ]),
    ):
        r = client.get("/api/trades")
        assert r.status_code == 200
        d = r.get_json()
        assert "open" in d
        assert "closed" in d
        assert len(d["open"]) == 1
        assert len(d["closed"]) == 1
        assert d["closed"][0]["ticker"] == "T2"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_web_app.py::test_trades_route_returns_200_with_title tests/test_web_app.py::test_api_trades_returns_correct_shape -v
```

Expected: FAIL with 404.

- [ ] **Step 3: Add /trades route and /api/trades endpoint to web_app.py inside `_build_app`**

```python
    @app.route("/trades")
    def trades_page():
        return render_template("trades.html")

    @app.route("/api/trades")
    def api_trades():
        try:
            from paper import get_all_trades, get_open_trades
        except ImportError as e:
            return jsonify({"error": str(e)}), 500

        open_trades = get_open_trades()

        # Enrich open trades with current implied prob from SSE snapshot
        snapshot = {m["ticker"]: m for m in _get_live_market_snapshot()}
        for t in open_trades:
            snap = snapshot.get(t.get("ticker", ""), {})
            t["current_yes_ask"] = snap.get("yes_ask")

        all_trades = get_all_trades()
        closed = [t for t in all_trades if t.get("settled")]

        return jsonify({"open": open_trades, "closed": closed})
```

- [ ] **Step 4: Create templates/trades.html**

```html
{% extends "base.html" %}
{% block title %}Trades{% endblock %}
{% block page_title %}Trades{% endblock %}

{% block content %}
<div class="section">
  <h2>Open Positions</h2>
  <div id="open-trades-table"><p class="neu">Loading…</p></div>
</div>

<div class="section">
  <h2>Closed Trade History</h2>
  <div style="display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap">
    <select id="filter-city" style="background:var(--surface);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:4px;font-size:0.85em">
      <option value="">All Cities</option>
    </select>
    <select id="filter-side" style="background:var(--surface);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:4px;font-size:0.85em">
      <option value="">All Sides</option>
      <option value="yes">YES</option>
      <option value="no">NO</option>
    </select>
  </div>
  <div id="closed-trades-table"><p class="neu">Loading…</p></div>
  <div class="pagination" id="trades-pagination"></div>
</div>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', filename='trades.js') }}"></script>
{% endblock %}
```

- [ ] **Step 5: Create static/trades.js**

```javascript
// static/trades.js
(function () {
  'use strict';

  var PAGE_SIZE = 25;
  var _closed = [];
  var _page = 0;

  function loadTrades() {
    fetch('/api/trades').then(function (r) { return r.json(); }).then(function (d) {
      renderOpen(d.open || []);
      _closed = d.closed || [];
      populateCityFilter(_closed);
      renderClosed();
    }).catch(function () {});
  }

  function renderOpen(trades) {
    var el = document.getElementById('open-trades-table');
    if (!el) return;
    if (!trades.length) { el.innerHTML = '<p class="neu">No open positions.</p>'; return; }
    var html = '<table><tr><th>Ticker</th><th>City</th><th>Side</th><th>Entry</th>'
      + '<th>Current</th><th>Cost</th><th>Expiry</th></tr>';
    trades.forEach(function (t) {
      var sideCls = t.side === 'yes' ? 'badge badge-green' : 'badge badge-red';
      var cur = (t.current_yes_ask !== undefined && t.current_yes_ask !== null)
        ? t.current_yes_ask + '¢' : '—';
      html += '<tr><td>' + (t.ticker || '—') + '</td>'
        + '<td>' + (t.city || '—') + '</td>'
        + '<td><span class="' + sideCls + '">' + (t.side || '').toUpperCase() + '</span></td>'
        + '<td>' + (t.entry_price !== undefined ? (t.entry_price * 100).toFixed(0) + '¢' : '—') + '</td>'
        + '<td>' + cur + '</td>'
        + '<td>$' + (t.cost || 0).toFixed(2) + '</td>'
        + '<td>' + (t.target_date || '—') + '</td></tr>';
    });
    html += '</table>';
    el.innerHTML = html;
  }

  function populateCityFilter(trades) {
    var cities = Array.from(new Set(
      trades.map(function (t) { return t.city || ''; }).filter(Boolean)
    )).sort();
    var sel = document.getElementById('filter-city');
    if (sel) {
      cities.forEach(function (c) {
        var opt = document.createElement('option');
        opt.value = c; opt.textContent = c;
        sel.appendChild(opt);
      });
      sel.addEventListener('change', function () { _page = 0; renderClosed(); });
    }
    var sideSel = document.getElementById('filter-side');
    if (sideSel) sideSel.addEventListener('change', function () { _page = 0; renderClosed(); });
  }

  function renderClosed() {
    var cityFilter = (document.getElementById('filter-city') || {}).value || '';
    var sideFilter = (document.getElementById('filter-side') || {}).value || '';
    var filtered = _closed.filter(function (t) {
      return (!cityFilter || t.city === cityFilter) && (!sideFilter || t.side === sideFilter);
    });
    var page = filtered.slice(_page * PAGE_SIZE, (_page + 1) * PAGE_SIZE);
    var el = document.getElementById('closed-trades-table');
    if (!el) return;
    if (!page.length) { el.innerHTML = '<p class="neu">No closed trades match filter.</p>'; renderPagination(0); return; }
    var html = '<table><tr><th>Ticker</th><th>City</th><th>Side</th><th>Outcome</th><th>P&L</th></tr>';
    page.forEach(function (t) {
      var p = t.pnl || 0;
      var pCls = p >= 0 ? 'pos' : 'neg';
      var pStr = (p >= 0 ? '+$' : '-$') + Math.abs(p).toFixed(2);
      var outCls = t.outcome === 'yes' ? 'badge badge-green' : 'badge badge-red';
      html += '<tr><td>' + (t.ticker || '—') + '</td>'
        + '<td>' + (t.city || '—') + '</td>'
        + '<td>' + (t.side || '').toUpperCase() + '</td>'
        + '<td><span class="' + outCls + '">' + (t.outcome || '—').toUpperCase() + '</span></td>'
        + '<td class="' + pCls + '">' + pStr + '</td></tr>';
    });
    html += '</table>';
    el.innerHTML = html;
    renderPagination(Math.ceil(filtered.length / PAGE_SIZE));
  }

  function renderPagination(pages) {
    var el = document.getElementById('trades-pagination');
    if (!el) return;
    if (pages <= 1) { el.innerHTML = ''; return; }
    var html = '';
    for (var i = 0; i < pages; i++) {
      var cls = i === _page ? ' class="active"' : '';
      html += '<button' + cls + ' onclick="window._tradePage(' + i + ')">' + (i + 1) + '</button>';
    }
    el.innerHTML = html;
  }

  window._tradePage = function (p) { _page = p; renderClosed(); };

  loadTrades();
}());
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_web_app.py::test_trades_route_returns_200_with_title tests/test_web_app.py::test_api_trades_returns_correct_shape -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web_app.py templates/trades.html static/trades.js tests/test_web_app.py
git commit -m "feat: add Trades page with open positions and closed trade history"
```

---

### Task 9: Signals page — /api/signals + signals.html + signals.js

**Files:**
- Modify: `web_app.py` (add `/signals` route + `/api/signals` endpoint)
- Create: `templates/signals.html`
- Create: `static/signals.js`
- Modify: `tests/test_web_app.py` (add 2 tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_web_app.py`:

```python
def test_signals_route_returns_200_with_title(client):
    """Signals page returns 200 and contains 'Signals'."""
    r = client.get("/signals")
    assert r.status_code == 200
    assert b"Signals" in r.data


def test_api_signals_returns_correct_shape(client):
    """/api/signals returns log and alerts keys."""
    import json
    from unittest.mock import mock_open
    fake_lines = '\n'.join([
        json.dumps({"ts": "2025-01-01T00:00:00", "ticker": "X", "signal": "BUY", "net_edge": 0.05}),
        json.dumps({"ts": "2025-01-02T00:00:00", "signal": "ALERT", "level": "WARNING", "message": "loss streak"}),
    ])
    with patch("builtins.open", mock_open(read_data=fake_lines)):
        with patch("pathlib.Path.exists", return_value=True):
            r = client.get("/api/signals")
            assert r.status_code == 200
            d = r.get_json()
            assert "log" in d
            assert "alerts" in d
            assert isinstance(d["log"], list)
            assert isinstance(d["alerts"], list)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_web_app.py::test_signals_route_returns_200_with_title tests/test_web_app.py::test_api_signals_returns_correct_shape -v
```

Expected: FAIL with 404.

- [ ] **Step 3: Add /signals route and /api/signals endpoint to web_app.py inside `_build_app`**

```python
    @app.route("/signals")
    def signals_page():
        return render_template("signals.html")

    @app.route("/api/signals")
    def api_signals():
        import pathlib

        cron_log = pathlib.Path("data/cron.log")
        entries = []
        if cron_log.exists():
            try:
                with open(cron_log, encoding="utf-8") as f:
                    lines = f.readlines()
                for line in lines[-200:]:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
            except Exception:
                pass

        alerts = [
            e for e in entries
            if e.get("signal") == "ALERT"
            or e.get("level") in ("WARNING", "ERROR")
        ]

        return jsonify({"log": entries, "alerts": alerts[-50:]})
```

- [ ] **Step 4: Create templates/signals.html**

```html
{% extends "base.html" %}
{% block title %}Signals{% endblock %}
{% block page_title %}Signals{% endblock %}

{% block content %}
<div class="section">
  <h2>Alert Feed <span style="font-size:0.8em;color:var(--text-muted)">(last 50 system alerts)</span></h2>
  <div id="alert-feed"><p class="neu">Loading…</p></div>
</div>

<div class="section">
  <h2>Cron Log <span style="font-size:0.8em;color:var(--text-muted)">(last 200 entries)</span></h2>
  <div style="display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap">
    <select id="filter-signal" style="background:var(--surface);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:4px;font-size:0.85em">
      <option value="">All Signal Types</option>
    </select>
    <select id="filter-sig-city" style="background:var(--surface);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:4px;font-size:0.85em">
      <option value="">All Cities</option>
    </select>
  </div>
  <div id="cron-log-table"><p class="neu">Loading…</p></div>
</div>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', filename='signals.js') }}"></script>
{% endblock %}
```

- [ ] **Step 5: Create static/signals.js**

```javascript
// static/signals.js
(function () {
  'use strict';

  var _log = [];

  function loadSignals() {
    fetch('/api/signals').then(function (r) { return r.json(); }).then(function (d) {
      renderAlerts(d.alerts || []);
      _log = d.log || [];
      populateFilters(_log);
      renderLog(_log);
    }).catch(function () {});
  }

  function renderAlerts(alerts) {
    var el = document.getElementById('alert-feed');
    if (!el) return;
    if (!alerts.length) { el.innerHTML = '<p class="neu">No alerts.</p>'; return; }
    var html = '<table><tr><th>Time</th><th>Level</th><th>Message</th></tr>';
    alerts.slice().reverse().forEach(function (a) {
      var lvl = a.level || a.signal || '—';
      var lvlCls = lvl === 'ERROR' ? 'neg' : lvl === 'WARNING' ? 'warn' : 'neu';
      var msg = a.message || a.signal || '';
      html += '<tr><td>' + (a.ts || '—').slice(0, 19) + '</td>'
        + '<td class="' + lvlCls + '">' + lvl + '</td>'
        + '<td>' + msg + '</td></tr>';
    });
    html += '</table>';
    el.innerHTML = html;
  }

  function populateFilters(log) {
    var signals = Array.from(new Set(
      log.map(function (e) { return e.signal || ''; }).filter(Boolean)
    )).sort();
    var cities = Array.from(new Set(
      log.map(function (e) { return e.city || ''; }).filter(Boolean)
    )).sort();

    var sigSel = document.getElementById('filter-signal');
    if (sigSel) {
      signals.forEach(function (s) {
        var o = document.createElement('option'); o.value = s; o.textContent = s;
        sigSel.appendChild(o);
      });
      sigSel.addEventListener('change', applyFilters);
    }
    var citySel = document.getElementById('filter-sig-city');
    if (citySel) {
      cities.forEach(function (c) {
        var o = document.createElement('option'); o.value = c; o.textContent = c;
        citySel.appendChild(o);
      });
      citySel.addEventListener('change', applyFilters);
    }
  }

  function applyFilters() {
    var sig = (document.getElementById('filter-signal') || {}).value || '';
    var city = (document.getElementById('filter-sig-city') || {}).value || '';
    var filtered = _log.filter(function (e) {
      return (!sig || e.signal === sig) && (!city || e.city === city);
    });
    renderLog(filtered);
  }

  function renderLog(entries) {
    var el = document.getElementById('cron-log-table');
    if (!el) return;
    if (!entries.length) { el.innerHTML = '<p class="neu">No entries match filter.</p>'; return; }
    var html = '<table><tr><th>Time</th><th>Ticker</th><th>City</th>'
      + '<th>Signal</th><th>Net Edge</th><th>Outcome</th></tr>';
    entries.slice().reverse().forEach(function (e) {
      var edge = e.net_edge;
      var edgeCls = edge > 0 ? 'pos' : edge < 0 ? 'neg' : 'neu';
      html += '<tr><td>' + (e.ts || '—').slice(0, 19) + '</td>'
        + '<td>' + (e.ticker || '—') + '</td>'
        + '<td>' + (e.city || '—') + '</td>'
        + '<td>' + (e.signal || '—') + '</td>'
        + '<td class="' + edgeCls + '">' + (edge !== undefined ? (edge * 100).toFixed(1) + '%' : '—') + '</td>'
        + '<td>' + (e.outcome !== undefined ? e.outcome : '—') + '</td></tr>';
    });
    html += '</table>';
    el.innerHTML = html;
  }

  loadSignals();
}());
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_web_app.py::test_signals_route_returns_200_with_title tests/test_web_app.py::test_api_signals_returns_correct_shape -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web_app.py templates/signals.html static/signals.js tests/test_web_app.py
git commit -m "feat: add Signals page with cron log and alert feed"
```

---

### Task 10: Forecast page — /api/forecast_quality + forecast.html + forecast.js

**Files:**
- Modify: `web_app.py` (add `/forecast` route + `/api/forecast_quality` endpoint)
- Create: `templates/forecast.html`
- Create: `static/forecast.js`
- Modify: `tests/test_web_app.py` (add 2 tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_web_app.py`:

```python
def test_forecast_route_returns_200_with_title(client):
    """Forecast page returns 200 and contains 'Forecast'."""
    r = client.get("/forecast")
    assert r.status_code == 200
    assert b"Forecast" in r.data


def test_api_forecast_quality_returns_correct_shape(client):
    """/api/forecast_quality returns city_heatmap and source_reliability keys."""
    with patch("tracker.get_calibration_by_city", return_value={
        "NYC": {"n": 10, "brier": 0.22, "bias": 0.01},
    }):
        r = client.get("/api/forecast_quality")
        assert r.status_code == 200
        d = r.get_json()
        assert "city_heatmap" in d
        assert "source_reliability" in d
        assert "NYC" in d["city_heatmap"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_web_app.py::test_forecast_route_returns_200_with_title tests/test_web_app.py::test_api_forecast_quality_returns_correct_shape -v
```

Expected: FAIL with 404.

- [ ] **Step 3: Add /forecast route and /api/forecast_quality endpoint to web_app.py inside `_build_app`**

```python
    @app.route("/forecast")
    def forecast_page():
        return render_template("forecast.html")

    @app.route("/api/forecast_quality")
    def api_forecast_quality():
        city_cal = {}
        try:
            from tracker import get_calibration_by_city
            city_cal = get_calibration_by_city() or {}
        except Exception:
            pass

        ensemble_accuracy = {}
        try:
            from tracker import get_ensemble_member_accuracy
            acc = get_ensemble_member_accuracy()
            if acc:
                ensemble_accuracy = acc
        except Exception:
            pass

        return jsonify({
            "city_heatmap": city_cal,
            "source_reliability": ensemble_accuracy,
        })
```

- [ ] **Step 4: Create templates/forecast.html**

```html
{% extends "base.html" %}
{% block title %}Forecast{% endblock %}
{% block page_title %}Forecast Quality{% endblock %}

{% block content %}
<div class="chart-wrap section">
  <h2>City Brier Score Heat Map <span style="font-size:0.8em;color:var(--text-muted)">(green = well-calibrated, red = poor)</span></h2>
  <div id="city-heatmap" style="height:300px"></div>
</div>

<div class="section">
  <h2>Source Reliability Scorecard</h2>
  <div id="source-reliability-table"><p class="neu">Loading…</p></div>
</div>

<div class="chart-wrap section">
  <h2>Ensemble Agreement <span style="font-size:0.8em;color:var(--text-muted)">(std dev of member MAE — shorter = more agreement)</span></h2>
  <div id="ensemble-chart" style="height:220px"></div>
</div>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', filename='forecast.js') }}"></script>
{% endblock %}
```

- [ ] **Step 5: Create static/forecast.js**

```javascript
// static/forecast.js
(function () {
  'use strict';

  var LAYOUT = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: 'var(--text)', family: 'Consolas', size: 12 },
    margin: { t: 20, b: 60, l: 100, r: 20 }
  };

  function loadForecast() {
    fetch('/api/forecast_quality').then(function (r) { return r.json(); }).then(function (d) {
      renderCityHeatmap(d.city_heatmap || {});
      renderSourceReliability(d.source_reliability || {});
    }).catch(function () {});
  }

  function renderCityHeatmap(cityHeatmap) {
    var el = document.getElementById('city-heatmap');
    if (!el || typeof Plotly === 'undefined') return;
    var cities = Object.keys(cityHeatmap).sort();
    if (!cities.length) {
      el.innerHTML = '<p class="neu" style="padding:20px">No calibration data yet.</p>';
      return;
    }
    var brierVals = cities.map(function (c) { return (cityHeatmap[c] || {}).brier || 0; });
    Plotly.newPlot(el, [{
      type: 'bar', orientation: 'h',
      x: brierVals,
      y: cities,
      text: brierVals.map(function (v) { return v.toFixed(3); }),
      textposition: 'outside',
      marker: { color: brierVals.map(function (v) {
        return v < 0.25 ? 'var(--pos)' : v < 0.35 ? 'var(--warn)' : 'var(--neg)';
      })}
    }], Object.assign({}, LAYOUT, {
      xaxis: { title: 'Brier Score', gridcolor: 'var(--border)', zeroline: false },
      yaxis: { gridcolor: 'var(--border)', automargin: true }
    }), { responsive: true });
  }

  function renderSourceReliability(acc) {
    var el = document.getElementById('source-reliability-table');
    if (!el) return;
    var cities = Object.keys(acc).sort();
    if (!cities.length) {
      el.innerHTML = '<p class="neu">No ensemble member data yet.</p>';
      renderEnsembleChart({});
      return;
    }
    var html = '<table><tr><th>City</th><th>Model</th><th>MAE (°F)</th><th>N</th></tr>';
    cities.forEach(function (city) {
      var models = acc[city] || {};
      Object.keys(models).sort().forEach(function (model) {
        var stats = models[model] || {};
        html += '<tr><td>' + city + '</td><td>' + model + '</td>'
          + '<td>' + (stats.mae !== undefined ? stats.mae.toFixed(2) : '—') + '</td>'
          + '<td>' + (stats.n || 0) + '</td></tr>';
      });
    });
    html += '</table>';
    el.innerHTML = html;
    renderEnsembleChart(acc);
  }

  function renderEnsembleChart(acc) {
    var ensembleEl = document.getElementById('ensemble-chart');
    if (!ensembleEl || typeof Plotly === 'undefined') return;
    var cityNames = [];
    var stdVals = [];
    Object.keys(acc).sort().forEach(function (city) {
      var models = acc[city] || {};
      var maes = Object.values(models).map(function (s) { return s.mae || 0; });
      if (maes.length > 1) {
        var mean = maes.reduce(function (a, b) { return a + b; }, 0) / maes.length;
        var variance = maes.reduce(function (a, v) {
          return a + (v - mean) * (v - mean);
        }, 0) / maes.length;
        cityNames.push(city);
        stdVals.push(Math.round(Math.sqrt(variance) * 100) / 100);
      }
    });
    if (!cityNames.length) {
      ensembleEl.innerHTML = '<p class="neu" style="padding:20px">Need 2+ ensemble members per city.</p>';
      return;
    }
    Plotly.newPlot(ensembleEl, [{
      type: 'bar',
      x: cityNames,
      y: stdVals,
      marker: { color: stdVals.map(function (v) {
        return v < 1.0 ? 'var(--pos)' : v < 2.0 ? 'var(--warn)' : 'var(--neg)';
      })}
    }], Object.assign({}, LAYOUT, {
      margin: { t: 20, b: 40, l: 55, r: 20 },
      xaxis: { gridcolor: 'var(--border)' },
      yaxis: { title: 'Std Dev (MAE °F)', gridcolor: 'var(--border)', zeroline: false }
    }), { responsive: true });
  }

  loadForecast();
}());
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_web_app.py::test_forecast_route_returns_200_with_title tests/test_web_app.py::test_api_forecast_quality_returns_correct_shape -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web_app.py templates/forecast.html static/forecast.js tests/test_web_app.py
git commit -m "feat: add Forecast page with city heat map and source reliability scorecard"
```

---

### Task 11: Full regression check

**Files:** No changes — run only.

- [ ] **Step 1: Run the full test suite**

```bash
pytest -v
```

Expected outcomes:
- All 280 previously passing tests continue to pass
- All 13 new tests added in Tasks 3–10 pass
- The 13 pre-existing failures in `test_paper.py` remain as-is (they were failing before this work)

- [ ] **Step 2: If any new test fails, diagnose before fixing**

Common failure modes and fixes:
- **`TemplateNotFound: dashboard.html`**: Flask couldn't find `templates/`. Confirm `templates/` folder is in the same directory as `web_app.py` (the project root).
- **`render_template` not imported**: Check the Flask import block inside `_build_app` — `render_template` must be in the import list.
- **Mock patch 404 on API tests**: The patch path must match where the name is *used*, not where it's *defined*. If `web_app.py` imports `from paper import get_open_trades`, patch `"paper.get_open_trades"`. If it imports `import paper` and calls `paper.get_open_trades()`, patch `"paper.get_open_trades"` (same result in this case).
- **`pathlib.Path.exists` patch scope**: The signals test patches `pathlib.Path.exists`. If the endpoint calls `cron_log.exists()` directly, this should work. If it fails, narrow the patch to `"web_app.pathlib.Path.exists"`.

- [ ] **Step 3: Commit any fixes**

```bash
git add <only changed files>
git commit -m "fix: correct patch paths and template discovery"
```

- [ ] **Step 4: Final check — verify static files are served**

Start the Flask dev server:

```bash
python main.py web
```

Open `http://localhost:5000` in a browser. Verify:
- Sidebar is visible with all 6 nav links
- Dark theme is default (dark background)
- Theme toggle button switches to light mode and persists across refresh
- Balance history chart renders (Plotly)
- Navigating to `/analytics`, `/risk`, `/trades`, `/signals`, `/forecast` all load without errors

Stop the server when done (Ctrl+C).
