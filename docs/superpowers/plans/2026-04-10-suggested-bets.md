# Suggested Bets + Risk Tolerance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface Kelly-sized bet recommendations on the `/analyze` page and loosen risk thresholds to capture more profitable opportunities.

**Architecture:** Raise the Kelly cap from 25% → 33% in `weather_markets.py`, lower `MIN_EDGE` from 10% → 7% in `utils.py`, add a `/api/suggested_bets` endpoint to `web_app.py` that ranks opportunities by EV, and update the `/analyze` page with a pinned top-3 card and a "Bet $X" column.

**Tech Stack:** Python/Flask, `paper.get_balance()`, existing `analyze_trade()` pipeline, `render_template_string` for HTML

---

## File map

| File | Action | What changes |
|------|--------|--------------|
| `weather_markets.py` | Modify line 1367 | Kelly cap `0.25` → `0.33` |
| `utils.py` | Modify line 18 | `MIN_EDGE` default `"0.10"` → `"0.07"` |
| `web_app.py` | Modify | Add `/api/suggested_bets` endpoint; update `/analyze` HTML string |
| `tests/test_weather_markets.py` | Append | `TestKellyCap` class (1 test) |
| `tests/test_suggested_bets.py` | Create | Ranking test + empty-list test |

---

### Task 1: Raise Kelly cap to 33%

**Files:**
- Modify: `weather_markets.py:1367`
- Modify: `tests/test_weather_markets.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_weather_markets.py` after the last class:

```python
# ── TestKellyCap ──────────────────────────────────────────────────────────────


class TestKellyCap:
    """Verify kelly_fraction hard cap is 33% (raised from 25%)."""

    def test_kelly_fraction_caps_at_33_pct(self):
        """Very high edge → fraction is capped at 0.33, not 0.25."""
        from weather_markets import kelly_fraction

        # our_prob=0.95, price=0.10: full Kelly would be enormous
        result = kelly_fraction(our_prob=0.95, price=0.10, fee_rate=0.02)
        assert result == pytest.approx(0.33, abs=1e-6), (
            f"Expected Kelly cap 0.33, got {result}"
        )
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_weather_markets.py::TestKellyCap -v
```

Expected: FAIL — `AssertionError: Expected Kelly cap 0.33, got 0.25`

- [ ] **Step 3: Raise the cap in `weather_markets.py`**

At line 1367, change:

```python
    return min(half_kelly, 0.25)  # #115: hard cap at 25% of bankroll
```

to:

```python
    return min(half_kelly, 0.33)  # hard cap at 33% of bankroll
```

- [ ] **Step 4: Run to confirm it passes**

```bash
python -m pytest tests/test_weather_markets.py::TestKellyCap -v
```

Expected: PASS

- [ ] **Step 5: Run full weather_markets suite to confirm no regressions**

```bash
python -m pytest tests/test_weather_markets.py -v --tb=short 2>&1 | tail -5
```

Expected: All tests pass (no failures in the 48 existing tests).

- [ ] **Step 6: Commit**

```bash
git add tests/test_weather_markets.py weather_markets.py
git commit -m "feat: raise Kelly hard cap from 25% to 33% of bankroll"
```

---

### Task 2: Lower MIN_EDGE default to 7%

**Files:**
- Modify: `utils.py:18`

- [ ] **Step 1: Verify the current value**

```bash
cd "C:/Users/thesa/claude kalshi"
python -c "from utils import MIN_EDGE; print(MIN_EDGE)"
```

Expected: `0.1`

- [ ] **Step 2: Change the default in `utils.py`**

At line 18, change:

```python
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.10"))  # minimum edge to show in analyze
```

to:

```python
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.07"))  # minimum edge to show in analyze
```

- [ ] **Step 3: Verify the new value**

```bash
python -c "from utils import MIN_EDGE; print(MIN_EDGE)"
```

Expected: `0.07`

- [ ] **Step 4: Run existing tests to confirm nothing broke**

```bash
python -m pytest --ignore=tests/test_http.py -x --tb=short -q 2>&1 | tail -5
```

Expected: No new failures (13 pre-existing `test_paper.py` failures are acceptable).

- [ ] **Step 5: Commit**

```bash
git add utils.py
git commit -m "feat: lower MIN_EDGE default from 10% to 7%"
```

---

### Task 3: Add `/api/suggested_bets` endpoint

**Files:**
- Create: `tests/test_suggested_bets.py`
- Modify: `web_app.py` (add endpoint after the `/analyze` route, around line 421)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_suggested_bets.py`:

```python
"""Tests for the /api/suggested_bets endpoint."""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _make_analysis(net_edge: float, kelly: float = 0.10) -> dict:
    return {
        "forecast_prob": 0.70,
        "market_prob": 0.56,
        "edge": net_edge,
        "net_edge": net_edge,
        "recommended_side": "yes",
        "signal": "BUY YES",
        "kelly": kelly,
        "fee_adjusted_kelly": kelly,
        "ci_adjusted_kelly": kelly,
        "condition": {"type": "above", "threshold": 68.0},
    }


def _make_market(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "title": f"Test market {ticker}",
        "_city": "NYC",
        "yes_ask": 0.55,
        "series_ticker": "KXHIGHNY",
    }


class TestSuggestedBetsEndpoint:
    """Tests for /api/suggested_bets."""

    @patch("web_app.get_balance", return_value=100.0)
    @patch("web_app.analyze_trade")
    @patch("web_app.enrich_with_forecast", side_effect=lambda m: m)
    @patch("web_app.get_weather_markets")
    def test_returns_top_n_sorted_by_ev(
        self, mock_markets, mock_enrich, mock_analyze, mock_balance
    ):
        """Returns top-n opportunities ranked by EV = net_edge × kelly_dollars."""
        from web_app import create_app

        markets = [
            _make_market("KXHIGHNY-A"),
            _make_market("KXHIGHNY-B"),
            _make_market("KXHIGHNY-C"),
            _make_market("KXHIGHNY-D"),
            _make_market("KXHIGHNY-E"),
        ]
        mock_markets.return_value = markets

        # EV = net_edge * (kelly * balance):
        # A: 0.08 * (0.05 * 100) = 0.40
        # B: 0.20 * (0.10 * 100) = 2.00  ← rank 2
        # C: 0.30 * (0.15 * 100) = 4.50  ← rank 1
        # D: 0.12 * (0.08 * 100) = 0.96  ← rank 3
        # E: 0.06 * (0.03 * 100) = 0.18  (below threshold if MIN_EDGE=0.07, still included)
        analyses = {
            "KXHIGHNY-A": _make_analysis(net_edge=0.08, kelly=0.05),
            "KXHIGHNY-B": _make_analysis(net_edge=0.20, kelly=0.10),
            "KXHIGHNY-C": _make_analysis(net_edge=0.30, kelly=0.15),
            "KXHIGHNY-D": _make_analysis(net_edge=0.12, kelly=0.08),
            "KXHIGHNY-E": _make_analysis(net_edge=0.06, kelly=0.03),
        }

        def side_effect(enriched):
            return analyses[enriched["ticker"]]

        mock_analyze.side_effect = side_effect

        app = create_app()
        with app.test_client() as client:
            resp = client.get("/api/suggested_bets?n=3")

        assert resp.status_code == 200
        data = resp.get_json()
        assert "bets" in data
        assert len(data["bets"]) == 3
        tickers = [b["ticker"] for b in data["bets"]]
        assert tickers[0] == "KXHIGHNY-C", f"Expected C first (highest EV), got {tickers}"
        assert tickers[1] == "KXHIGHNY-B", f"Expected B second, got {tickers}"
        assert tickers[2] == "KXHIGHNY-D", f"Expected D third, got {tickers}"

    @patch("web_app.get_balance", return_value=100.0)
    @patch("web_app.analyze_trade", return_value=None)
    @patch("web_app.enrich_with_forecast", side_effect=lambda m: m)
    @patch("web_app.get_weather_markets")
    def test_empty_when_no_opportunities(
        self, mock_markets, mock_enrich, mock_analyze, mock_balance
    ):
        """Returns empty bets list when analyze_trade returns None for all markets."""
        from web_app import create_app

        mock_markets.return_value = [_make_market("KXHIGHNY-X")]

        app = create_app()
        with app.test_client() as client:
            resp = client.get("/api/suggested_bets")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["bets"] == []
        assert "balance" in data
        assert "generated_at" in data
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_suggested_bets.py -v --tb=short
```

Expected: FAIL — `ImportError` or `404` (endpoint doesn't exist yet)

- [ ] **Step 3: Check `web_app.py` for `create_app` pattern**

```bash
python -c "from web_app import create_app; print('ok')"
```

If this raises `ImportError`, find how the Flask app is exposed in `web_app.py` (look for `app = Flask(...)` or a factory function) and adapt the test's `from web_app import create_app` / `create_app()` call to match. The test must import the Flask app object to use `test_client()`.

- [ ] **Step 4: Add `/api/suggested_bets` to `web_app.py`**

Add the following endpoint inside the app factory or at module level, after the `/analyze` route (around line 421). Add at the top of the file the import of `get_weather_markets`, `enrich_with_forecast`, `analyze_trade` (check if already imported) and `get_balance`. Then add:

```python
@app.route("/api/suggested_bets")
def api_suggested_bets():
    """Return top-N trade opportunities ranked by expected value (edge × kelly $)."""
    from weather_markets import analyze_trade, enrich_with_forecast, get_weather_markets
    from paper import get_balance
    from utils import MIN_EDGE
    from datetime import datetime, timezone

    n = int(request.args.get("n", 3))

    try:
        markets = get_weather_markets(client)
    except Exception as e:
        return jsonify({"error": str(e), "bets": []}), 500

    balance = get_balance()
    candidates = []

    for m in markets:
        try:
            enriched = enrich_with_forecast(m)
            analysis = analyze_trade(enriched)
            if not analysis:
                continue
            net_edge = abs(analysis.get("net_edge", analysis.get("edge", 0)))
            if net_edge < MIN_EDGE:
                continue
            kelly = analysis.get("ci_adjusted_kelly", analysis.get("fee_adjusted_kelly", analysis.get("kelly", 0)))
            kelly_dollars = round(kelly * balance, 2)
            ev_score = net_edge * kelly_dollars
            candidates.append({
                "ticker": m.get("ticker", ""),
                "title": (m.get("title") or m.get("ticker", ""))[:60],
                "city": m.get("_city", "—"),
                "recommended_side": analysis.get("recommended_side", "—").upper(),
                "edge_pct": round(net_edge * 100, 1),
                "kelly_fraction": round(kelly, 4),
                "suggested_dollars": kelly_dollars,
                "signal": analysis.get("signal", "—"),
                "ev_score": round(ev_score, 4),
            })
        except Exception:
            continue

    candidates.sort(key=lambda x: x["ev_score"], reverse=True)
    top = candidates[:n]
    # Remove ev_score from response (internal ranking only)
    for bet in top:
        del bet["ev_score"]

    return jsonify({
        "bets": top,
        "balance": round(balance, 2),
        "min_edge": MIN_EDGE,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    })
```

Also ensure `request` and `jsonify` are imported at the top of `web_app.py` (they should already be there — verify with `grep "from flask import" web_app.py`).

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_suggested_bets.py -v --tb=short
```

Expected:
```
PASSED tests/test_suggested_bets.py::TestSuggestedBetsEndpoint::test_returns_top_n_sorted_by_ev
PASSED tests/test_suggested_bets.py::TestSuggestedBetsEndpoint::test_empty_when_no_opportunities
2 passed
```

If tests fail due to import differences (e.g., `web_app` doesn't expose `get_weather_markets` at module level), update the patch paths to match the actual import location (e.g., `weather_markets.get_weather_markets` instead of `web_app.get_weather_markets`).

- [ ] **Step 6: Run full suite to confirm no regressions**

```bash
python -m pytest --ignore=tests/test_http.py -q --tb=short 2>&1 | tail -5
```

Expected: No new failures beyond the 13 pre-existing `test_paper.py` ones.

- [ ] **Step 7: Commit**

```bash
git add tests/test_suggested_bets.py web_app.py
git commit -m "feat: add /api/suggested_bets endpoint ranked by EV"
```

---

### Task 4: Update `/analyze` page with pinned card + Bet $ column

**Files:**
- Modify: `web_app.py` — update the `/analyze` route's HTML string (lines 377–420)

No new tests needed — this is UI-only HTML/JS changes.

- [ ] **Step 1: Add the pinned card + Bet $ column to the `/analyze` route**

In `web_app.py`, find the `/analyze` route. Make two changes to the HTML string:

**Change A:** Add a pinned "Top Bets" card right after `{NAV}` and before the `<p class="refreshing"` countdown paragraph. Insert:

```python
TOP_BETS_CARD = """
<div id="top-bets-card" style="background:var(--surface);border:1px solid var(--border);
     border-radius:8px;padding:16px;margin-bottom:20px">
  <h2 style="margin:0 0 12px 0;font-size:1.1em">Today&rsquo;s Top Bets</h2>
  <div id="top-bets-body" style="font-size:0.9em;color:var(--text-muted)">Loading&hellip;</div>
</div>
<script>
fetch('/api/suggested_bets?n=3')
  .then(r => r.json())
  .then(data => {
    const el = document.getElementById('top-bets-body');
    if (!data.bets || data.bets.length === 0) {
      el.textContent = 'No strong bets today.';
      return;
    }
    const rows = data.bets.map((b, i) => {
      const badge = b.recommended_side === 'YES'
        ? '<span class="badge badge-green">YES</span>'
        : '<span class="badge badge-red">NO</span>';
      return `<div style="display:flex;gap:16px;align-items:center;padding:6px 0;
                    border-bottom:1px solid var(--border)">
        <span style="font-weight:bold;color:var(--text-muted);min-width:24px">#${i+1}</span>
        <span style="flex:1;font-family:monospace">${b.ticker}</span>
        <span style="flex:2;color:var(--text)">${b.title}</span>
        ${badge}
        <span class="pos">+${b.edge_pct}%</span>
        <span style="font-weight:bold;color:var(--accent,#4ade80)">Bet $${b.suggested_dollars.toFixed(2)}</span>
      </div>`;
    }).join('');
    el.innerHTML = rows + `<p style="margin-top:8px;font-size:0.82em;color:var(--text-muted)">
      Balance: $${data.balance.toFixed(2)} &mdash; Min edge: ${(data.min_edge*100).toFixed(0)}%</p>`;
  })
  .catch(() => {
    document.getElementById('top-bets-body').textContent = 'Could not load suggestions.';
  });
</script>
"""
```

In the route, insert `{TOP_BETS_CARD}` right after `{NAV}` in the HTML f-string.

**Change B:** Add "Bet $" column header and cell to the table.

Find the table header line:
```python
  <tr><th>Ticker</th><th>Question</th><th>City</th><th>We Think</th><th>Mkt Says</th>
      <th>Edge</th><th>Risk</th><th>Buy</th></tr>
```

Change to:
```python
  <tr><th>Ticker</th><th>Question</th><th>City</th><th>We Think</th><th>Mkt Says</th>
      <th>Edge</th><th>Risk</th><th>Bet</th><th>Buy</th></tr>
```

Find the row construction in `rows_html +=` and add the Kelly dollar cell. The row currently ends with `<td>{side_badge}</td>`. Before that line, you need the balance and Kelly fraction. Update the loop to compute `kelly_dollars`:

```python
    for m, a in opps:
        net_edge = a.get("net_edge", a["edge"])
        edge_cls = "pos" if net_edge > 0 else "neg"
        edge_str = f"+{net_edge:.0%}" if net_edge > 0 else f"{net_edge:.0%}"
        ticker = m.get("ticker", "")
        kelly = a.get("ci_adjusted_kelly", a.get("fee_adjusted_kelly", a.get("kelly", 0)))
        kelly_dollars = kelly * _balance
        bet_cell = f"${kelly_dollars:.2f}" if kelly_dollars >= 0.05 else "—"
        side_badge = (
            '<span class="badge badge-green">YES</span>'
            if a["recommended_side"] == "yes"
            else '<span class="badge badge-red">NO</span>'
        )
        rows_html += f"""
        <tr>
          <td>{ticker}</td>
          <td>{(m.get("title") or ticker)[:38]}</td>
          <td>{m.get("_city", "—")}</td>
          <td>{a["forecast_prob"]:.0%}</td>
          <td>{a["market_prob"]:.0%}</td>
          <td class="{edge_cls}">{edge_str}</td>
          <td>{a.get("time_risk", "—")}</td>
          <td>{bet_cell}</td>
          <td>{side_badge}</td>
        </tr>"""
```

Add `_balance = get_balance()` near the top of the `/analyze` route function, right after `from utils import MIN_EDGE`. Also add `from paper import get_balance` alongside that import if not already present.

- [ ] **Step 2: Verify the page loads without errors**

Start the app (or use the test client) and check `/analyze` loads:

```bash
cd "C:/Users/thesa/claude kalshi"
python -c "
from web_app import create_app
app = create_app()
with app.test_client() as c:
    resp = c.get('/analyze')
    print(resp.status_code)
    print('top-bets-card' in resp.data.decode())
    print('Bet' in resp.data.decode())
"
```

Expected:
```
200
True
True
```

- [ ] **Step 3: Run full suite**

```bash
python -m pytest --ignore=tests/test_http.py -q --tb=short 2>&1 | tail -5
```

Expected: No new failures beyond the 13 pre-existing `test_paper.py` ones.

- [ ] **Step 4: Commit**

```bash
git add web_app.py
git commit -m "feat: add suggested bets card and Bet $ column to /analyze page"
```

---

## Self-review

**Spec coverage:**
- Kelly cap 25% → 33% → Task 1 ✓
- MIN_EDGE 10% → 7% → Task 2 ✓
- `/api/suggested_bets` endpoint → Task 3 ✓
- Pinned top-3 card on `/analyze` → Task 4 ✓
- "Bet $X" column in table → Task 4 ✓
- Rank by EV = edge × kelly_dollars → Task 3 (endpoint sorts) + Task 4 (card fetches endpoint) ✓
- Response includes balance, min_edge, generated_at → Task 3 ✓

**Placeholder scan:** No TBDs. All code blocks are complete.

**Type consistency:** `kelly` field accessed as `a.get("ci_adjusted_kelly", a.get("fee_adjusted_kelly", a.get("kelly", 0)))` — same fallback chain used in both Task 3 and Task 4. `get_balance()` from `paper` used consistently. `_balance` variable name used in Task 4 loop to avoid shadowing Flask's `balance` if it appears elsewhere.
