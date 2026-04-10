# Phase 6: Dashboard Improvements
**Date**: 2026-04-10  
**Covers**: #81, #84, #85  
**Approach**: TDD — write failing test → confirm red → implement → confirm green → commit

---

## Overview

Three dashboard improvements:
- **#81**: Balance history endpoint hardcoded to 50 most recent points — add time-range selector
- **#84**: Analytics page lacks model attribution (which blend source adds value) — log components, expose in API
- **#85**: Dashboard shows stale prices requiring manual refresh — add SSE-pushed market updates every 10s

---

## Task 1 — Balance history time-range selector (#81)

### Context
`web_app.py:160`: `points = history[-50:]`  
`get_balance_history()` in `paper.py:1027` returns list of `{"ts": ISO string, "balance": float}` sorted by time.  
`/api/balance_history` currently returns the last 50 points regardless of total history length.

### Failing test
**File**: `tests/test_web_app.py`

```python
import pytest
from unittest.mock import patch

HISTORY = [
    {"ts": f"2025-0{m:01d}-01T00:00:00", "balance": 1000 + m * 10, "event": "Trade"}
    for m in range(1, 10)
]


@pytest.fixture
def client():
    from web_app import _build_app
    mock_client = object()
    app = _build_app(mock_client)
    app.config["TESTING"] = True
    return app.test_client()


def test_balance_history_default_returns_50(client):
    """Default (?range not specified) returns at most 50 points."""
    big_history = [
        {"ts": f"2024-01-{d:02d}T00:00:00", "balance": 900 + d, "event": "T"}
        for d in range(1, 92)  # 91 points
    ]
    with patch("paper.get_balance_history", return_value=big_history):
        r = client.get("/api/balance_history")
        data = r.get_json()
        assert len(data["labels"]) <= 50


def test_balance_history_range_1mo(client):
    """?range=1mo returns only points from the last 30 days."""
    from datetime import datetime, timedelta, UTC

    now = datetime(2025, 9, 1, tzinfo=UTC)
    history = [
        {"ts": (now - timedelta(days=d)).isoformat(), "balance": 1000, "event": "T"}
        for d in range(60)  # 60 days of data
    ]
    with patch("paper.get_balance_history", return_value=history):
        with patch("web_app._now_utc", return_value=now):
            r = client.get("/api/balance_history?range=1mo")
            data = r.get_json()
            # Only points ≤ 30 days old should appear
            assert all(
                (now - datetime.fromisoformat(ts.replace("Z", "+00:00"))).days <= 30
                for ts in data["labels"]
            )


def test_balance_history_range_3mo(client):
    """?range=3mo returns only points from the last 90 days."""
    from datetime import datetime, timedelta, UTC

    now = datetime(2025, 9, 1, tzinfo=UTC)
    history = [
        {"ts": (now - timedelta(days=d)).isoformat(), "balance": 1000, "event": "T"}
        for d in range(200)
    ]
    with patch("paper.get_balance_history", return_value=history):
        with patch("web_app._now_utc", return_value=now):
            r = client.get("/api/balance_history?range=3mo")
            data = r.get_json()
            assert all(
                (now - datetime.fromisoformat(ts.replace("Z", "+00:00"))).days <= 90
                for ts in data["labels"]
            )


def test_balance_history_range_all(client):
    """?range=all returns every point."""
    big_history = [
        {"ts": f"2024-01-{d:02d}T00:00:00", "balance": 900 + d, "event": "T"}
        for d in range(1, 92)
    ]
    with patch("paper.get_balance_history", return_value=big_history):
        r = client.get("/api/balance_history?range=all")
        data = r.get_json()
        assert len(data["labels"]) == 91


def test_balance_history_invalid_range_falls_back_to_default(client):
    """Unknown ?range value falls back to 50-point default."""
    big_history = [
        {"ts": f"2024-01-{d:02d}T00:00:00", "balance": 900 + d, "event": "T"}
        for d in range(1, 92)
    ]
    with patch("paper.get_balance_history", return_value=big_history):
        r = client.get("/api/balance_history?range=bogus")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["labels"]) <= 50
```

**Run**: `pytest tests/test_web_app.py::test_balance_history_range_1mo -x` → expect `FAILED` (KeyError or AssertionError).

### Implementation

**Step 1**: Add `_now_utc()` helper to `web_app.py` (just after imports, before `_build_app`):

```python
def _now_utc():
    """Mockable timestamp source for tests."""
    from datetime import UTC, datetime
    return datetime.now(UTC)
```

**Step 2**: Replace `balance_history` route in `web_app.py:155-166`:

```python
@app.route("/api/balance_history")
def balance_history():
    from datetime import UTC, datetime, timedelta
    from paper import get_balance_history

    history = get_balance_history()
    range_param = request.args.get("range", "default")

    # Determine cutoff
    now = _now_utc()
    if range_param == "1mo":
        cutoff = now - timedelta(days=30)
    elif range_param == "3mo":
        cutoff = now - timedelta(days=90)
    elif range_param == "1yr":
        cutoff = now - timedelta(days=365)
    elif range_param == "all":
        cutoff = None
    else:
        # Default: last 50 points
        points = history[-50:]
        return jsonify({
            "labels": [p["ts"][:16] or "Start" for p in points],
            "values": [p["balance"] for p in points],
        })

    if cutoff is not None:
        filtered = []
        for p in history:
            ts_str = p.get("ts", "")
            if not ts_str:
                filtered.append(p)  # always include "Start" sentinel
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts >= cutoff:
                    filtered.append(p)
            except ValueError:
                pass
        points = filtered
    else:
        points = history

    return jsonify({
        "labels": [p["ts"][:16] or "Start" for p in points],
        "values": [p["balance"] for p in points],
    })
```

Also add `from flask import request` to the imports inside `_build_app` if not already present.

**Step 3**: Add range selector buttons to the balance chart JS in `web_app.py` (inside `chart_js`):

Find the line `fetch('/api/balance_history').then(...)` and replace with:

```javascript
function loadBalanceChart(range) {
  fetch('/api/balance_history?range=' + (range || 'default')).then(r=>r.json()).then(data => {
    const ctx = document.getElementById('balanceChart');
    if (!ctx) return;
    if (window._balanceChart) window._balanceChart.destroy();
    window._balanceChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: data.labels,
        datasets: [{
          label: 'Balance ($)',
          data: data.values,
          borderColor: '#58a6ff',
          backgroundColor: 'rgba(88,166,255,0.08)',
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          borderWidth: 2,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { display: false },
          y: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } }
        }
      }
    });
  });
}
loadBalanceChart('default');
```

Add HTML range buttons just before the `<canvas id="balanceChart">` element:

```html
<div style="margin-bottom:8px;">
  <span style="color:#8b949e;font-size:0.8em;margin-right:8px;">Range:</span>
  <button onclick="loadBalanceChart('1mo')" style="background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:2px 8px;cursor:pointer;margin-right:4px;">1mo</button>
  <button onclick="loadBalanceChart('3mo')" style="background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:2px 8px;cursor:pointer;margin-right:4px;">3mo</button>
  <button onclick="loadBalanceChart('1yr')" style="background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:2px 8px;cursor:pointer;margin-right:4px;">1yr</button>
  <button onclick="loadBalanceChart('all')" style="background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:2px 8px;cursor:pointer;">All</button>
</div>
```

**Run**: `pytest tests/test_web_app.py -k "balance_history" -x` → expect all green.

**Commit**:
```
git add web_app.py tests/test_web_app.py
git commit -m "feat: balance history time-range selector (1mo/3mo/1yr/all) (#81)"
```

---

## Task 2 — Model attribution analytics (#84)

### Context
`analyze_trade()` in `weather_markets.py` already returns `blend_sources` — e.g. `{"ensemble": 0.6, "climatology": 0.3, "nws": 0.1}`.  
The prediction is logged to `tracker.py` via `log_prediction()`. We need to:
1. Persist `blend_sources` as JSON in the `predictions` table.
2. Add `get_component_attribution()` in `tracker.py` — for each source, compute mean Brier score and compare to overall.
3. Expose via `/api/analytics` and render in the analytics page.

### Failing tests
**File**: `tests/test_tracker.py` (append to existing file)

```python
def test_log_prediction_stores_blend_sources(tmp_db):
    """blend_sources dict is stored and retrievable."""
    import json
    from tracker import log_prediction, _con

    log_prediction(
        ticker="KXWEATHER-A",
        city="NYC",
        condition="HIGH_ABOVE_70",
        target_date=date(2025, 6, 1),
        forecast_prob=0.65,
        market_prob=0.55,
        days_out=3,
        blend_sources={"ensemble": 0.6, "climatology": 0.3, "nws": 0.1},
    )
    with _con() as con:
        row = con.execute(
            "SELECT blend_sources FROM predictions WHERE ticker='KXWEATHER-A'"
        ).fetchone()
    stored = json.loads(row[0])
    assert stored == {"ensemble": 0.6, "climatology": 0.3, "nws": 0.1}


def test_get_component_attribution_returns_per_source_brier(tmp_db):
    """get_component_attribution returns Brier score by dominant source."""
    from tracker import log_prediction, settle_prediction, get_component_attribution
    from datetime import date

    # Two predictions: one ensemble-dominant (settled yes, prob 0.9 → good)
    # one climatology-dominant (settled no, prob 0.8 → bad)
    log_prediction(
        ticker="ENS1",
        city="NYC",
        condition="HIGH_ABOVE_70",
        target_date=date(2025, 6, 1),
        forecast_prob=0.90,
        market_prob=0.5,
        days_out=2,
        blend_sources={"ensemble": 0.7, "climatology": 0.2, "nws": 0.1},
    )
    settle_prediction("ENS1", date(2025, 6, 1), True)

    log_prediction(
        ticker="CLIM1",
        city="NYC",
        condition="HIGH_ABOVE_70",
        target_date=date(2025, 6, 2),
        forecast_prob=0.80,
        market_prob=0.5,
        days_out=2,
        blend_sources={"ensemble": 0.2, "climatology": 0.7, "nws": 0.1},
    )
    settle_prediction("CLIM1", date(2025, 6, 2), False)

    result = get_component_attribution()
    assert "ensemble" in result
    assert "climatology" in result
    # ensemble-dominant trade had lower Brier (good) than climatology-dominant
    assert result["ensemble"]["brier"] < result["climatology"]["brier"]
    assert result["ensemble"]["n"] == 1
    assert result["climatology"]["n"] == 1
```

**Run**: `pytest tests/test_tracker.py::test_get_component_attribution_returns_per_source_brier -x` → `FAILED`.

### Implementation

**Step 1**: Add migration in `tracker.py` `_MIGRATIONS` list:

```python
# Migration N+1: add blend_sources column to predictions
(N+1, "ALTER TABLE predictions ADD COLUMN blend_sources TEXT"),
```
(Replace `N+1` with the next migration index after whatever was added in Phase 2.)

**Step 2**: Update `log_prediction()` signature and INSERT in `tracker.py`:

```python
def log_prediction(
    ticker: str,
    city: str,
    condition: str,
    target_date,
    forecast_prob: float,
    market_prob: float,
    days_out: int,
    blend_sources: dict | None = None,
    forecast_cycle: str | None = None,
) -> None:
    import json as _json
    sources_json = _json.dumps(blend_sources) if blend_sources else None
    with _con() as con:
        con.execute(
            """INSERT OR REPLACE INTO predictions
               (ticker, city, condition, target_date, predicted_at,
                forecast_prob, market_prob, days_out, blend_sources, forecast_cycle)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                ticker, city, condition,
                target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date),
                _now_iso(),
                forecast_prob, market_prob, days_out,
                sources_json, forecast_cycle,
            ),
        )
```

**Step 3**: Add `get_component_attribution()` in `tracker.py`:

```python
def get_component_attribution() -> dict[str, dict]:
    """
    For each forecast source (ensemble, climatology, nws), find predictions where
    that source has the highest blend weight. Compute mean Brier score for each group.

    Returns:
        {
          "ensemble": {"n": int, "brier": float},
          "climatology": {"n": int, "brier": float},
          "nws": {"n": int, "brier": float},
        }
    """
    import json as _json

    with _con() as con:
        rows = con.execute(
            """SELECT blend_sources, forecast_prob, outcome
               FROM predictions
               WHERE outcome IS NOT NULL
                 AND blend_sources IS NOT NULL"""
        ).fetchall()

    buckets: dict[str, list[float]] = {}

    for row in rows:
        sources_json, prob, outcome = row
        try:
            sources = _json.loads(sources_json)
        except (ValueError, TypeError):
            continue
        if not sources:
            continue
        # Dominant source = key with highest weight
        dominant = max(sources, key=lambda k: sources[k])
        brier = (prob - outcome) ** 2
        buckets.setdefault(dominant, []).append(brier)

    return {
        source: {
            "n": len(scores),
            "brier": round(sum(scores) / len(scores), 4) if scores else None,
        }
        for source, scores in buckets.items()
    }
```

**Step 4**: Wire `blend_sources` into `analyze_trade()` call in `weather_markets.py`.

`blend_sources` is already computed in the function and included in the return dict. When `tracker.log_prediction()` is called after `analyze_trade()`, pass it through. Search `weather_markets.py` for `log_prediction(` calls and add the kwarg:

```python
tracker.log_prediction(
    ...,
    blend_sources=result.get("blend_sources"),
)
```

**Step 5**: Expose in `/api/analytics` in `web_app.py:168`:

```python
@app.route("/api/analytics")
def api_analytics():
    try:
        from tracker import (
            brier_score,
            get_brier_by_days_out,
            get_calibration_by_city,
            get_component_attribution,   # ← add this import
        )
        result: dict = {
            "brier": brier_score(),
            "brier_by_days": get_brier_by_days_out(),
            "component_attribution": get_component_attribution(),  # ← add this
            ...
        }
```

**Step 6**: Render attribution table in the analytics page HTML (inside the analytics template string):

```html
{% if analytics.component_attribution %}
<h2>Forecast Source Attribution</h2>
<table>
  <tr><th>Source</th><th>Dominant-Source Trades</th><th>Mean Brier Score</th></tr>
  {% for src, stats in analytics.component_attribution.items() %}
  <tr>
    <td>{{ src.title() }}</td>
    <td>{{ stats.n }}</td>
    <td class="{{ 'pos' if stats.brier is not none and stats.brier < 0.25 else 'neg' }}">
      {{ '%.4f'|format(stats.brier) if stats.brier is not none else 'N/A' }}
    </td>
  </tr>
  {% endfor %}
</table>
{% endif %}
```

(Note: the dashboard uses `render_template_string`, not Jinja2 template files — use Python f-string formatting matching the existing pattern in `web_app.py:596`.)

**Run**: `pytest tests/test_tracker.py -k "attribution or blend_sources" -x` → expect all green.

**Commit**:
```
git add tracker.py weather_markets.py web_app.py tests/test_tracker.py
git commit -m "feat: model attribution analytics — log blend_sources, Brier by source (#84)"
```

---

## Task 3 — Real-time market updates in dashboard (#85)

### Context
The existing SSE endpoint at `/api/stream` (`web_app.py:127`) already pushes balance/brier/open_count every 30 seconds. The market analysis table (Analyze page) shows prices that only update on manual page refresh.

The fix is to add market data (top opportunities) to the SSE stream and update the analyze table in the JavaScript SSE listener — OR add a separate lightweight endpoint that the JS polls every 10 seconds.

**Chosen approach**: SSE extension (simplest — reuse existing connection). Add `top_markets` (top 5 by edge) to the SSE payload. On the frontend, update a "live opportunities" widget rather than the full analyze table (full re-analyze is expensive; SSE is for price awareness).

### Failing tests
**File**: `tests/test_web_app.py` (append)

```python
def test_stream_includes_market_snapshot_key(client):
    """SSE stream data includes 'markets' key for real-time price awareness."""
    # We can't easily test SSE streaming in Flask test client,
    # so test the data-building function directly.
    from web_app import _build_stream_data

    with patch("paper.get_balance", return_value=1050.0), \
         patch("paper.get_open_trades", return_value=[]), \
         patch("tracker.brier_score", return_value=0.18), \
         patch("web_app._get_live_market_snapshot", return_value=[
             {"ticker": "KXWEATHER-A", "yes_ask": 0.62, "edge": 0.08}
         ]):
        data = _build_stream_data()
        assert "markets" in data
        assert isinstance(data["markets"], list)


def test_get_live_market_snapshot_returns_list(monkeypatch):
    """_get_live_market_snapshot returns a list (possibly empty) without crashing."""
    from web_app import _get_live_market_snapshot

    monkeypatch.setattr("web_app._client", None)
    result = _get_live_market_snapshot()
    assert isinstance(result, list)
```

**Run**: `pytest tests/test_web_app.py::test_stream_includes_market_snapshot_key -x` → `FAILED` (no `_build_stream_data` or `_get_live_market_snapshot`).

### Implementation

**Step 1**: Extract stream data building into a testable function in `web_app.py`. Add before `_build_app`:

```python
def _get_live_market_snapshot(max_markets: int = 5) -> list[dict]:
    """
    Return a lightweight snapshot of top market prices without running full analysis.
    Uses the cached results from the last analyze run if available, to avoid
    hitting the API on every SSE tick.
    
    Returns list of dicts: [{"ticker": str, "yes_ask": float, "edge": float}, ...]
    """
    try:
        if _client is None:
            return []
        # Use the module-level cache written by the analyze route
        cached = getattr(_get_live_market_snapshot, "_cache", [])
        return cached[:max_markets]
    except Exception:
        return []


def _build_stream_data() -> dict:
    """Build the SSE payload dict. Extracted for testability."""
    from paper import get_balance, get_open_trades
    from tracker import brier_score

    return {
        "balance": round(get_balance(), 2),
        "open_count": len(get_open_trades()),
        "brier": brier_score(),
        "markets": _get_live_market_snapshot(),
        "ts": datetime.now(UTC).isoformat(),
    }
```

**Step 2**: Update the `generate()` function inside `/api/stream` to use `_build_stream_data()`:

```python
def generate():
    while True:
        try:
            data = _build_stream_data()
            yield f"data: {json.dumps(data)}\n\n"
        except Exception:
            yield "data: {}\n\n"
        time.sleep(10)  # was 30s; reduce to 10s for market awareness (#85)
```

**Step 3**: Populate `_get_live_market_snapshot._cache` when the analyze route runs. Inside the `analyze` route (around `web_app.py:407-435`), after building the analysis rows list:

```python
# Update live market snapshot cache for SSE
_get_live_market_snapshot._cache = [
    {
        "ticker": row["ticker"],
        "yes_ask": row.get("yes_ask", 0),
        "edge": row.get("edge", 0),
    }
    for row in sorted(rows, key=lambda r: r.get("edge", 0), reverse=True)
    if row.get("edge", 0) > 0
][:10]
```

**Step 4**: Update the SSE JavaScript listener in the dashboard HTML to display live market prices. Find the existing SSE event handler (look for `EventSource` or `onmessage` in `web_app.py`) and add market rendering:

```javascript
source.onmessage = function(e) {
  const d = JSON.parse(e.data);
  if (d.balance !== undefined) {
    document.getElementById('live-balance').textContent = '$' + d.balance.toFixed(2);
  }
  if (d.brier !== undefined) {
    document.getElementById('live-brier').textContent = d.brier.toFixed(4);
  }
  if (d.markets && d.markets.length > 0) {
    const el = document.getElementById('live-markets');
    if (el) {
      el.innerHTML = d.markets.slice(0, 3).map(m =>
        `<span style="margin-right:12px;">${m.ticker}: <strong>${(m.yes_ask*100).toFixed(0)}¢</strong> <span class="${m.edge > 0 ? 'pos' : 'neg'}">(${m.edge > 0 ? '+' : ''}${(m.edge*100).toFixed(1)}%)</span></span>`
      ).join('');
    }
  }
  // Update last-seen timestamp
  const tsEl = document.getElementById('live-ts');
  if (tsEl) tsEl.textContent = 'Updated ' + new Date().toLocaleTimeString();
};
```

Add a `<div id="live-markets"></div>` element near the top of the dashboard page next to the live dot.

**Run**: `pytest tests/test_web_app.py -k "stream or snapshot" -x` → expect all green.

**Commit**:
```
git add web_app.py tests/test_web_app.py
git commit -m "feat: real-time market snapshot in SSE stream, 10s update interval (#85)"
```

---

## Execution order

```
Task 1  →  Task 2  →  Task 3
(independent; can run in sequence)
```

Each task: write tests → confirm red → implement → confirm green → commit.
