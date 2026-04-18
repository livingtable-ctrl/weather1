# Score Improvement Plan — 2026-04-17

**Branch:** `debug/full-program-fixes` (or new branch per phase)
**Baseline scores:** Architecture 9, Risk 8.5, Tests 8, ML/Forecasting 7.5, Signal Quality 7, Live Readiness 6
**Target scores:**   Architecture 9.5, Risk 9.5, Tests 9, ML/Forecasting 9, Signal Quality 8.5, Live Readiness 8

Ordered by impact-to-effort. Each section is self-contained — tasks can be implemented independently.

---

## Phase 1 — Replace open_meteo_ensemble with a reliable alternative (ML/Forecasting 7.5→8.5)

**Why first:** Open-Meteo is rate-limiting us — this is on their end and not fixable. The circuit will stay OPEN indefinitely. We need a replacement ensemble source, not a fix.

**Situation:** Open-Meteo's free tier has become unreliable for repeated ensemble queries at our scan volume (295 markets × 30 city/date pairs per run). The circuit trips to protect the bot, but there's nothing to recover to.

### Task 1.1 — Evaluate replacement ensemble sources

Candidates (all free or low-cost):
- **National Blend of Models (NBM)** — already partially integrated via `nws.py`; extend to pull high/low directly
- **Open-Meteo alternative API** — `api-open-meteo.com` (community mirror, separate rate limit)
- **Weatherapi.com** — free tier 1M calls/month, returns hourly forecasts
- **Tomorrow.io** — free tier 500 calls/day, HRRR + GFS ensemble

### Task 1.2 — Extend NBM fetch as primary ensemble replacement

NBM is NOAA-operated (same as NWS), has no rate limit for reasonable use, and already has a fetch function in `nws.py`. Promote it to fill the ensemble slot.

```python
# weather_markets.py
# In get_weather_forecast(), when open_meteo circuit is OPEN,
# use NBM high/low directly rather than falling back only to Pirate Weather
nbm_data = fetch_nbm_forecast(city, target_date)
if nbm_data:
    highs.append((nbm_data["high_f"], 1.0))
    lows.append((nbm_data["low_f"], 1.0))
```

### Task 1.3 — Add weatherapi.com as second ensemble source

Register a free key at weatherapi.com (1M calls/month) and add a fetch function:

```python
# weather_markets.py
_weatherapi_cb = CircuitBreaker(name="weatherapi", failure_threshold=3, recovery_timeout=3600)

def fetch_temperature_weatherapi(city: str, target_date: date) -> dict | None:
    """Fetch high/low from weatherapi.com free tier."""
    ...
```

Weight it equally with NBM until rolling accuracy is established (Phase 3).

### Task 1.4 — Deprecate open_meteo_ensemble gracefully

- Keep the circuit breaker and fetch function in place (don't delete)
- Add a startup warning if the circuit has been OPEN for >24 hours
- Log `[DataSource] open_meteo_ensemble disabled — using NBM + weatherapi` in cron output

### Task 1.5 — Add structured logging to all circuit breaker failure sites

So future failures are diagnosable immediately:

```python
_om_cb.record_failure()
_log.warning("open_meteo_ensemble: failure #%d — %s: %s",
             _om_cb.failure_count, type(exc).__name__, exc)
```

### Tests

- Test NBM fetch returns expected high/low for fixture city/date
- Test weatherapi fetch parses response correctly
- Test fallback chain: open_meteo OPEN → NBM → weatherapi → Pirate Weather
- Test startup warning fires when circuit OPEN >24h

---

## Phase 2 — Signal quality tightening (Signal Quality 7→8.5)

**Why:** 44–50 strong signals per scan (15–17% of markets) is suspicious. Tightening thresholds and adding volume filtering will reduce noise and improve precision.

### Task 2.1 — Raise STRONG_EDGE default from 0.25 → 0.30

```python
# utils.py
STRONG_EDGE = float(os.getenv("STRONG_EDGE", "0.30"))
```

Update `.env.example` comment to reflect new default. Monitor next 5 cron runs — target is 20–30 strong signals (7–10% of markets). Adjust further if needed.

### Task 2.2 — Add minimum volume filter

Don't fire on markets with near-zero open interest — the price is meaningless.

```python
# weather_markets.py — inside analysis loop
MIN_VOLUME = int(os.getenv("MIN_SIGNAL_VOLUME", "50"))  # contracts

volume = market.get("volume", 0) or 0
if volume < MIN_VOLUME:
    _log.debug("Skipping %s — volume %d below minimum %d", ticker, volume, MIN_VOLUME)
    continue
```

Add `MIN_SIGNAL_VOLUME` to env vars table in README.

### Task 2.3 — Per-tier signal accuracy tracking

Currently Brier score is computed overall. Add breakdown by tier so you can see if STRONG signals actually outperform MED signals.

```python
# tracker.py — new function
def get_brier_by_tier() -> dict:
    """Brier score split by signal tier (strong / med / weak)."""
    ...
```

Display in `cmd_weekly_summary()` and dashboard.

### Task 2.4 — Signal confidence interval gate

If the ensemble forecast has high spread (e.g. ICON says 88°F, GFS says 78°F), suppress the signal regardless of edge.

```python
# weather_markets.py
MAX_MODEL_SPREAD_F = float(os.getenv("MAX_MODEL_SPREAD_F", "8.0"))

high_range = forecast.get("high_range", (high_f, high_f))
spread = high_range[1] - high_range[0]
if spread > MAX_MODEL_SPREAD_F:
    # models disagree too much — skip
    ...
```

### Tests

- Test volume filter skips low-volume markets
- Test spread gate suppresses high-uncertainty signals
- Test Brier-by-tier returns correct values for fixture data

---

## Phase 3 — Adaptive ensemble weights (ML/Forecasting 8.5→9)

**Why:** Static equal weighting of ICON/GFS/NBM ignores that some models are more accurate for certain cities or seasons.

### Task 3.1 — Track per-model accuracy in DB

Add `model_source` column to `analysis_attempts` (or a new `model_accuracy` table):

```sql
CREATE TABLE IF NOT EXISTS model_accuracy (
    city        TEXT NOT NULL,
    model       TEXT NOT NULL,  -- 'icon', 'gfs', 'nbm'
    target_date TEXT NOT NULL,
    predicted_f REAL,
    observed_f  REAL,
    error_f     REAL,
    recorded_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (city, model, target_date)
);
```

### Task 3.2 — Compute rolling 30-day MAE per model per city

```python
# tracker.py
def get_model_weights(city: str, window_days: int = 30) -> dict[str, float]:
    """Returns softmax-normalised inverse-MAE weights for each model."""
    ...
```

### Task 3.3 — Apply weights in ensemble averaging

```python
# weather_markets.py — in get_weather_forecast()
weights = get_model_weights(city)  # {'icon': 0.45, 'gfs': 0.35, 'nbm': 0.20}
# replace equal-weight averaging with weighted average
```

Fall back to equal weights if fewer than 10 observations for a model.

### Task 3.4 — Display model weights in `python main.py forecast <city>`

Show the current active weights so you can see which model the bot is trusting most.

### Tests

- Test weight computation with fixture accuracy data
- Test fallback to equal weights with insufficient data
- Test weight update after new observations

---

## Phase 4 — Station-level bias correction (ML/Forecasting 9→9, refinement)

**Why:** Dallas Love Field and Dallas Fort Worth are both "Dallas" but behave differently. City-level bias misses this.

### Task 4.1 — Map markets to nearest METAR station

```python
# metar.py — add station→city mapping
MARKET_STATION_MAP = {
    "DAL": "KDAL",  # Love Field
    "DFW": "KDFW",  # Fort Worth
    "NYC": "KNYC",
    ...
}
```

### Task 4.2 — Fetch observed high/low from METAR on settlement

When `sync_outcomes()` runs, also record the METAR observation for that station/date in a new `metar_observations` table.

### Task 4.3 — Train per-station bias models

Extend `ml_bias.py` to train a model per station (not just per city) when 200+ observations are available. Fall back to city-level model otherwise.

### Task 4.4 — Gate on data availability

Only activate station-level model if MAE < city-level model on held-out validation set.

### Tests

- Test station mapping lookup
- Test fallback from station → city model
- Test bias model selection logic

---

## Phase 5 — Correlation-aware Kelly (Risk 8.5→9.5)

**Why:** Two Dallas temperature positions on the same day are highly correlated — holding both over-concentrates risk. Current Kelly treats them as independent.

### Task 5.1 — Build correlation matrix from open positions

```python
# paper.py — new function
def position_correlation_matrix(open_trades: list[dict]) -> np.ndarray:
    """
    Returns NxN correlation matrix.
    Same city + same date → rho=0.85
    Same city + adjacent dates → rho=0.50
    Different cities → rho=0.10
    """
    ...
```

### Task 5.2 — Correlation-adjusted Kelly scale

```python
# paper.py
def corr_kelly_scale(trade: dict, open_trades: list[dict]) -> float:
    """Scale Kelly fraction down if new trade is correlated with existing positions."""
    corr_matrix = position_correlation_matrix(open_trades + [trade])
    max_corr = max(corr_matrix[-1, :-1])  # correlation of new trade with each existing
    return max(0.25, 1.0 - max_corr)  # minimum 25% of Kelly
```

### Task 5.3 — Integrate into `_auto_place_trades()`

Apply `corr_kelly_scale` before computing contract quantity in cron auto-placement.

### Task 5.4 — Monte Carlo uses correlation matrix

Update `monte_carlo.py` `simulate_portfolio()` to use correlated random draws instead of independent Bernoulli trials.

```python
# monte_carlo.py
from numpy.random import default_rng
rng = default_rng()
corr_matrix = position_correlation_matrix(trades)
# Use multivariate normal → threshold to correlated Bernoulli
```

### Tests

- Test correlation matrix: same city/date → 0.85, different cities → 0.10
- Test Kelly scale reduces for correlated positions
- Test Monte Carlo P&L distribution widens with correlated draws vs independent

---

## Phase 6 — Monte Carlo → position sizing feedback (Risk 9→9.5)

**Why:** Monte Carlo currently reports risk but doesn't influence sizing. Closing the loop makes risk management active.

### Task 6.1 — Extract 5th percentile outcome from Monte Carlo

```python
# monte_carlo.py
def portfolio_var(open_trades, confidence=0.05, n_simulations=1000) -> float:
    """Returns the dollar loss at the given confidence level (5th percentile)."""
    results = simulate_portfolio(open_trades, n_simulations)
    return float(np.percentile(results["pnl_distribution"], confidence * 100))
```

### Task 6.2 — Pre-trade VaR check in `_auto_place_trades()`

Before placing each trade, run a quick Monte Carlo with the new position included:

```python
projected_var = portfolio_var(open_trades + [candidate_trade])
if abs(projected_var) > MAX_VAR_DOLLARS:
    _log.warning("Skipping %s — would push portfolio VaR to $%.2f", ticker, projected_var)
    continue
```

Add `MAX_VAR_DOLLARS` env var (default: 20% of balance).

### Task 6.3 — Show VaR in cron output and dashboard

```
[cron] Portfolio VaR (5%): -$42.10  |  Expected: +$18.30
```

### Tests

- Test `portfolio_var` returns correct percentile
- Test pre-trade VaR gate blocks position when threshold exceeded
- Test VaR check does not fire when portfolio is within limits

---

## Phase 7 — Position-level stop-loss (Risk 9.5, refinement)

**Why:** Early exit currently only fires on model update. Price-based stops catch situations where the market moves sharply against you regardless of model.

### Task 7.1 — Add stop-loss parameters

```python
# utils.py
STOP_LOSS_MULT = float(os.getenv("STOP_LOSS_MULT", "2.0"))
# Exit if mark-to-market loss > STOP_LOSS_MULT × expected_loss
```

### Task 7.2 — Implement `check_stop_losses()` in `paper.py`

```python
def check_stop_losses(open_trades: list[dict], current_prices: dict) -> list[str]:
    """Return list of tickers that have breached their stop-loss."""
    exits = []
    for t in open_trades:
        cost = t.get("cost", 0)
        expected_loss = cost  # max loss = cost paid
        current_price = current_prices.get(t["ticker"], t["entry_price"])
        mark = _mark_to_market(t, current_price)
        if mark < -expected_loss * STOP_LOSS_MULT:
            exits.append(t["ticker"])
    return exits
```

### Task 7.3 — Call in cron scan

After pre-warming forecasts, fetch current prices and run stop-loss check before placing new trades.

### Tests

- Test stop triggered when price moves 2× expected loss
- Test stop not triggered within normal range
- Test cron closes stopped positions before placing new ones

---

## Phase 8 — Test coverage improvements (Tests 8→9)

### Task 8.1 — Property-based tests for Kelly sizing (Hypothesis)

```python
# tests/test_kelly_property.py
from hypothesis import given, strategies as st

@given(
    edge=st.floats(min_value=0.01, max_value=0.50),
    win_prob=st.floats(min_value=0.05, max_value=0.95),
    balance=st.floats(min_value=10.0, max_value=10000.0),
)
def test_kelly_never_exceeds_balance(edge, win_prob, balance):
    qty, cost = kelly_size(edge, win_prob, balance)
    assert cost <= balance
    assert qty >= 0
```

### Task 8.2 — Forecast accuracy regression tests

Save a snapshot of NWS/METAR observations for 3 cities × 3 dates. Assert that `get_weather_forecast()` returns values within ±5°F of the archived observations.

```python
# tests/test_forecast_accuracy.py
FORECAST_FIXTURES = [
    {"city": "NYC", "date": "2026-04-01", "observed_high": 62.0},
    ...
]
```

Uses `responses` or `pytest-httpx` to mock the API calls.

### Task 8.3 — Sandbox API integration tests (skipped in CI, runnable locally)

```python
# tests/test_integration_live.py
import pytest

@pytest.mark.skipif(not os.getenv("KALSHI_ENV") == "demo", reason="requires demo credentials")
def test_fetch_markets_returns_list(client):
    markets = client.get_markets(limit=10)
    assert len(markets) > 0
```

Mark with `@pytest.mark.integration` so they're excluded from normal `pytest` runs but can be triggered with `pytest -m integration`.

### Task 8.4 — Circuit breaker backoff tests

```python
# tests/test_circuit_breaker.py
def test_backoff_doubles_recovery_timeout():
    cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60, backoff_multiplier=2.0)
    # trip once → 60s recovery
    # trip again → 120s recovery
    # trip again → 240s recovery
    ...
```

---

## Phase 9 — Circuit breaker health in dashboard (Architecture 9→9.5)

**Why:** Circuit breaker state is only visible in cron logs. The dashboard should show it live.

### Task 9.1 — Add `/api/circuit-status` endpoint in `web_app.py`

```python
@app.route("/api/circuit-status")
def circuit_status():
    from weather_markets import _om_cb, _pirate_cb
    from kalshi_ws import _ws_cb  # if exists
    return jsonify({
        "open_meteo_ensemble": {
            "state": "open" if _om_cb.is_open() else "closed",
            "failures": _om_cb.failure_count,
            "retry_in_s": _om_cb.seconds_until_retry(),
        },
        "pirate_weather": { ... },
    })
```

### Task 9.2 — Show circuit breaker status card in dashboard

Add a "Data Sources" card to the web dashboard showing green/red status for each circuit. Red = OPEN with retry countdown.

### Task 9.3 — Alert when circuit opens

In `cmd_cron()`, if a circuit transitions from closed → open during the scan, trigger a Discord/desktop notification.

---

## Phase 10 — Live readiness path (Live Readiness 6→8)

**Why:** Paper trading proves nothing without live validation. This phase is a process, not just code.

### Task 10.1 — Micro live trades alongside paper

When `KALSHI_ENV=prod` is set, place a parallel live trade at 1/100th the paper size (min $1) for every paper trade. This gives real fill data and slippage measurements without meaningful risk.

```python
# paper.py / main.py
MICRO_LIVE_FRACTION = float(os.getenv("MICRO_LIVE_FRACTION", "0.01"))
```

Gate behind `ENABLE_MICRO_LIVE=true` env var so it can't happen accidentally.

### Task 10.2 — Graduation dashboard widget

Add a graduation progress bar to the web dashboard:
- Settled trades: `N / 30`
- PnL: `$X / $50`
- Brier score: `0.XX / ≤0.20`

Green checkmark when all three pass.

### Task 10.3 — Weekly Brier score alert

If Brier score rises above 0.22 (10% above target) for two consecutive weeks, auto-send a notification and pause new live trades until reviewed.

### Task 10.4 — Live slippage tracking

Compare `entry_price` (paper) vs actual fill price (live) for each micro trade. Track mean slippage in DB and display in dashboard. If mean slippage exceeds 0.5¢, adjust `slippage_adjusted_price()` model.

---

## Implementation order

| Priority | Phase | Impact | Effort | Score gain |
|---|---|---|---|---|
| 1 | Phase 1 — Replace open_meteo with NBM + weatherapi | High | Medium | ML +1.0 |
| 2 | Phase 2 — Signal tightening | High | Low | Signal +1.0 |
| 3 | Phase 5 — Correlation Kelly | High | Medium | Risk +0.5 |
| 4 | Phase 3 — Adaptive weights | High | Medium | ML +0.5 |
| 5 | Phase 6 — Monte Carlo → sizing | Medium | Medium | Risk +0.25 |
| 6 | Phase 8 — Test coverage | Medium | Medium | Tests +1.0 |
| 7 | Phase 9 — Dashboard circuits | Low | Low | Arch +0.5 |
| 8 | Phase 7 — Stop-losses | Medium | Low | Risk +0.25 |
| 9 | Phase 4 — Station bias | High | High | ML +0.5 |
| 10 | Phase 10 — Live readiness | High | Ongoing | Live +2.0 |
