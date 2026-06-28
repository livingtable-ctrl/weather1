# Category B: Risk Management — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strengthen the risk layer with per-trade drawdown re-checks, break-even stop-loss, bimodal Kelly reduction, portfolio expected value tracking, and overnight gap protection.

**Architecture:** All changes are localized to `order_executor.py`, `paper.py`, and `weather_markets.py`. B1 (per-trade drawdown check) and B5 (break-even stop-loss) are the highest priority — implement in that order. B4 (marginal Kelly) is the most complex and should be deferred post-graduation.

**Tech Stack:** Python 3.14, SQLite, pytest.

**Implementation Order:** B1 → B5 → B7 → B3 → B2 → B6 → B4

---

## B1: Per-Trade Drawdown Re-check

**Problem:** The drawdown tier and HALT check run once at the start of the cron cycle. If the bot places 4 trades that collectively drop the balance below the HALT floor (80% of peak), the fifth trade is still placed before the next cron cycle detects the breach.

**Files:**
- Modify: `order_executor.py` — re-check `is_paused_drawdown()` before each individual `place_paper_order` / `_place_live_order` call
- Test: `tests/test_drawdown_tiers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drawdown_tiers.py — add this
def test_no_trades_placed_when_drawdown_breached_mid_cycle(monkeypatch):
    """If balance drops below HALT mid-cycle, _auto_place_trades must stop.

    Calls order_executor._auto_place_trades directly — the only correct way
    to test this guard. A test that reimplements the loop would always pass
    regardless of whether the guard exists in the real function.
    """
    import paper
    import order_executor as oe

    placed = []

    def mock_place(ticker, side, qty, entry_price, **kwargs):
        # First placement succeeds; then simulate balance crashing below HALT
        placed.append(ticker)
        if len(placed) == 1:
            monkeypatch.setattr(paper, "is_paused_drawdown", lambda: True)
        return {"ticker": ticker, "side": side, "settled": False, "pnl": 0}

    monkeypatch.setattr(paper, "place_paper_order", mock_place)
    monkeypatch.setattr(paper, "is_paused_drawdown", lambda: False)

    signals = [
        {"ticker": "KXHIGH-A", "side": "yes", "qty": 1, "entry_price": 0.55,
         "net_edge": 0.15, "days_out": 1},
        {"ticker": "KXHIGH-B", "side": "yes", "qty": 1, "entry_price": 0.55,
         "net_edge": 0.15, "days_out": 1},
    ]

    result = oe._auto_place_trades(signals, client=None)

    assert len(placed) == 1, (
        f"Expected 1 trade placed, got {len(placed)}: {placed}. "
        "The per-trade drawdown guard must call is_paused_drawdown() before each order."
    )
    assert len(result) == 1, "Return value must reflect only successfully placed trades"
```

- [ ] **Step 2: Run to confirm it fails**

```
pytest tests/test_drawdown_tiers.py::test_no_trades_placed_when_drawdown_breached_mid_cycle -v
```
Expected: `AttributeError: module 'order_executor' has no attribute '_auto_place_trades'` OR the test fails with `AssertionError: Expected 1 trade placed, got 2` if the function exists but lacks the guard.

```
pytest tests/test_drawdown_tiers.py::test_no_trades_placed_when_drawdown_breached_mid_cycle -v
```

- [ ] **Step 3: Add the per-trade guard in `order_executor.py`**

Find `_auto_place_trades()` in `order_executor.py`. Before the `place_paper_order` or `_place_live_order` call in the signal loop, add:

```python
def _auto_place_trades(signals: list[dict], client=None, **kwargs) -> list[dict]:
    """Place paper or live orders for approved signals.

    Re-checks drawdown status before each individual order to prevent
    placing trades when the balance breaches the HALT floor mid-cycle.
    """
    from paper import is_paused_drawdown
    placed = []
    for signal in signals:
        # Per-trade drawdown gate — re-evaluated each iteration
        if is_paused_drawdown():
            import logging
            logging.getLogger("main").warning(
                "auto_place_trades: HALT — drawdown floor breached mid-cycle, "
                "stopping after %d placements", len(placed)
            )
            break
        # ... existing placement logic ...
        result = place_paper_order(
            signal["ticker"],
            signal.get("side", "yes"),
            signal.get("qty", 1),
            signal.get("entry_price", 0.5),
            **{k: v for k, v in signal.items() if k not in ("ticker", "side", "qty", "entry_price")},
        )
        if result:
            placed.append(result)
    return placed
```

- [ ] **Step 4: Run the full drawdown test file**

```
pytest tests/test_drawdown_tiers.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```
git add order_executor.py tests/test_drawdown_tiers.py
git commit -m "fix(risk): re-check drawdown HALT before each individual trade placement"
```

---

## B5: Break-Even Stop-Loss

**Status: ALREADY IMPLEMENTED AND WIRED.** `paper.check_breakeven_stops()` exists at `paper.py:1171` and is called from `cron.py:1787` every cron cycle. `paper.update_peak_profits()` tracks running peaks at `cron.py:1760`. This item needs **tests only** — no new implementation.

**What exists:**
- `paper.update_peak_profits(open_trades, current_yes_prices)` — updates `peak_profit_pct` on each trade each cycle
- `paper.check_breakeven_stops(open_trades, current_yes_prices)` — fires when `peak_profit_pct >= BREAKEVEN_TRIGGER_PCT` AND unrealized PnL has fallen back to ≤ 0
- `BREAKEVEN_TRIGGER_PCT` is read from `utils.py` via `os.getenv("BREAKEVEN_TRIGGER_PCT", "0.30")`
- Wired in `cron.py` at lines ~1760 and ~1787

**Files:**
- Read: `paper.py:1137–1222` — both functions exist
- Test: `tests/test_early_exits.py`

- [ ] **Step 1: Write tests for the existing `check_breakeven_stops`**

```python
# tests/test_early_exits.py — add
def test_check_breakeven_stops_fires_when_peak_met_and_price_falls(monkeypatch):
    """check_breakeven_stops must return the ticker when peak was met and price fell back."""
    import paper
    from utils import BREAKEVEN_TRIGGER_PCT

    far_future = "2099-01-01T00:00:00+00:00"  # well outside the 24h settlement gate
    trade = {
        "ticker": "KXHIGH-T70",
        "side": "yes",
        "entry_price": 0.50,
        "quantity": 10,
        "settled": False,
        "won": None,
        "peak_profit_pct": BREAKEVEN_TRIGGER_PCT + 0.01,  # peak was hit
        "close_time": far_future,
    }

    # Price has now fallen back below entry (0.48 < 0.50)
    exits = paper.check_breakeven_stops([trade], current_yes_prices={"KXHIGH-T70": 0.48})
    assert "KXHIGH-T70" in exits, (
        f"check_breakeven_stops should fire when price falls below entry. Got: {exits}"
    )


def test_check_breakeven_stops_silent_before_peak_is_met(monkeypatch):
    """check_breakeven_stops must NOT fire when peak_profit_pct is below the trigger."""
    import paper
    from utils import BREAKEVEN_TRIGGER_PCT

    far_future = "2099-01-01T00:00:00+00:00"
    trade = {
        "ticker": "KXHIGH-T70",
        "side": "yes",
        "entry_price": 0.50,
        "quantity": 10,
        "settled": False,
        "won": None,
        "peak_profit_pct": BREAKEVEN_TRIGGER_PCT - 0.05,  # below trigger
        "close_time": far_future,
    }

    exits = paper.check_breakeven_stops([trade], current_yes_prices={"KXHIGH-T70": 0.40})
    assert exits == [], f"Should not fire when peak not yet met. Got: {exits}"


def test_update_peak_profits_sets_peak_on_new_high(monkeypatch, tmp_path):
    """update_peak_profits must record a new peak when unrealized profit exceeds stored peak."""
    import paper
    monkeypatch.setattr(paper, "DB_PATH", tmp_path / "test_paper.json")

    # Stub _load / _save to avoid file I/O
    trade = {
        "ticker": "KXHIGH-T70",
        "side": "yes",
        "entry_price": 0.50,
        "quantity": 10,
        "cost": 5.00,
        "settled": False,
        "peak_profit_pct": None,
    }

    class _FakeData(dict):
        pass
    fake_data = _FakeData(trades=[trade], balance=1000.0)
    monkeypatch.setattr(paper, "_load", lambda: fake_data)
    saved = []
    monkeypatch.setattr(paper, "_save", lambda d: saved.append(d))

    # yes_ask = 0.65 → unrealized_profit = (0.65 - 0.50) * 10 / 5.00 = 0.30 (30%)
    paper.update_peak_profits([trade], current_yes_prices={"KXHIGH-T70": 0.65})

    assert saved, "update_peak_profits must call _save when a new peak is found"
    updated_trade = saved[0]["trades"][0]
    assert updated_trade["peak_profit_pct"] == pytest.approx(0.30, abs=0.01), (
        f"Expected peak_profit_pct ≈ 0.30, got {updated_trade.get('peak_profit_pct')}"
    )
```

- [ ] **Step 2: Run the tests**

```
pytest tests/test_early_exits.py -k "breakeven or peak_profit" -v
```
Expected: all PASS (these test existing code)

- [ ] **Step 3: Commit**

```
git add tests/test_early_exits.py
git commit -m "test(risk): add coverage for existing check_breakeven_stops and update_peak_profits"
```

---

## B7: Overnight GFS Gap Protection

**Problem:** GFS model runs update at 00Z, 06Z, 12Z, 18Z UTC. Within 90 minutes after each update, the new model run is ingesting observations but has not yet been fully published to Open-Meteo. Placing new multi-day trades during this window uses stale model output.

**Files:**
- Modify: `order_executor.py` — add `_in_gfs_update_window()` guard before new trade placement
- Test: `tests/test_execution_stability.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_execution_stability.py — add
def test_gfs_update_window_blocks_new_trades(monkeypatch):
    from order_executor import _in_gfs_update_window
    from datetime import datetime, timezone

    # 00:30 UTC — within 90 min of 00Z → should be blocked
    t_blocked = datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc)
    assert _in_gfs_update_window(now_utc=t_blocked) is True

    # 02:00 UTC — 90+ minutes after 00Z → clear
    t_clear = datetime(2026, 7, 1, 2, 0, tzinfo=timezone.utc)
    assert _in_gfs_update_window(now_utc=t_clear) is False

    # 12:45 UTC — within 90 min of 12Z → blocked
    t_blocked2 = datetime(2026, 7, 1, 12, 45, tzinfo=timezone.utc)
    assert _in_gfs_update_window(now_utc=t_blocked2) is True
```

- [ ] **Step 2: Add `_in_gfs_update_window()` to `order_executor.py`**

```python
_GFS_UPDATE_HOURS_UTC = [0, 6, 12, 18]   # GFS model initialization hours
_GFS_UPDATE_LOCKOUT_MINS = int(os.getenv("GFS_LOCKOUT_MINS", "90"))


def _in_gfs_update_window(now_utc=None) -> bool:
    """Return True if we are within LOCKOUT_MINS of a GFS model initialization.

    During this window, Open-Meteo may be serving the previous model run.
    New multi-day trades should wait for the new run to propagate (~90 min).
    Same-day trades using METAR lock-in are unaffected and skip this check.
    """
    if _GFS_UPDATE_LOCKOUT_MINS <= 0:
        return False
    if now_utc is None:
        now_utc = datetime.now(UTC)
    minute_of_day = now_utc.hour * 60 + now_utc.minute
    for update_hour in _GFS_UPDATE_HOURS_UTC:
        update_minute = update_hour * 60
        if 0 <= (minute_of_day - update_minute) < _GFS_UPDATE_LOCKOUT_MINS:
            return True
    return False
```

- [ ] **Step 3: Add the guard in `_auto_place_trades` for multi-day signals**

In `_auto_place_trades`, before placing a signal with `days_out >= 1`:

```python
if signal.get("days_out", 1) >= 1 and _in_gfs_update_window():
    _log.info(
        "auto_place_trades: skipping %s — GFS update window active (set GFS_LOCKOUT_MINS=0 to disable)",
        signal.get("ticker", "?"),
    )
    continue
```

- [ ] **Step 4: Run the test**

```
pytest tests/test_execution_stability.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```
git add order_executor.py tests/test_execution_stability.py
git commit -m "feat(risk): block multi-day trade placement during 90-min GFS model update window"
```

---

## B3: Portfolio Expected Value Card

**Problem:** No live metric shows the sum of (position_size × model_edge) for all open trades. This tells the operator immediately how much the model thinks open positions are worth above cost.

**Files:**
- Modify: `paper.py` — add `get_portfolio_expected_value()` function
- Modify: `web_app.py` — expose via `/api/status` or new `/api/portfolio-ev`
- Test: `tests/test_paper.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_paper.py — add
def test_portfolio_expected_value_positive_for_winning_trades(monkeypatch):
    import paper

    trades = [
        {"ticker": "T1", "side": "yes", "entry_price": 0.50, "qty": 10, "net_edge": 0.15, "settled": False, "won": None},
        {"ticker": "T2", "side": "yes", "entry_price": 0.55, "qty": 5,  "net_edge": 0.20, "settled": False, "won": None},
    ]
    monkeypatch.setattr(paper, "load_paper_trades", lambda: trades)

    ev = paper.get_portfolio_expected_value()
    # T1: cost=10*0.50=$5.00, EV=cost*(1+edge)=$5.75 → profit=$0.75
    # T2: cost=5*0.55=$2.75, EV=cost*(1+edge)=$3.30 → profit=$0.55
    expected_total_profit = 0.75 + 0.55
    assert abs(ev["expected_profit_dollars"] - expected_total_profit) < 0.01
    assert ev["open_position_count"] == 2
```

- [ ] **Step 2: Add `get_portfolio_expected_value()` to `paper.py`**

```python
def get_portfolio_expected_value() -> dict:
    """Return the sum of expected profit across all open positions.

    expected_profit_per_trade = cost * net_edge
    where cost = entry_price * qty (for YES) or (1 - entry_price) * qty (for NO).

    Returns:
        {
            "expected_profit_dollars": float,
            "total_cost_dollars": float,
            "open_position_count": int,
            "expected_roi_pct": float,
        }
    """
    trades = load_paper_trades()
    open_trades = [
        t for t in trades if not t.get("settled") and t.get("won") is None
    ]

    total_cost = 0.0
    total_ev = 0.0
    for t in open_trades:
        side = t.get("side", "yes")
        entry = float(t.get("entry_price", 0.5))
        qty = int(t.get("qty", 1))
        edge = float(t.get("net_edge", 0.0))

        if side == "yes":
            cost = entry * qty
        else:
            cost = (1.0 - entry) * qty

        total_cost += cost
        total_ev += cost * edge  # expected profit above cost

    roi_pct = (total_ev / total_cost * 100.0) if total_cost > 0 else 0.0

    return {
        "expected_profit_dollars": round(total_ev, 2),
        "total_cost_dollars": round(total_cost, 2),
        "open_position_count": len(open_trades),
        "expected_roi_pct": round(roi_pct, 2),
    }
```

- [ ] **Step 3: Expose via `/api/status` in `web_app.py`**

Find the `/api/status` endpoint in `web_app.py` and add to its response dict:

```python
from paper import get_portfolio_expected_value
_ev = get_portfolio_expected_value()
# Add to the status response:
"portfolio_ev": _ev["expected_profit_dollars"],
"portfolio_ev_roi_pct": _ev["expected_roi_pct"],
"portfolio_cost": _ev["total_cost_dollars"],
```

- [ ] **Step 4: Run the test**

```
pytest tests/test_paper.py::test_portfolio_expected_value_positive_for_winning_trades -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```
git add paper.py web_app.py tests/test_paper.py
git commit -m "feat(analytics): add portfolio expected value metric (sum of cost × net_edge for open positions)"
```

---

## B2: Dynamic Correlation Matrix in Monte Carlo

**Problem:** `monte_carlo.py` uses static pairwise correlations from `data/correlations.json` (backtest-derived). Temperature correlations between cities spike in extreme weather regimes (heat domes produce high cross-city correlation). Static correlations understate tail risk.

**Files:**
- Modify: `tracker.py` — add `get_recent_city_correlations(days=60)`
- Modify: `monte_carlo.py` — use dynamic correlations when sufficient data exists
- Test: `tests/test_p9_p10.py`

- [ ] **Step 1: Add `get_recent_city_correlations()` to `tracker.py`**

```python
def get_recent_city_correlations(days: int = 60, min_pairs: int = 5) -> dict:
    """Compute pairwise city temperature correlations from recent settled outcomes.

    Returns {(city_a, city_b): correlation_coefficient} for pairs with enough data.
    Falls back to empty dict when insufficient data.
    """
    import math
    init_db()
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.city, o.settled_temp_f, o.settled_at
            FROM   multiday_predictions p
            JOIN   outcomes o ON o.ticker = p.ticker
            WHERE  o.settled_at >= ?
              AND  o.settled_temp_f IS NOT NULL
              AND  p.city IS NOT NULL
            """,
            (cutoff,),
        ).fetchall()

    # Group by date, then city
    from collections import defaultdict
    by_date: dict[str, dict[str, float]] = defaultdict(dict)
    for city, temp, settled_at in rows:
        date_str = str(settled_at)[:10]
        by_date[date_str][city] = float(temp)

    # Compute correlations for city pairs appearing on same dates
    city_data: dict[str, list[float]] = defaultdict(list)
    date_index: dict[str, list[str]] = defaultdict(list)
    for date_str, city_temps in sorted(by_date.items()):
        for city, temp in city_temps.items():
            city_data[city].append(temp)
            date_index[city].append(date_str)

    cities = list(city_data.keys())
    correlations = {}
    for i, c1 in enumerate(cities):
        for c2 in cities[i + 1:]:
            # Find common dates
            dates1 = set(date_index[c1])
            dates2 = set(date_index[c2])
            common = sorted(dates1 & dates2)
            if len(common) < min_pairs:
                continue
            v1 = [city_data[c1][date_index[c1].index(d)] for d in common]
            v2 = [city_data[c2][date_index[c2].index(d)] for d in common]
            # Pearson correlation
            n = len(v1)
            mx = sum(v1) / n
            my = sum(v2) / n
            num = sum((a - mx) * (b - my) for a, b in zip(v1, v2))
            d1 = math.sqrt(sum((a - mx) ** 2 for a in v1))
            d2 = math.sqrt(sum((b - my) ** 2 for b in v2))
            if d1 > 0 and d2 > 0:
                correlations[(c1, c2)] = round(num / (d1 * d2), 3)
    return correlations
```

- [ ] **Step 2: Update `monte_carlo.py` to prefer dynamic correlations**

In the `run_monte_carlo()` or equivalent function, add:

```python
from tracker import get_recent_city_correlations
dynamic_corr = get_recent_city_correlations(days=60)
if len(dynamic_corr) >= 3:
    # Merge dynamic over static defaults
    for (c1, c2), corr in dynamic_corr.items():
        _DEFAULT_CORRELATIONS[(c1, c2)] = corr
        _DEFAULT_CORRELATIONS[(c2, c1)] = corr
```

- [ ] **Step 3: Commit**

```
git add tracker.py monte_carlo.py
git commit -m "feat(risk): dynamic city temperature correlations in Monte Carlo VaR"
```

---

## B6: Tail-Risk Stress Testing

**Problem:** No scenario tests exist for "5 cities simultaneously wrong" — the extreme loss scenario that could hit the HALT floor in a single settlement window.

**Files:**
- Modify: `monte_carlo.py` — add `run_stress_test(scenario="heat_wave_failure")`
- Modify: `web_app.py` — expose `/api/stress-test` endpoint
- Test: `tests/test_p9_p10.py`

- [ ] **Step 1: Add `run_stress_test()` to `monte_carlo.py`**

```python
_STRESS_SCENARIOS = {
    "heat_wave_failure": {
        "description": "All southern cities' NO-above bets lose simultaneously (heat wave materializes)",
        "cities": ["Dallas", "Houston", "Phoenix", "Atlanta", "Austin"],
        "assumed_loss_per_position_pct": 1.00,  # full loss
    },
    "cold_snap_failure": {
        "description": "All northern cities' NO-below bets lose simultaneously",
        "cities": ["Chicago", "Minneapolis", "NYC", "Boston", "Denver"],
        "assumed_loss_per_position_pct": 1.00,
    },
    "total_model_failure": {
        "description": "All open positions lose (worst case)",
        "cities": None,  # all cities
        "assumed_loss_per_position_pct": 1.00,
    },
}


def run_stress_test(scenario: str = "heat_wave_failure") -> dict:
    """Compute worst-case P&L under a named stress scenario.

    Returns {scenario, description, loss_dollars, pct_of_balance, below_halt}.
    """
    from paper import load_paper_trades, get_balance, get_peak_balance
    import utils

    cfg = _STRESS_SCENARIOS.get(scenario)
    if not cfg:
        return {"error": f"Unknown scenario: {scenario}"}

    trades = [t for t in load_paper_trades() if not t.get("settled") and t.get("won") is None]
    if cfg["cities"] is not None:
        trades = [t for t in trades if t.get("city", "").lower() in
                  [c.lower() for c in cfg["cities"]]]

    total_loss = 0.0
    for t in trades:
        side = t.get("side", "yes")
        entry = float(t.get("entry_price", 0.5))
        qty = int(t.get("qty", 1))
        cost = (entry if side == "yes" else 1.0 - entry) * qty
        total_loss += cost * cfg["assumed_loss_per_position_pct"]

    balance = get_balance()
    peak = get_peak_balance()
    halt_floor = peak * (1.0 - utils.DRAWDOWN_HALT_PCT)

    return {
        "scenario": scenario,
        "description": cfg["description"],
        "positions_affected": len(trades),
        "loss_dollars": round(total_loss, 2),
        "balance_after": round(balance - total_loss, 2),
        "pct_of_balance": round(total_loss / balance * 100, 1) if balance > 0 else 0,
        "below_halt": (balance - total_loss) < halt_floor,
        "halt_floor": round(halt_floor, 2),
    }
```

- [ ] **Step 2: Expose via Flask**

In `web_app.py`, add:

```python
@_app.route("/api/stress-test")
@_require_auth
def api_stress_test():
    from monte_carlo import run_stress_test
    return {
        "heat_wave": run_stress_test("heat_wave_failure"),
        "cold_snap": run_stress_test("cold_snap_failure"),
        "total": run_stress_test("total_model_failure"),
    }
```

- [ ] **Step 3: Commit**

```
git add monte_carlo.py web_app.py
git commit -m "feat(risk): tail-risk stress test scenarios (heat wave, cold snap, total failure)"
```

---

## B4: Marginal Kelly (Portfolio-Level Covariance)

*Defer post-graduation — requires 100+ settled cross-city pairs for reliable correlation estimates.*

**Concept:** True portfolio Kelly computes the full covariance matrix Σ of all open position payoffs, then finds the position vector f that maximizes E[log(1 + f·r)] subject to the existing portfolio. This requires solving a quadratic program per proposed trade.

**Prerequisites:**
- `get_recent_city_correlations()` (from B2) must be live and accumulating data
- 100+ settled multi-city pairs for reliable Pearson correlations

**When ready:**
- Use `scipy.optimize.minimize` with SLSQP method to solve the portfolio Kelly frontier
- Integrate as a gate on Kelly fraction: if marginal_kelly < 0.05, skip the trade
- Add to `order_executor.py` as `_compute_marginal_kelly(signal, open_positions, corr_matrix)`

*No implementation code provided — write this plan when B2 has 60+ days of data.*
