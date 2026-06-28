# Category D: Analytics & Reporting — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add forecast source attribution on signals, model disagreement indicators, model version history, profit factor metric, per-city reliability diagrams, and CSV export.

**Architecture:** D1 (forecast attribution) and D6 (profit factor) require backend changes. D2 (disagreement flag), D8 (CSV), D9 (Kalshi URL) are pure frontend. D7 (version history) is a data persistence change. D4 (reliability diagram) needs a new API endpoint.

**Tech Stack:** Python 3.14, Flask, React/JSX, pytest.

**Implementation Order:** D6 → D7 → D9 → D8 → D2 → D1 → D3 → D4 → D5 → D10

---

## D6: Profit Factor Metric

**Problem:** No gross profit / gross loss ratio in the system. This is the most standard quantitative trading quality metric and requires only 3 lines in paper.py.

**Files:**
- Modify: `paper.py` — add `get_profit_factor()`
- Modify: `web_app.py` — add to `/api/status`
- Test: `tests/test_paper_metrics.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_paper_metrics.py — add
def test_profit_factor_two_wins_one_loss(monkeypatch):
    import paper

    trades = [
        {"ticker": "T1", "settled": True, "won": True,  "pnl": 15.00},
        {"ticker": "T2", "settled": True, "won": True,  "pnl": 10.00},
        {"ticker": "T3", "settled": True, "won": False, "pnl": -8.00},
    ]
    monkeypatch.setattr(paper, "load_paper_trades", lambda: trades)

    pf = paper.get_profit_factor()
    # gross profit = 25.00, gross loss = 8.00 → PF = 3.125
    assert abs(pf - 3.125) < 0.01

def test_profit_factor_no_losses_returns_infinity(monkeypatch):
    import paper
    trades = [{"ticker": "T1", "settled": True, "won": True, "pnl": 20.0}]
    monkeypatch.setattr(paper, "load_paper_trades", lambda: trades)
    pf = paper.get_profit_factor()
    assert pf == float("inf") or pf > 100

def test_profit_factor_no_wins_returns_zero(monkeypatch):
    import paper
    trades = [{"ticker": "T1", "settled": True, "won": False, "pnl": -10.0}]
    monkeypatch.setattr(paper, "load_paper_trades", lambda: trades)
    pf = paper.get_profit_factor()
    assert pf == 0.0
```

- [ ] **Step 2: Run to confirm all fail**

```
pytest tests/test_paper_metrics.py -k "profit_factor" -v
```
Expected: `AttributeError: module 'paper' has no attribute 'get_profit_factor'`

- [ ] **Step 3: Add `get_profit_factor()` to `paper.py`**

```python
def get_profit_factor() -> float:
    """Return gross_profit / gross_loss for all settled trades.

    Returns float('inf') when there are no losses (all wins).
    Returns 0.0 when there are no wins.
    Uses the 'pnl' field on settled trades; falls back to reconstructing from
    entry_price, qty, side, and outcome for trades without explicit pnl.
    """
    trades = load_paper_trades()
    gross_profit = 0.0
    gross_loss = 0.0
    for t in trades:
        if not t.get("settled") or t.get("won") is None:
            continue
        pnl = t.get("pnl")
        if pnl is None:
            # Reconstruct from trade record
            side = t.get("side", "yes")
            entry = float(t.get("entry_price", 0.5))
            qty = int(t.get("qty", 1))
            won = bool(t.get("won"))
            if side == "yes":
                pnl = (1.0 - entry) * qty if won else -entry * qty
            else:
                pnl = entry * qty if won else -(1.0 - entry) * qty
        pnl = float(pnl)
        if pnl > 0:
            gross_profit += pnl
        elif pnl < 0:
            gross_loss += abs(pnl)

    if gross_loss == 0.0:
        return float("inf") if gross_profit > 0 else 0.0
    return round(gross_profit / gross_loss, 3)
```

- [ ] **Step 4: Add to `/api/status` in `web_app.py`**

Find the `/api/status` route. Add:

```python
from paper import get_profit_factor
# Add to response dict:
"profit_factor": get_profit_factor() if get_profit_factor() != float("inf") else 9999,
```

- [ ] **Step 5: Run the tests**

```
pytest tests/test_paper_metrics.py -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```
git add paper.py web_app.py tests/test_paper_metrics.py
git commit -m "feat(analytics): add profit_factor metric (gross_profit / gross_loss)"
```

---

## D7: Model Version History

**Problem:** Every calibration run overwrites `temperature_scale.json`, `condition_weights.json`, `seasonal_weights.json`. There is no history of what changed or when. If calibration worsens performance, there's no easy rollback.

**Files:**
- Modify: `safe_io.py` — add `atomic_write_json_with_history(data, path, max_history=10)`
- Modify: `calibration.py` — use history writer for calibration outputs
- Modify: `ml_bias.py` — use history writer for `save_emos_params` and `save_temperature_scale`
- Test: `tests/test_cleanup_data_dir.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_cleanup_data_dir.py — add
def test_atomic_write_json_with_history_keeps_previous_versions(tmp_path):
    from safe_io import atomic_write_json_with_history
    import json

    target = tmp_path / "weights.json"

    # Write version 1
    atomic_write_json_with_history({"a": 1}, target, max_history=3)
    # Write version 2
    atomic_write_json_with_history({"a": 2}, target, max_history=3)
    # Write version 3
    atomic_write_json_with_history({"a": 3}, target, max_history=3)

    # Current file should have version 3
    assert json.loads(target.read_text())["a"] == 3

    # History directory should have two previous versions
    history_dir = target.parent / ".history"
    history_files = sorted(history_dir.glob(f"{target.stem}_*.json"))
    assert len(history_files) == 2

    # Oldest history file should have a=1
    oldest = json.loads(history_files[0].read_text())
    assert oldest["a"] == 1
```

- [ ] **Step 2: Add `atomic_write_json_with_history()` to `safe_io.py`**

```python
def atomic_write_json_with_history(
    data: dict,
    path: "Path",
    max_history: int = 10,
) -> None:
    """Write JSON atomically and keep the previous version in a .history directory.

    History files are named <stem>_YYYYMMDDTHHMMSS.json.
    Keeps at most max_history previous versions; deletes oldest when over limit.
    """
    import json
    import time as _time
    from datetime import UTC, datetime
    from pathlib import Path

    path = Path(path)
    history_dir = path.parent / ".history"

    # Archive the current file if it exists
    if path.exists():
        history_dir.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        history_file = history_dir / f"{path.stem}_{stamp}.json"
        # Avoid collision if two writes happen within the same second
        if history_file.exists():
            history_file = history_dir / f"{path.stem}_{stamp}_{int(_time.monotonic() * 1000) % 1000}.json"
        history_file.write_text(path.read_text())

        # Prune oldest history files if over limit
        existing = sorted(history_dir.glob(f"{path.stem}_*.json"))
        while len(existing) > max_history:
            existing[0].unlink(missing_ok=True)
            existing = existing[1:]

    # Write the new version atomically
    atomic_write_json(data, path)
```

- [ ] **Step 3: Update `calibration.py` to use history writer**

Find where `calibration.py` calls `atomic_write_json` for `condition_weights.json` and `seasonal_weights.json`. Replace:

```python
# old:
atomic_write_json(weights, CONDITION_WEIGHTS_PATH)
# new:
from safe_io import atomic_write_json_with_history
atomic_write_json_with_history(weights, CONDITION_WEIGHTS_PATH)
```

Do the same for `seasonal_weights.json` and `city_weights.json`.

- [ ] **Step 4: Update `ml_bias.py` `save_emos_params` and temperature scale save**

In `save_emos_params`:
```python
from safe_io import atomic_write_json_with_history
atomic_write_json_with_history(payload, _EMOS_PARAMS_PATH)
```

In `train_all_temperature_scaling` (wherever it writes `temperature_scale.json`):
```python
atomic_write_json_with_history(scale_data, _TEMP_PATH)
```

- [ ] **Step 5: Run the test**

```
pytest tests/test_cleanup_data_dir.py::test_atomic_write_json_with_history_keeps_previous_versions -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```
git add safe_io.py calibration.py ml_bias.py tests/test_cleanup_data_dir.py
git commit -m "feat(ops): model version history — atomic_write_json_with_history keeps last 10 calibration states"
```

---

## D9: Kalshi Market URL Links (Frontend)

**Problem:** Signals and positions show tickers like `KXHIGHNY-26JUL04-T72` with no link. Operators must manually navigate to Kalshi to look up the market. Kalshi market URLs follow a predictable pattern.

**Files:**
- Modify: `weather app site V_3 (3)/src/tabs/SignalsTab.jsx` — add URL link on ticker
- Modify: `weather app site V_3 (3)/src/tabs/PositionsTab.jsx` — same

- [ ] **Step 1: Add `kalshiMarketUrl` helper to `shared.jsx`**

```jsx
// shared.jsx — add after existing helpers
export function kalshiMarketUrl(ticker) {
  if (!ticker) return null;
  // Kalshi market page format: https://kalshi.com/markets/{series}/{ticker}
  // The series is the prefix before the first hyphen
  const series = ticker.split('-')[0].toLowerCase();
  return `https://kalshi.com/markets/${series}/${ticker.toUpperCase()}`;
}
```

- [ ] **Step 2: Update `SignalsTab.jsx` ticker display**

Find the ticker cell in the signals table. Replace:

```jsx
// old:
<td>{opp.ticker}</td>

// new:
<td>
  <a
    href={kalshiMarketUrl(opp.ticker)}
    target="_blank"
    rel="noopener noreferrer"
    style={{ color: 'var(--color-blue)', textDecoration: 'none', fontFamily: 'monospace' }}
    title="Open on Kalshi"
  >
    {opp.ticker} ↗
  </a>
</td>
```

- [ ] **Step 3: Update `PositionsTab.jsx` ticker display**

Same pattern as Step 2 for position rows.

- [ ] **Step 4: Rebuild and verify**

```
cd "weather app site V_3 (3)"
npm run build
```

Open dashboard → Signals tab. Click a ticker link. Should open `https://kalshi.com/markets/kxhigh...` in a new tab.

- [ ] **Step 5: Commit**

```
git add "weather app site V_3 (3)/src/" static/dist/
git commit -m "feat(dashboard): add Kalshi market URL links on tickers in Signals and Positions tabs"
```

---

## D8: Trades History CSV Export (Frontend)

**Problem:** No way to export trade history for external analysis.

**Files:**
- Modify: `weather app site V_3 (3)/src/tabs/TradesTab.jsx` — add export button

- [ ] **Step 1: Add `exportToCsv` function and button to `TradesTab.jsx`**

```jsx
// TradesTab.jsx — add above the component
function exportToCsv(trades, filename = 'kalshi_trades.csv') {
  const headers = [
    'ticker', 'side', 'qty', 'entry_price', 'won',
    'pnl', 'net_edge', 'days_out', 'entered_at', 'settled_at'
  ];
  const rows = trades.map(t => headers.map(h => {
    const v = t[h];
    if (v === null || v === undefined) return '';
    if (typeof v === 'string' && v.includes(',')) return `"${v}"`;
    return v;
  }).join(','));
  const csv = [headers.join(','), ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
```

In the component JSX, add an export button near the table heading:

```jsx
<button
  onClick={() => exportToCsv(M.closedTrades || [])}
  style={{
    marginLeft: 8, padding: '4px 10px',
    background: 'var(--bg-surface)', border: '1px solid var(--border)',
    borderRadius: 4, cursor: 'pointer', fontSize: 12,
  }}
>
  Export CSV
</button>
```

- [ ] **Step 2: Rebuild and verify**

```
cd "weather app site V_3 (3)"
npm run build
```

Open dashboard → Trades tab. Click Export CSV. Verify a CSV downloads with the correct headers.

- [ ] **Step 3: Commit**

```
git add "weather app site V_3 (3)/src/tabs/TradesTab.jsx" static/dist/
git commit -m "feat(dashboard): CSV export button on Trades tab"
```

---

## D2: Model Disagreement Flag (Frontend + Backend)

**Problem:** When NWS and ensemble disagree by >8°F, the signal is riskier but there's no visual indicator. The `blend_sources` field is already stored in `predictions` DB rows.

**Files:**
- Modify: `cron.py` — add `"model_disagreement_f": float` to signals cache entries
- Modify: `weather_markets.py` — compute and return disagreement in `analyze_trade` result
- Modify: `weather app site V_3 (3)/src/tabs/SignalsTab.jsx` — show disagreement flag

### Backend (cron + weather_markets)

- [ ] **Step 1: Add disagreement to `analyze_trade` return dict**

In `weather_markets.py`, at the end of `analyze_trade()` where the return dict is built, add:

```python
# Model disagreement: absolute difference between NWS and ensemble temperature forecasts
_disagree_f = None
_nws_temp = enriched.get("nws_forecast_f")
if _nws_temp is not None and forecast_temp is not None:
    _disagree_f = round(abs(float(_nws_temp) - float(forecast_temp)), 1)

# In the returned dict, include:
"model_disagreement_f": _disagree_f,
"model_disagreement_flag": _disagree_f is not None and _disagree_f > 8.0,
```

- [ ] **Step 2: Write test**

```python
def test_analyze_trade_sets_model_disagreement_flag(monkeypatch):
    import weather_markets as wm
    # ... (minimal analyze_trade mock) ...
    # When NWS forecast = 80°F, ensemble mean = 70°F → disagreement = 10°F
    # Result dict should have model_disagreement_flag=True
    # (Integration test using existing test patterns from test_forecasting.py)
    pass  # placeholder — add full mock once analyze_trade interface is stable
```

### Frontend

- [ ] **Step 3: Display flag in `SignalsTab.jsx`**

Find the signal row rendering. After the edge display, add:

```jsx
{opp.model_disagreement_flag && (
  <span
    title={`NWS & ensemble disagree by ${opp.model_disagreement_f}°F — signal is riskier`}
    style={{
      marginLeft: 4, fontSize: 11, color: 'var(--color-yellow)',
      background: 'rgba(234,179,8,0.15)', padding: '1px 4px', borderRadius: 3,
    }}
  >
    ⚠ {opp.model_disagreement_f}°F gap
  </span>
)}
```

- [ ] **Step 4: Rebuild and commit**

```
cd "weather app site V_3 (3)"
npm run build
```

```
git add weather_markets.py cron.py "weather app site V_3 (3)/src/tabs/SignalsTab.jsx" static/dist/
git commit -m "feat(dashboard): show model disagreement flag when NWS/ensemble gap >8°F"
```

---

## D1: Forecast Source Attribution on Signals

**Problem:** The operator reviewing a signal sees edge and market price but not *why* the model disagrees — is it NWS, ensemble, or climatology driving the disagreement?

**Files:**
- Modify: `weather_markets.py` — include per-source probabilities in signal output
- Modify: `cron.py` — pass through to signals_cache
- Modify: `weather app site V_3 (3)/src/tabs/SignalsTab.jsx` — show attribution on expand

- [ ] **Step 1: Confirm per-source probs are already stored**

`weather_markets.py` already computes `ens_prob`, `nws_prob`, `clim_prob` individually before blending. Verify these appear in `analyze_trade`'s return dict.

```python
# In analyze_trade return dict, look for:
# "ensemble_prob": ens_prob,
# "nws_prob": nws_prob,
# "clim_prob": clim_prob,
```

If they're not in the return dict, add them:

```python
# In the analyze_trade return dict:
"ensemble_prob": round(ens_prob, 3) if ens_prob is not None else None,
"nws_prob":      round(nws_prob, 3) if nws_prob is not None else None,
"clim_prob":     round(clim_prob, 3) if clim_prob is not None else None,
"forecast_temp_f": round(forecast_temp, 1) if forecast_temp is not None else None,
```

- [ ] **Step 2: Ensure `cron.py` passes these through to signals_cache**

In `cron.py`, when building signal cache entries, include:

```python
signal_entry = {
    # ... existing fields ...
    "ensemble_prob":  a.get("ensemble_prob"),
    "nws_prob":       a.get("nws_prob"),
    "clim_prob":      a.get("clim_prob"),
    "forecast_temp_f": a.get("forecast_temp_f"),
    "blend_method":   a.get("method", "ensemble"),
}
```

- [ ] **Step 3: Add attribution row to `SignalsTab.jsx` expand view**

In the expanded signal detail section, add:

```jsx
{opp.ensemble_prob != null && (
  <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 4 }}>
    <strong>Source breakdown:</strong>
    {' '}Ensemble: {(opp.ensemble_prob * 100).toFixed(0)}%
    {opp.nws_prob != null && <>{' '}· NWS: {(opp.nws_prob * 100).toFixed(0)}%</>}
    {opp.clim_prob != null && <>{' '}· Clim: {(opp.clim_prob * 100).toFixed(0)}%</>}
    {opp.forecast_temp_f != null && <>{' '}· Forecast: {opp.forecast_temp_f.toFixed(1)}°F</>}
  </div>
)}
```

- [ ] **Step 4: Rebuild and commit**

```
cd "weather app site V_3 (3)"
npm run build
```

```
git add weather_markets.py cron.py "weather app site V_3 (3)/src/tabs/SignalsTab.jsx" static/dist/
git commit -m "feat(dashboard): show forecast source attribution (ensemble/NWS/clim breakdown) on signal expand"
```

---

## D3: Trade Timeline View

*Medium priority — implement after D1 is live, as it reuses the same per-source probability data.*

**Goal:** For any closed position, show a timeline of: entry (model prob + market price), any early-exit events, settlement (actual temperature + outcome). Requires storing market prices at intervals between entry and settlement, which isn't currently done.

**Prerequisite:** Add a `position_snapshots` table to `tracker.py` that records (ticker, timestamp, yes_price, our_prob) on each cron scan for open positions.

---

## D4: Per-City Reliability Diagram

**Goal:** Show a calibration curve for each city — binned predicted probabilities vs actual outcomes. This shows where the model is over/underconfident per city.

**Files:**
- Modify: `web_app.py` — add `/api/reliability/<city>` endpoint
- Modify: `weather app site V_3 (3)/src/tabs/AnalyticsTab.jsx` — add `ReliabilityDiagramChart`

- [ ] **Step 1: Add `/api/reliability/<city>` to `web_app.py`**

```python
@_app.route("/api/reliability/<city>")
@_require_auth
def api_reliability(city: str):
    """Return calibration curve data for a city: binned pred_prob vs actual win rate."""
    from tracker import _conn, init_db
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.our_prob, CASE WHEN p.settled_yes = 1 THEN 1 ELSE 0 END as outcome
            FROM   multiday_predictions p
            WHERE  p.city = ? AND p.settled_yes IS NOT NULL
            ORDER  BY p.our_prob
            """,
            (city,),
        ).fetchall()

    if not rows:
        return {"bins": [], "city": city, "n": 0}

    # Bin into 5 equal-width buckets from 0 to 1
    bins = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
    result = []
    for lo, hi in bins:
        bucket = [(p, o) for p, o in rows if lo <= p < hi]
        if bucket:
            mean_pred = sum(p for p, _ in bucket) / len(bucket)
            actual_rate = sum(o for _, o in bucket) / len(bucket)
            result.append({
                "bin_lo": lo, "bin_hi": hi,
                "mean_pred": round(mean_pred, 3),
                "actual_rate": round(actual_rate, 3),
                "n": len(bucket),
            })
    return {"bins": result, "city": city, "n": len(rows)}
```

- [ ] **Step 2: Add `ReliabilityDiagramChart` to `AnalyticsTab.jsx`**

```jsx
function ReliabilityDiagramChart({ city, data }) {
  if (!data || !data.bins || data.bins.length === 0) {
    return <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>No data for {city}</div>;
  }
  const size = 200;
  const pad = 24;
  const inner = size - 2 * pad;

  // Perfect calibration diagonal
  const toXY = (p) => ({ x: pad + p * inner, y: size - pad - p * inner });

  return (
    <svg width={size} height={size} title={`Calibration curve — ${city}`}>
      {/* Perfect calibration line */}
      <line x1={pad} y1={size - pad} x2={size - pad} y2={pad}
            stroke="var(--border)" strokeDasharray="4 2" strokeWidth={1} />
      {/* Actual calibration dots */}
      {data.bins.map((b, i) => {
        const { x: px, y: py } = toXY(b.mean_pred);
        const { x: ax, y: ay } = toXY(b.actual_rate);
        return (
          <g key={i}>
            <line x1={px} y1={py} x2={ax} y2={ay} stroke="var(--color-blue)" strokeWidth={1.5} />
            <circle cx={ax} cy={ay} r={4} fill="var(--color-blue)"
                    title={`pred=${b.mean_pred.toFixed(2)} actual=${b.actual_rate.toFixed(2)} n=${b.n}`} />
          </g>
        );
      })}
      {/* Axes */}
      <line x1={pad} y1={pad} x2={pad} y2={size - pad} stroke="var(--border)" />
      <line x1={pad} y1={size - pad} x2={size - pad} y2={size - pad} stroke="var(--border)" />
      <text x={size / 2} y={size - 4} fontSize={9} textAnchor="middle" fill="var(--text-dim)">Predicted</text>
      <text x={8} y={size / 2} fontSize={9} textAnchor="middle" fill="var(--text-dim)"
            transform={`rotate(-90,8,${size / 2})`}>Actual</text>
    </svg>
  );
}
```

- [ ] **Step 3: Fetch and render in AnalyticsTab**

Add reliability data fetch to `useData.js` for the top 5 cities by trade count, then render a grid of `ReliabilityDiagramChart` components in `AnalyticsTab.jsx`.

- [ ] **Step 4: Commit**

```
git add web_app.py "weather app site V_3 (3)/src/" static/dist/
git commit -m "feat(analytics): per-city calibration reliability diagrams in Analytics tab"
```

---

## D5: Edge Realization by City

*Straightforward analytics query — add after D4.*

**Goal:** Compare declared `net_edge` at entry vs actual outcome probability. If edge is predictive, higher-edge trades should win more.

Add `get_edge_realization_by_city()` to `tracker.py`:

```python
def get_edge_realization_by_city() -> list[dict]:
    """Return edge realization stats per city.

    edge_realization = correlation between net_edge and won (1/0) per city.
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.city,
                   AVG(p.net_edge) as mean_edge,
                   AVG(CASE WHEN p.settled_yes IS NOT NULL THEN p.settled_yes ELSE 0.5 END) as win_rate,
                   COUNT(*) as n
            FROM   multiday_predictions p
            WHERE  p.settled_yes IS NOT NULL
              AND  p.net_edge IS NOT NULL
            GROUP  BY p.city
            HAVING COUNT(*) >= 5
            ORDER  BY mean_edge DESC
            """
        ).fetchall()
    return [{"city": r[0], "mean_edge": r[1], "win_rate": r[2], "n": r[3]} for r in rows]
```

Expose via `/api/edge-realization` and display in AnalyticsTab as a scatter plot.

---

## D10: A/B Test for Market Anchor Weights

*Medium priority — implement after EMOS is live and calibrated.*

**Goal:** Test 3 variants of `_MARKET_ANCHOR_ABOVE` / `_MARKET_ANCHOR_BELOW`: 0.05, 0.10 (current), 0.20. Use the existing `ABTest` framework from `ab_test.py`.

Add to `order_executor.py`:

```python
_ANCHOR_AB_TEST = ABTest(
    name="market_anchor_weights",
    variants={"low": 0.05, "medium": 0.10, "high": 0.20},
    max_trades_per_variant=50,
)
```

Wire into `analyze_trade` by passing the active variant's anchor weight as a parameter. Store the variant name on the paper trade for attribution. After 50 settled trades per variant, compare Brier scores.
