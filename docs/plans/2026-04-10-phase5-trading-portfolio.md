# Phase 5: Trading & Portfolio Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Bayesian Kelly sizing, dynamic correlation matrix, slippage modeling, partial fills, hedge ratio covariance, time-decay edge, price improvement tracking, and execution latency guard.

**Architecture:** All changes in `paper.py`, `monte_carlo.py`, `weather_markets.py`. New helper functions; existing interfaces preserved.

**Tech Stack:** Python stdlib (math, statistics, random)

**Covers:** #15, #39, #49, #50, #51, #63, #65, #73, #74, #78, #79

---

### Task 1: Bayesian Kelly fraction (#39)

**Files:**
- Modify: `weather_markets.py` — Kelly calculation

- [ ] **Step 1: Write failing test**

Add to `tests/test_trading.py` (create if not exists):

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest
import math


def test_bayesian_kelly_lower_than_point_estimate():
    """Bayesian Kelly should be <= point-estimate Kelly due to edge uncertainty."""
    from weather_markets import bayesian_kelly_fraction, kelly_fraction
    point_k = kelly_fraction(our_prob=0.70, market_prob=0.60)
    bayes_k = bayesian_kelly_fraction(our_prob=0.70, market_prob=0.60, n_predictions=5)
    assert bayes_k <= point_k, "Bayesian Kelly should be conservative vs point estimate"


def test_bayesian_kelly_converges_with_more_data():
    """With many predictions, Bayesian Kelly should approach point estimate."""
    from weather_markets import bayesian_kelly_fraction, kelly_fraction
    point_k = kelly_fraction(our_prob=0.70, market_prob=0.60)
    bayes_k_large = bayesian_kelly_fraction(our_prob=0.70, market_prob=0.60, n_predictions=1000)
    assert abs(bayes_k_large - point_k) < 0.05


def test_kelly_never_negative():
    from weather_markets import bayesian_kelly_fraction
    result = bayesian_kelly_fraction(our_prob=0.40, market_prob=0.60, n_predictions=10)
    assert result >= 0.0


def test_kelly_capped_at_quarter():
    """Kelly should be capped at 0.25 to avoid overbetting."""
    from weather_markets import bayesian_kelly_fraction
    result = bayesian_kelly_fraction(our_prob=0.99, market_prob=0.10, n_predictions=100)
    assert result <= 0.25
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_trading.py -k "kelly" -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'bayesian_kelly_fraction'`

- [ ] **Step 3: Implement bayesian_kelly_fraction() in weather_markets.py**

```python
def kelly_fraction(our_prob: float, market_prob: float) -> float:
    """
    Standard Kelly fraction for a binary market.
    f* = (p * (1/q) - (1-p)) / (1/q)  where q = market_prob (cost per contract)
    Simplified: f* = our_prob - market_prob  (for binary 0/1 payoff at market price).
    Capped at 25% of bankroll. Returns 0 if no edge.
    """
    edge = our_prob - market_prob
    if edge <= 0:
        return 0.0
    # Binary market Kelly: f = edge / (1 - market_prob) scaled by payoff
    odds = (1.0 - market_prob) / market_prob  # odds in favour
    f = (our_prob * odds - (1 - our_prob)) / odds
    return max(0.0, min(0.25, f))


def bayesian_kelly_fraction(
    our_prob: float,
    market_prob: float,
    n_predictions: int = 20,
    confidence: float = 0.90,
) -> float:
    """
    Bayesian Kelly: integrate over posterior uncertainty in our edge.

    Models our_prob as a Beta posterior: Beta(alpha, beta) where
    alpha = our_prob * n_predictions, beta = (1-our_prob) * n_predictions.
    Uses the lower confidence bound of the posterior as a conservative estimate.
    This naturally shrinks Kelly fraction when n_predictions is small.

    Args:
        our_prob:      Point estimate of P(YES)
        market_prob:   Market implied probability
        n_predictions: Number of past predictions (proxy for posterior concentration)
        confidence:    Confidence level for lower bound (default 90%)
    """
    import math

    if n_predictions < 1:
        n_predictions = 1

    # Beta posterior parameters
    alpha = our_prob * n_predictions + 1.0
    beta = (1.0 - our_prob) * n_predictions + 1.0

    # Wilson lower bound on our_prob (conservative estimate)
    z = 1.645 if confidence == 0.90 else 1.96
    p_hat = alpha / (alpha + beta)
    n = alpha + beta
    conservative_p = (
        (p_hat + z * z / (2 * n) - z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n)))
        / (1 + z * z / n)
    )
    conservative_p = max(0.0, min(1.0, conservative_p))

    return kelly_fraction(conservative_p, market_prob)
```

- [ ] **Step 4: Update Kelly calls in paper.py / weather_markets.py**

Find all calls to existing Kelly computation (grep for `kelly` in both files) and replace with `bayesian_kelly_fraction`, passing `n_predictions` from tracker if available:

```bash
grep -n "kelly\|Kelly" "C:/Users/thesa/claude kalshi/weather_markets.py" | head -20
grep -n "kelly\|Kelly" "C:/Users/thesa/claude kalshi/paper.py" | head -20
```

Replace each Kelly call with:

```python
from weather_markets import bayesian_kelly_fraction
# Get recent prediction count from tracker
try:
    from tracker import get_history
    history = get_history(city=city, limit=100)
    n_pred = len(history) if history else 20
except Exception:
    n_pred = 20

kelly_f = bayesian_kelly_fraction(our_prob=our_prob, market_prob=market_prob, n_predictions=n_pred)
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_trading.py -k "kelly" -v
python -m pytest tests/ --tb=short 2>&1 | tail -10
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add weather_markets.py paper.py tests/test_trading.py
git commit -m "feat: Bayesian Kelly fraction with posterior uncertainty shrinkage (#39)"
```

---

### Task 2: Dynamic correlation matrix from backtest (#49)

**Files:**
- Modify: `monte_carlo.py` — load correlations from tracker/backtest

- [ ] **Step 1: Write test**

Add to `tests/test_trading.py`:

```python
def test_dynamic_correlation_loads_from_data(tmp_path):
    """If backtest data exists, correlation matrix should differ from hardcoded defaults."""
    import monte_carlo
    from unittest.mock import patch

    mock_corr = {frozenset({"NYC", "Boston"}): 0.92}
    with patch("monte_carlo._load_dynamic_correlations", return_value=mock_corr):
        corr = monte_carlo.get_city_correlation("NYC", "Boston")
    assert corr == pytest.approx(0.92, abs=0.01)


def test_correlation_falls_back_to_hardcoded():
    import monte_carlo
    from unittest.mock import patch
    with patch("monte_carlo._load_dynamic_correlations", return_value=None):
        corr = monte_carlo.get_city_correlation("NYC", "Boston")
    assert 0.5 <= corr <= 1.0  # hardcoded value
```

- [ ] **Step 2: Add _load_dynamic_correlations() and get_city_correlation() to monte_carlo.py**

```python
from __future__ import annotations
import logging
from pathlib import Path

_log = logging.getLogger(__name__)

# Hardcoded fallback correlations (from paper.py _CITY_PAIR_CORR)
_HARDCODED_CORR: dict[frozenset, float] = {
    frozenset({"NYC", "Boston"}): 0.85,
    frozenset({"NYC", "Philadelphia"}): 0.80,
    frozenset({"Chicago", "Denver"}): 0.45,
    frozenset({"Chicago", "Minneapolis"}): 0.60,
    frozenset({"LA", "Phoenix"}): 0.55,
    frozenset({"LA", "San Francisco"}): 0.50,
    frozenset({"Dallas", "Atlanta"}): 0.55,
    frozenset({"Dallas", "Houston"}): 0.70,
    frozenset({"Miami", "Atlanta"}): 0.50,
}

_CORR_CACHE: dict | None = None
_CORR_CACHE_TS: float = 0.0
_CORR_CACHE_TTL = 86400  # refresh daily


def _load_dynamic_correlations() -> dict[frozenset, float] | None:
    """
    Load updated city-pair correlations from backtest walk-forward results.
    Stored in data/learned_correlations.json (updated by backtest module annually).
    Returns None if file missing or stale.
    """
    import json, time
    global _CORR_CACHE, _CORR_CACHE_TS

    if _CORR_CACHE is not None and (time.time() - _CORR_CACHE_TS) < _CORR_CACHE_TTL:
        return _CORR_CACHE

    corr_path = Path(__file__).parent / "data" / "learned_correlations.json"
    if not corr_path.exists():
        return None
    try:
        raw = json.loads(corr_path.read_text())
        result = {frozenset(pair.split("|")): float(val) for pair, val in raw.items()}
        _CORR_CACHE = result
        _CORR_CACHE_TS = time.time()
        return result
    except Exception as exc:
        _log.warning("Could not load dynamic correlations: %s", exc)
        return None


def get_city_correlation(city_a: str, city_b: str) -> float:
    """Return correlation between city_a and city_b. Tries dynamic, falls back to hardcoded."""
    pair = frozenset({city_a, city_b})
    dynamic = _load_dynamic_correlations()
    if dynamic and pair in dynamic:
        return dynamic[pair]
    return _HARDCODED_CORR.get(pair, 0.3)  # default low correlation if unknown
```

- [ ] **Step 3: Use get_city_correlation() in portfolio Kelly simulation**

In `monte_carlo.py`, replace direct dict lookups with `get_city_correlation(city_a, city_b)`.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_trading.py -k "correlation" -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add monte_carlo.py tests/test_trading.py
git commit -m "feat: dynamic correlation matrix from learned_correlations.json (#49)"
```

---

### Task 3: Slippage model for large orders (#50)

**Files:**
- Modify: `paper.py` — `place_paper_order()`, `_check_exit_targets()`

- [ ] **Step 1: Write test**

Add to `tests/test_trading.py`:

```python
def test_slippage_increases_with_quantity():
    from paper import estimate_slippage
    slip_small = estimate_slippage(quantity=1, market_prob=0.60)
    slip_large = estimate_slippage(quantity=100, market_prob=0.60)
    assert slip_large > slip_small, "Larger orders should have more slippage"


def test_slippage_zero_for_tiny_order():
    from paper import estimate_slippage
    slip = estimate_slippage(quantity=1, market_prob=0.60)
    assert slip >= 0.0
    assert slip < 0.02  # should be < 2 cents for 1 contract
```

- [ ] **Step 2: Implement estimate_slippage() in paper.py**

```python
def estimate_slippage(quantity: float, market_prob: float, depth_scale: float = 50.0) -> float:
    """
    Estimate price slippage for an order of `quantity` contracts.
    Models market depth as depth_scale contracts at mid-price.
    Each additional contract beyond depth_scale moves price by 1 tick (0.01).

    Args:
        quantity:    Number of contracts
        market_prob: Current mid-price probability
        depth_scale: Assumed market depth in contracts

    Returns:
        Slippage in probability points (e.g. 0.02 = 2 cents per contract)
    """
    if quantity <= depth_scale:
        return 0.0
    excess = quantity - depth_scale
    # Linear price impact beyond depth
    slip = (excess / depth_scale) * 0.01
    # Cap at 5 cents
    return min(slip, 0.05)
```

- [ ] **Step 3: Apply slippage in place_paper_order()**

In `paper.py` `place_paper_order` (or equivalent), after determining entry price:

```python
slip = estimate_slippage(quantity=quantity, market_prob=entry_price)
# For buys: we pay more (slippage against us)
actual_entry = entry_price + slip
_log.debug("Slippage %.4f on %d contracts: entry %.4f → %.4f", slip, quantity, entry_price, actual_entry)
```

- [ ] **Step 4: Apply slippage to exit targets (#78)**

In `_check_exit_targets()` in `paper.py`:

```python
# When checking if we can exit, account for slippage
position_qty = trade.get("quantity", 1)
exit_slip = estimate_slippage(quantity=position_qty, market_prob=current_price)
effective_exit_price = current_price - exit_slip  # slippage against us on exit too
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_trading.py -k "slippage" -v
python -m pytest tests/ --tb=short 2>&1 | tail -10
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add paper.py tests/test_trading.py
git commit -m "feat: slippage model for large orders, applied at entry and exit (#50, #78)"
```

---

### Task 4: Time-decay edge toward close (#63)

**Files:**
- Modify: `weather_markets.py` — `analyze_trade()`

- [ ] **Step 1: Write test**

Add to `tests/test_trading.py`:

```python
def test_time_decay_reduces_edge_near_close():
    from weather_markets import time_decay_edge
    from datetime import datetime, timezone, timedelta

    close_time = datetime.now(timezone.utc) + timedelta(hours=2)
    edge_now = time_decay_edge(raw_edge=0.10, close_time=close_time)

    close_time_far = datetime.now(timezone.utc) + timedelta(hours=48)
    edge_far = time_decay_edge(raw_edge=0.10, close_time=close_time_far)

    assert edge_far > edge_now, "Edge should decay as close_time approaches"


def test_time_decay_zero_at_close():
    from weather_markets import time_decay_edge
    from datetime import datetime, timezone, timedelta

    close_time = datetime.now(timezone.utc) - timedelta(minutes=1)  # already closed
    edge = time_decay_edge(raw_edge=0.10, close_time=close_time)
    assert edge == pytest.approx(0.0, abs=0.001)
```

- [ ] **Step 2: Implement time_decay_edge() in weather_markets.py**

```python
def time_decay_edge(raw_edge: float, close_time: "datetime", reference_hours: float = 48.0) -> float:
    """
    Scale edge linearly toward 0 as market approaches close_time.
    At reference_hours before close: full edge.
    At close: zero edge (market has fully priced in available information).

    Args:
        raw_edge:        Edge computed from forecast vs market prob
        close_time:      Market settlement datetime (UTC-aware)
        reference_hours: Hours before close at which edge is fully realized
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    hours_left = (close_time - now).total_seconds() / 3600
    if hours_left <= 0:
        return 0.0
    decay = min(1.0, hours_left / reference_hours)
    return raw_edge * decay
```

- [ ] **Step 3: Apply in analyze_trade()**

In `analyze_trade`, after computing `edge = our_prob - market_prob`, add:

```python
if close_time:
    try:
        from datetime import datetime, timezone
        ct = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
        edge = time_decay_edge(raw_edge=edge, close_time=ct)
    except Exception:
        pass
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_trading.py -k "time_decay" -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add weather_markets.py tests/test_trading.py
git commit -m "feat: time-decay edge scaling to zero at market close (#63)"
```

---

### Task 5: Price improvement tracking (#65)

**Files:**
- Modify: `paper.py` — log desired vs actual fill price
- Modify: `tracker.py` — add price_improvement table

- [ ] **Step 1: Add price_improvement table migration**

Add to `_MIGRATIONS` in `tracker.py`:

```python
# v5: price improvement tracking
"""CREATE TABLE IF NOT EXISTS price_improvement (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT NOT NULL,
    desired_price REAL NOT NULL,
    actual_price  REAL NOT NULL,
    improvement   REAL NOT NULL,
    quantity      REAL,
    side          TEXT,
    logged_at     TEXT NOT NULL
)""",
```

Increment `_SCHEMA_VERSION = 5`.

Add function:

```python
def log_price_improvement(ticker: str, desired: float, actual: float,
                           quantity: float, side: str) -> None:
    """Record desired vs actual fill price to measure execution quality."""
    improvement = desired - actual if side == "yes" else actual - desired
    try:
        with _conn() as con:
            con.execute(
                "INSERT INTO price_improvement (ticker, desired_price, actual_price, improvement, quantity, side, logged_at) VALUES (?,?,?,?,?,?,?)",
                (ticker, desired, actual, improvement, quantity, side,
                 datetime.now(UTC).isoformat()),
            )
    except Exception as exc:
        _log.warning("Failed to log price improvement: %s", exc)


def get_price_improvement_stats() -> dict | None:
    """Return mean/median price improvement across all logged fills."""
    import statistics
    with _conn() as con:
        rows = con.execute("SELECT improvement FROM price_improvement").fetchall()
    if len(rows) < 5:
        return None
    vals = [r["improvement"] for r in rows]
    return {
        "mean": statistics.mean(vals),
        "median": statistics.median(vals),
        "count": len(vals),
        "positive_pct": sum(1 for v in vals if v > 0) / len(vals),
    }
```

- [ ] **Step 2: Call log_price_improvement in paper.py**

In `place_paper_order`, after fill is simulated:

```python
from tracker import log_price_improvement
desired_price = entry_price  # what we wanted
actual_price = entry_price + slip  # what we got (with slippage)
log_price_improvement(
    ticker=ticker,
    desired=desired_price,
    actual=actual_price,
    quantity=quantity,
    side=side,
)
```

- [ ] **Step 3: Write test**

Add to `tests/test_trading.py`:

```python
def test_log_price_improvement(tmp_path):
    import tracker
    orig = tracker.DB_PATH
    tracker.DB_PATH = tmp_path / "pi_test.db"
    tracker._db_initialized = False
    tracker.init_db()

    tracker.log_price_improvement("TICKER1", desired=0.60, actual=0.61, quantity=5, side="yes")
    tracker.log_price_improvement("TICKER2", desired=0.60, actual=0.59, quantity=3, side="yes")

    with tracker._conn() as con:
        rows = con.execute("SELECT * FROM price_improvement").fetchall()
    assert len(rows) == 2

    tracker.DB_PATH = orig
    tracker._db_initialized = False
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_trading.py -k "price_improvement" -v
python -m pytest tests/ --tb=short 2>&1 | tail -10
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add tracker.py paper.py tests/test_trading.py
git commit -m "feat: price improvement tracking — log desired vs actual fill price (#65)"
```

---

### Task 6: Partial fills simulation (#73, #74)

**Files:**
- Modify: `paper.py` — simulate partial fills

- [ ] **Step 1: Write test**

Add to `tests/test_trading.py`:

```python
def test_simulate_partial_fill_large_order():
    from paper import simulate_fill
    # Large order in thin market should partially fill
    filled, avg_price = simulate_fill(
        quantity=200, market_prob=0.60, volume=100, side="yes"
    )
    assert filled < 200, "Should not fully fill 200-contract order in 100-volume market"
    assert filled >= 1


def test_simulate_partial_fill_small_order():
    from paper import simulate_fill
    # Small order in deep market should fully fill
    filled, avg_price = simulate_fill(
        quantity=5, market_prob=0.60, volume=1000, side="yes"
    )
    assert filled == 5
```

- [ ] **Step 2: Implement simulate_fill() in paper.py**

```python
import random


def simulate_fill(
    quantity: float,
    market_prob: float,
    volume: float = 500,
    side: str = "yes",
    fill_uncertainty: float = 0.1,
) -> tuple[float, float]:
    """
    Simulate a fill for `quantity` contracts given market volume.
    Returns (filled_quantity, average_fill_price).

    Models:
      - If quantity <= 20% of volume: full fill at market + tiny noise
      - If quantity > 20% of volume: partial fill (50-90% of order)
      - Slippage increases with fill size
    """
    max_fillable = volume * 0.20
    if quantity <= max_fillable:
        filled = quantity
    else:
        # Partial fill: random between 50% and 90% of order
        fill_frac = random.uniform(0.50, 0.90)
        filled = round(quantity * fill_frac)

    slip = estimate_slippage(quantity=filled, market_prob=market_prob)
    noise = random.gauss(0, fill_uncertainty * 0.01)
    avg_price = market_prob + slip + noise
    avg_price = max(0.01, min(0.99, avg_price))

    return filled, avg_price
```

- [ ] **Step 3: Integrate into place_paper_order()**

Replace the current all-or-nothing fill logic with `simulate_fill`:

```python
filled_qty, fill_price = simulate_fill(
    quantity=quantity,
    market_prob=entry_price,
    volume=market.get("volume", 500),
    side=side,
)
if filled_qty < quantity:
    _log.info("Partial fill: %d/%d contracts at %.4f", filled_qty, quantity, fill_price)
quantity = filled_qty
entry_price = fill_price
```

- [ ] **Step 4: Add max execution latency guard (#79)**

In `place_paper_order`, add:

```python
import time
MAX_EXECUTION_LATENCY_S = float(os.getenv("MAX_EXECUTION_LATENCY_S", "10"))

t0 = time.monotonic()
# ... fill simulation ...
elapsed = time.monotonic() - t0
if elapsed > MAX_EXECUTION_LATENCY_S:
    _log.warning("Order latency %.1fs exceeds max %.1fs — abandoning", elapsed, MAX_EXECUTION_LATENCY_S)
    return None  # abort the order
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_trading.py -v
python -m pytest tests/ --tb=short 2>&1 | tail -10
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add paper.py tests/test_trading.py
git commit -m "feat: partial fill simulation, max execution latency guard (#73, #74, #79)"
```

---

### Task 7: PnL with variable fill prices (#15)

**Files:**
- Modify: `paper.py` — `_calc_pnl()` uses actual fill price

- [ ] **Step 1: Write test**

Add to `tests/test_trading.py`:

```python
def test_pnl_uses_actual_fill_price():
    """PnL should reflect actual fill price, not desired entry price."""
    from paper import calc_trade_pnl

    trade = {
        "ticker": "T1",
        "side": "yes",
        "quantity": 10,
        "entry_price": 0.60,
        "actual_fill_price": 0.62,  # slippage paid
        "settled_yes": True,
    }
    pnl = calc_trade_pnl(trade)
    # Won: (1.00 - 0.62) * 10 contracts - fees
    expected = (1.00 - 0.62) * 10
    assert pnl == pytest.approx(expected, abs=0.10)
```

- [ ] **Step 2: Add calc_trade_pnl() to paper.py**

```python
def calc_trade_pnl(trade: dict) -> float:
    """
    Compute realized PnL for a settled trade using actual_fill_price if available.
    Falls back to entry_price for backwards compatibility.

    P&L for YES win:  (1.00 - fill_price) * quantity
    P&L for YES loss: (-fill_price) * quantity
    P&L for NO win:   (1.00 - fill_price) * quantity  (where fill_price = cost of NO)
    """
    fill_price = trade.get("actual_fill_price") or trade.get("entry_price", 0)
    quantity = trade.get("quantity", 1)
    side = trade.get("side", "yes")
    settled_yes = trade.get("settled_yes")

    if settled_yes is None:
        return 0.0

    if side == "yes":
        if settled_yes:
            return (1.0 - fill_price) * quantity
        else:
            return -fill_price * quantity
    else:  # NO position
        if not settled_yes:
            return (1.0 - fill_price) * quantity
        else:
            return -fill_price * quantity
```

- [ ] **Step 3: Store actual_fill_price in trade records**

In `place_paper_order`, store `actual_fill_price` in the trade dict:

```python
trade = {
    ...
    "entry_price": desired_price,       # original desired price
    "actual_fill_price": fill_price,    # actual filled price (includes slippage)
    ...
}
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_trading.py -v
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add paper.py tests/test_trading.py
git commit -m "feat: PnL calculated from actual fill price, not desired entry (#15)"
```
