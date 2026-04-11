# Group G — Dashboard & Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete four dashboard and analytics improvements: parameterised balance-history range, model-attribution endpoint, per-market SSE stream, and price-improvement tracking with API endpoint.
**Architecture:** All four items add or extend routes inside `_build_app()` in `web_app.py`, backed by existing helper functions in `tracker.py` and `paper.py`; `execution_log.py` is NOT involved — price-improvement tracking lives in `tracker.py`. The SSE market stream is a second event-stream endpoint alongside the existing `/api/stream`; model attribution reads the `blend_sources` JSON column already present in the `predictions` table.
**Tech Stack:** Python 3.11, Flask, SQLite (via `tracker.py`/`paper.py`), Server-Sent Events, pytest

---

### Task 1: Balance history range parameter (#81)

**Context:** `/api/balance_history` already exists in `web_app.py` (line 182) and already parses a `range` query parameter using `_RANGE_DAYS`. The implementation is complete. This task writes the missing test to lock in the behaviour.

**Files:**
- Modify: `tests/test_web_app.py`

- [ ] Step 1: Write failing test — append to `tests/test_web_app.py`:

```python
# ── #81 balance-history range parameter ──────────────────────────────────────

def test_balance_history_range_3mo(tmp_path, monkeypatch):
    """?range=3mo returns a different (longer) slice than the default 50-point cap."""
    import json
    from datetime import UTC, datetime, timedelta

    import paper
    import web_app

    # Synthesise 100 history points spanning 120 days
    now = datetime.now(UTC)
    fake_history = [
        {"ts": (now - timedelta(days=120 - i)).isoformat(), "balance": 1000.0 + i}
        for i in range(100)
    ]
    monkeypatch.setattr(paper, "get_balance_history", lambda: fake_history)
    monkeypatch.setattr(web_app, "_now_utc", lambda: now)

    app = web_app._build_app(client=None)
    client = app.test_client()

    default_resp = client.get("/api/balance_history")
    range_resp = client.get("/api/balance_history?range=3mo")

    default_data = json.loads(default_resp.data)
    range_data = json.loads(range_resp.data)

    # default is capped at 50; 3mo should include more points (≥ 75 of the 100)
    assert default_resp.status_code == 200
    assert range_resp.status_code == 200
    assert len(default_data["values"]) == 50
    assert len(range_data["values"]) > 50
```

- [ ] Step 2: Run test (expect FAIL — route exists but test is new; should actually PASS immediately because implementation is already present):

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_web_app.py -k "test_balance_history_range_3mo" -x -v
```

Expected output: `1 passed`

- [ ] Step 3: If the test fails, the range filtering in `web_app.py` `balance_history()` (lines 182–223) needs to be verified. The existing logic filters by `cutoff = _now_utc() - timedelta(days=_RANGE_DAYS[range_param])`. Confirm `_now_utc` is monkeypatchable (it is — defined at module level line 19). No code change should be needed.

- [ ] Step 4: Run full suite to confirm no regressions:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -x -q
```

Expected output: all tests pass.

- [ ] Step 5: Commit:

```
git -C "C:/Users/thesa/claude kalshi" add tests/test_web_app.py
git -C "C:/Users/thesa/claude kalshi" commit -m "test: add range parameter test for /api/balance_history (#81)"
```

---

### Task 2: Model attribution endpoint (#84)

**Context:** `tracker.py` already has `blend_sources` column in `predictions` and `get_component_attribution()`. The `/api/analytics` endpoint already calls `get_component_attribution()`. What is missing is a dedicated `/api/model-attribution` endpoint that returns per-city averages, and a `log_blend_sources` call in `weather_markets.py` `analyze_trade()` (though `analyze_trade` already populates `blend_sources` in its return dict and `tracker.log_prediction` already accepts `blend_sources` — check that the call site in `weather_markets.py` or `main.py` actually passes it through).

**Files:**
- Modify: `web_app.py` (add route inside `_build_app()`)
- Modify: `tracker.py` (add `get_model_attribution_by_city()` helper)
- Modify: `tests/test_web_app.py` (append test)

- [ ] Step 1: Write failing test — append to `tests/test_web_app.py`:

```python
# ── #84 model attribution endpoint ───────────────────────────────────────────

def test_model_attribution_endpoint_returns_city_keys(monkeypatch):
    """GET /api/model-attribution returns JSON with at least one city key,
    each city mapping to a dict of source weights."""
    import json
    import web_app

    fake_attribution = {
        "Chicago": {"ensemble": 0.6, "nws": 0.25, "climatology": 0.15},
        "Dallas": {"ensemble": 0.5, "nws": 0.35, "climatology": 0.15},
    }

    import tracker
    monkeypatch.setattr(tracker, "get_model_attribution_by_city", lambda: fake_attribution)

    app = web_app._build_app(client=None)
    client = app.test_client()

    resp = client.get("/api/model-attribution")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert isinstance(data, dict)
    assert len(data) >= 1
    first_city = next(iter(data.values()))
    assert isinstance(first_city, dict)
    assert "ensemble" in first_city
```

- [ ] Step 2: Run test (expect FAIL — route does not exist yet):

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_web_app.py -k "test_model_attribution_endpoint" -x -v
```

Expected output: `FAILED` (404 or AttributeError on `tracker.get_model_attribution_by_city`).

- [ ] Step 3: Implement — first add helper to `tracker.py` (append before the final blank line):

```python
# ── #84 per-city model attribution ────────────────────────────────────────────

def get_model_attribution_by_city() -> dict[str, dict[str, float]]:
    """Return average blend-source weights per city from settled predictions.

    Returns: {city: {source: avg_weight, ...}, ...}
    Only cities with at least one prediction that has blend_sources recorded.
    """
    import json as _json2

    init_db()
    with _conn() as con:
        rows = con.execute(
            """SELECT city, blend_sources
               FROM predictions
               WHERE blend_sources IS NOT NULL AND city IS NOT NULL"""
        ).fetchall()

    if not rows:
        return {}

    from collections import defaultdict

    city_totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    city_counts: dict[str, int] = defaultdict(int)

    for row in rows:
        city = row["city"]
        try:
            sources = _json2.loads(row["blend_sources"])
        except (ValueError, TypeError):
            continue
        if not isinstance(sources, dict):
            continue
        for k, v in sources.items():
            city_totals[city][k] += float(v)
        city_counts[city] += 1

    result: dict[str, dict[str, float]] = {}
    for city, totals in city_totals.items():
        n = city_counts[city]
        result[city] = {k: round(v / n, 4) for k, v in totals.items()}
    return result
```

Then add the route inside `_build_app()` in `web_app.py`, immediately after the `/api/analytics` route block (around line 270):

```python
    @app.route("/api/model-attribution")
    def model_attribution():
        """#84 — per-city average model blend weights."""
        try:
            from tracker import get_model_attribution_by_city

            data = get_model_attribution_by_city()
            return jsonify(data)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
```

- [ ] Step 4: Run passing test:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_web_app.py -k "test_model_attribution_endpoint" -x -v
```

Expected output: `1 passed`

- [ ] Step 5: Commit:

```
git -C "C:/Users/thesa/claude kalshi" add web_app.py tracker.py tests/test_web_app.py
git -C "C:/Users/thesa/claude kalshi" commit -m "feat: add /api/model-attribution endpoint with per-city blend weights (#84)"
```

---

### Task 3: Per-market SSE stream endpoint (#85)

**Context:** `/api/stream` (line 162) already exists and streams portfolio-level data (balance, open count, brier score). Item #85 asks for a second SSE endpoint `/api/stream/markets` that streams the current open-markets list specifically, so the market table in the frontend can auto-update without a full page reload. `_get_live_market_snapshot()` is already defined at module level (line 26).

**Files:**
- Modify: `web_app.py` (add `/api/stream/markets` route inside `_build_app()`)
- Modify: `tests/test_web_app.py` (append test)

- [ ] Step 1: Write failing test — append to `tests/test_web_app.py`:

```python
# ── #85 per-market SSE stream ─────────────────────────────────────────────────

def test_stream_markets_content_type(monkeypatch):
    """GET /api/stream/markets returns Content-Type: text/event-stream."""
    import web_app

    # Patch the generator's sleep so the test doesn't block
    import time
    monkeypatch.setattr(time, "sleep", lambda _: (_ for _ in ()).throw(StopIteration()))

    app = web_app._build_app(client=None)
    client = app.test_client()

    resp = client.get("/api/stream/markets")
    assert "text/event-stream" in resp.content_type
```

- [ ] Step 2: Run test (expect FAIL — route does not exist):

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_web_app.py -k "test_stream_markets_content_type" -x -v
```

Expected output: `FAILED` (404).

- [ ] Step 3: Implement — add route inside `_build_app()` in `web_app.py`, after the existing `/api/stream` route (around line 181):

```python
    @app.route("/api/stream/markets")
    def stream_markets():
        """#85 — SSE endpoint that yields open-market snapshots every 10 s."""
        import time

        def generate():
            while True:
                try:
                    payload = {
                        "markets": _get_live_market_snapshot(),
                        "ts": datetime.now(UTC).isoformat(),
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                except Exception:
                    yield "data: {}\n\n"
                time.sleep(10)

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
```

Also add the EventSource subscriber in the market-table template. Locate the market table in `web_app.py` (inside the `/analyze` or `/` route HTML). Add the following `<script>` block just before the closing `</body>` tag of any template that renders a market table:

```html
<script>
(function () {
  if (!window.EventSource) return;
  var es = new EventSource('/api/stream/markets');
  es.onmessage = function (e) {
    try {
      var payload = JSON.parse(e.data);
      var markets = payload.markets || [];
      var tbody = document.getElementById('market-table-body');
      if (!tbody || markets.length === 0) return;
      tbody.innerHTML = markets.map(function (m) {
        return '<tr><td>' + (m.ticker || '') + '</td><td>' + (m.yes_bid || '') +
               '</td><td>' + (m.yes_ask || '') + '</td></tr>';
      }).join('');
      var ts = document.getElementById('last-updated');
      if (ts) ts.textContent = payload.ts ? payload.ts.slice(0, 19).replace('T', ' ') : '';
    } catch (_) {}
  };
})();
</script>
```

Note: the exact element IDs (`market-table-body`, `last-updated`) must match what is already in the template. Verify with a quick grep before inserting.

- [ ] Step 4: Run passing test:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_web_app.py -k "test_stream_markets_content_type" -x -v
```

Expected output: `1 passed`

- [ ] Step 5: Commit:

```
git -C "C:/Users/thesa/claude kalshi" add web_app.py tests/test_web_app.py
git -C "C:/Users/thesa/claude kalshi" commit -m "feat: add /api/stream/markets SSE endpoint and EventSource subscriber (#85)"
```

---

### Task 4: Price improvement tracking and API endpoint (#65)

**Context:** `tracker.log_price_improvement(ticker, desired, actual, quantity, side)` already exists in `tracker.py` (line 1409). It writes to the `price_improvement` table. `tracker.get_price_improvement_stats()` (line 1447) returns `{mean, median, count, positive_pct}` but returns `None` if fewer than 5 rows. What is missing: (a) calling `log_price_improvement` inside `paper.place_paper_order` after the simulated fill, and (b) a `/api/price-improvement` endpoint in `web_app.py`.

**Files:**
- Modify: `paper.py` (call `log_price_improvement` after fill in `place_paper_order`)
- Modify: `web_app.py` (add `/api/price-improvement` route inside `_build_app()`)
- Modify: `tests/test_web_app.py` (append test)

- [ ] Step 1: Write failing test — append to `tests/test_web_app.py`:

```python
# ── #65 price-improvement endpoint ───────────────────────────────────────────

def test_price_improvement_endpoint_returns_valid_json(monkeypatch):
    """GET /api/price-improvement returns JSON with avg_improvement_cents and total_trades."""
    import json
    import web_app

    import tracker
    monkeypatch.setattr(
        tracker,
        "get_price_improvement_stats",
        lambda: {"mean": 0.02, "median": 0.015, "count": 12, "positive_pct": 0.75},
    )

    app = web_app._build_app(client=None)
    client = app.test_client()

    resp = client.get("/api/price-improvement")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "avg_improvement_cents" in data
    assert "total_trades" in data
    assert isinstance(data["total_trades"], int)
```

- [ ] Step 2: Run test (expect FAIL — route does not exist):

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_web_app.py -k "test_price_improvement_endpoint" -x -v
```

Expected output: `FAILED` (404).

- [ ] Step 3: Implement both changes.

**3a — Wire `log_price_improvement` into `paper.place_paper_order`.**

In `paper.py`, find the end of `place_paper_order` where the trade dict is assembled and saved (around line 395–410, after `data["balance"] -= cost` and `data["trades"].append(trade)`). Add the call immediately after `_save(data)`:

```python
    # #65: record price improvement (paper fill = entry_price, desired = entry_price for paper)
    try:
        from tracker import log_price_improvement as _log_pi
        _log_pi(ticker, desired=entry_price, actual=entry_price, quantity=quantity, side=side)
    except Exception:
        pass  # never block a trade on logging failure
```

Note: for paper trades the desired and actual prices are the same (no slippage simulated), so improvement will be 0. This still creates the audit row so the endpoint has data. If the codebase later adds simulated slippage, replace `actual=entry_price` with the slipped value.

**3b — Add the API endpoint in `web_app.py`** inside `_build_app()`, after the `/api/status` route:

```python
    @app.route("/api/price-improvement")
    def price_improvement():
        """#65 — aggregate price improvement stats."""
        try:
            from tracker import get_price_improvement_stats

            stats = get_price_improvement_stats()
            if stats is None:
                return jsonify({"avg_improvement_cents": None, "total_trades": 0,
                                "note": "insufficient data (< 5 trades)"})
            # convert raw float improvement (0–1 scale) to cents (multiply by 100)
            avg_cents = round(stats["mean"] * 100, 4)
            return jsonify({
                "avg_improvement_cents": avg_cents,
                "total_trades": stats["count"],
                "median_improvement_cents": round(stats["median"] * 100, 4),
                "positive_pct": stats["positive_pct"],
            })
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
```

- [ ] Step 4: Run passing test:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_web_app.py -k "test_price_improvement_endpoint" -x -v
```

Expected output: `1 passed`

- [ ] Step 5: Run full suite:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -x -q
```

Expected output: all tests pass.

- [ ] Step 6: Commit:

```
git -C "C:/Users/thesa/claude kalshi" add paper.py web_app.py tests/test_web_app.py
git -C "C:/Users/thesa/claude kalshi" commit -m "feat: wire log_price_improvement into place_paper_order and add /api/price-improvement endpoint (#65)"
```
