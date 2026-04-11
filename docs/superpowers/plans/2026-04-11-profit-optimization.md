# Profit Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 10 profit-maximization changes covering trade frequency, position sizing, signal quality, and trade management.

**Architecture:** Changes flow through 4 files in dependency order: `utils.py` (constants) → `paper.py` (sizing engine) → `weather_markets.py` (signal enrichment) → `main.py` (orchestration). Each task is independently testable and committed before the next.

**Tech Stack:** Python 3.11+, pytest, existing `tracker.py` (Brier scores), `paper.py` (paper ledger), `weather_markets.py` (signal analysis)

**Spec:** `docs/superpowers/specs/2026-04-11-profit-optimization-design.md`

---

## File Map

| File | What changes |
|------|-------------|
| `utils.py` | Add `MED_EDGE`, `MAX_DAILY_SPEND` constants |
| `paper.py` | `kelly_bet_dollars()` gains `cap` + `method` params + dynamic Brier cap; `place_paper_order()` records `entry_hour`; new `close_paper_early()` |
| `weather_markets.py` | `analyze_trade()` adds `model_consensus`, `near_threshold` fields; new `_get_consensus_probs()` helper |
| `main.py` | `cmd_cron` builds MED+STRONG tiers + early-exit loop + near_threshold cache; `_auto_place_trades()` gains `cap` param + daily spend check; new `cmd_schedule_cycles()` |
| `tests/test_paper.py` | Update cap assertions; add tests for `close_paper_early`, `entry_hour`, dynamic Brier cap |
| `tests/test_weather_markets.py` | Add tests for `model_consensus`, `near_threshold` fields |

---

## Task 1: Add MED_EDGE and MAX_DAILY_SPEND to utils.py

**Files:**
- Modify: `utils.py`
- Test: `tests/test_paper.py` (import check)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_paper.py` (at the top of the file, in the imports section):

```python
def test_med_edge_and_max_daily_spend_constants_exist():
    from utils import MED_EDGE, MAX_DAILY_SPEND
    assert 0 < MED_EDGE < 0.25
    assert MAX_DAILY_SPEND > 0
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_paper.py::test_med_edge_and_max_daily_spend_constants_exist -v
```

Expected: `ImportError: cannot import name 'MED_EDGE'`

- [ ] **Step 3: Add constants to utils.py**

In `utils.py`, after the `STRONG_EDGE` line (line 21), add:

```python
MED_EDGE = float(
    os.getenv("MED_EDGE", "0.15")
)  # threshold for medium-confidence auto-trade tier
MAX_DAILY_SPEND = float(
    os.getenv("MAX_DAILY_SPEND", "100.0")
)  # max total paper dollars auto-traded per day
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_paper.py::test_med_edge_and_max_daily_spend_constants_exist -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```
git add utils.py tests/test_paper.py
git commit -m "feat(utils): add MED_EDGE and MAX_DAILY_SPEND constants"
```

---

## Task 2: Overhaul kelly_bet_dollars() — cap param, dynamic Brier cap, method scaling

**Files:**
- Modify: `paper.py` — `kelly_bet_dollars()` function (lines ~292–321)
- Test: `tests/test_paper.py`

The current signature is `kelly_bet_dollars(kelly_fraction: float) -> float` with a hardcoded $50 cap.

New signature: `kelly_bet_dollars(kelly_fraction: float, cap: float | None = None, method: str | None = None) -> float`

- `cap=None` → compute dynamic Brier cap (STRONG tier)
- `cap=20.0` → MED tier ceiling, ignores Brier
- `method` → scale Kelly by per-method Brier (e.g., "ensemble", "normal_dist")

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_paper.py`:

```python
def test_kelly_bet_dollars_respects_explicit_cap(mock_balance_1000):
    """Explicit cap overrides dynamic Brier cap."""
    from paper import kelly_bet_dollars
    result = kelly_bet_dollars(0.5, cap=20.0)
    assert result <= 20.0


def test_kelly_bet_dollars_dynamic_cap_unlocks_with_good_brier(mock_balance_1000, monkeypatch):
    """Dynamic cap raises above $50 when Brier score is excellent."""
    import paper
    monkeypatch.setattr(paper, "_dynamic_kelly_cap", lambda: 125.0)
    result = kelly_bet_dollars(0.5)
    assert result <= 125.0
    assert result > 50.0  # would be capped at 50 under old logic


def test_kelly_bet_dollars_method_scaling_reduces_kelly(mock_balance_1000, monkeypatch):
    """Poor-performing method (Brier > 0.20) reduces Kelly by 25%."""
    import paper
    monkeypatch.setattr(paper, "_method_kelly_multiplier", lambda m: 0.75)
    base = kelly_bet_dollars(0.5)
    scaled = kelly_bet_dollars(0.5, method="normal_dist")
    assert scaled < base
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_paper.py::test_kelly_bet_dollars_respects_explicit_cap tests/test_paper.py::test_kelly_bet_dollars_dynamic_cap_unlocks_with_good_brier tests/test_paper.py::test_kelly_bet_dollars_method_scaling_reduces_kelly -v
```

Expected: FAIL

- [ ] **Step 3: Add helper functions above kelly_bet_dollars in paper.py**

Add these two helpers immediately before `kelly_bet_dollars` (around line 292):

```python
def _dynamic_kelly_cap() -> float:
    """Determine STRONG-tier per-trade cap from current Brier score.

    Brier scale: lower = better. 0.0 = perfect, 0.25 = random.
    As bot proves calibration, cap unlocks automatically.
    """
    try:
        from tracker import brier_score as _brier
        score = _brier()
        if score is None:
            return 50.0
        if score <= 0.05:
            return 125.0
        if score <= 0.10:
            return 100.0
        if score <= 0.15:
            return 75.0
        return 50.0
    except Exception:
        return 50.0


def _method_kelly_multiplier(method: str | None) -> float:
    """Scale Kelly fraction based on per-method Brier performance.

    method is the analysis method string from analyze_trade(): 'ensemble' or 'normal_dist'.
    Uses brier_score_by_method() which requires min_samples=20 per method.
    Falls back to 1.0 (no change) if insufficient data.
    """
    if not method:
        return 1.0
    try:
        from tracker import brier_score_by_method as _by_method
        scores = _by_method(min_samples=5)  # lower threshold than default
        if method not in scores:
            return 1.0
        brier = scores[method]
        if brier > 0.20:
            return 0.75
        return 1.0
    except Exception:
        return 1.0
```

- [ ] **Step 4: Modify kelly_bet_dollars signature and body in paper.py**

Replace the existing `kelly_bet_dollars` function:

```python
def kelly_bet_dollars(
    kelly_fraction: float,
    cap: float | None = None,
    method: str | None = None,
) -> float:
    """
    Return the dollar amount to bet.
    #120: Respects STRATEGY env var:
      kelly:         half-Kelly × balance (default)
      fixed_pct:     FIXED_BET_PCT × balance regardless of Kelly
      fixed_dollars: FIXED_BET_DOLLARS flat per trade

    cap: explicit per-trade ceiling (e.g. 20.0 for MED tier).
         If None, uses _dynamic_kelly_cap() based on current Brier score.
    method: analysis method string ('ensemble', 'normal_dist'); scales Kelly
            down if that method's Brier performance is poor.

    Applies drawdown scaling and streak pause regardless of strategy.
    """
    scale = drawdown_scaling_factor()
    if scale == 0.0:
        return 0.0
    balance = get_balance()

    if STRATEGY == "fixed_pct":
        dollars = round(balance * min(FIXED_BET_PCT, 0.25), 2)
    elif STRATEGY == "fixed_dollars":
        dollars = min(FIXED_BET_DOLLARS, balance)
    else:
        # Default: half-Kelly, hard cap at 25% of balance
        fraction = max(0.0, min(kelly_fraction * scale, 0.25))
        dollars = round(balance * fraction, 2)

    if is_streak_paused():
        dollars = round(dollars * 0.50, 2)

    # Apply per-method Brier scaling before cap
    dollars = round(dollars * _method_kelly_multiplier(method), 2)

    # Determine active cap: explicit (MED tier) or dynamic Brier-based (STRONG tier)
    active_cap = cap if cap is not None else _dynamic_kelly_cap()
    dollars = min(dollars, active_cap)
    return dollars
```

- [ ] **Step 5: Update existing cap assertions in test_paper.py**

The existing test `test_kelly_bet_dollars_caps_at_50_dollars` asserts `<= 50`. It now needs to pass `cap=50.0` explicitly (or accept the dynamic cap). Find the test and update:

```python
def test_kelly_bet_dollars_caps_at_50_dollars(mock_balance_1000):
    # Pass explicit cap to test the cap parameter behaviour
    result = kelly_bet_dollars(1.0, cap=50.0)
    assert result <= 50.0
```

- [ ] **Step 6: Run all paper tests**

```
pytest tests/test_paper.py -v
```

Expected: All PASS

- [ ] **Step 7: Commit**

```
git add paper.py tests/test_paper.py
git commit -m "feat(paper): kelly_bet_dollars gains cap/method params and dynamic Brier cap"
```

---

## Task 3: Add close_paper_early() and entry_hour tracking to paper.py

**Files:**
- Modify: `paper.py` — `place_paper_order()` and new `close_paper_early()`
- Test: `tests/test_paper.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_paper.py`:

```python
def test_place_paper_order_records_entry_hour(mock_balance_1000):
    """place_paper_order should record the UTC hour of entry."""
    from paper import place_paper_order, get_open_trades
    place_paper_order("TEST-TICKER", "yes", 1, 0.40)
    trades = get_open_trades()
    assert len(trades) == 1
    assert "entry_hour" in trades[0]
    assert 0 <= trades[0]["entry_hour"] <= 23


def test_close_paper_early_settles_at_exit_price(mock_balance_1000):
    """close_paper_early should settle trade at exit price, not $0/$1."""
    from paper import place_paper_order, close_paper_early, get_open_trades, get_balance
    place_paper_order("TEST-TICKER", "yes", 10, 0.40)  # paid $4.00
    balance_after_entry = get_balance()
    trade_id = get_open_trades()[0]["id"]
    close_paper_early(trade_id, exit_price=0.55)  # selling at $5.50
    assert not get_open_trades()  # no more open trades
    assert get_balance() > balance_after_entry  # profit (sold higher than bought)
    from paper import _load
    t = [t for t in _load()["trades"] if t["id"] == trade_id][0]
    assert t["outcome"] == "early_exit"
    assert abs(t["pnl"] - 1.50) < 0.01  # (0.55 - 0.40) * 10 = $1.50


def test_close_paper_early_raises_on_unknown_id(mock_balance_1000):
    from paper import close_paper_early
    with pytest.raises(ValueError, match="not found"):
        close_paper_early(9999, exit_price=0.50)
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_paper.py::test_place_paper_order_records_entry_hour tests/test_paper.py::test_close_paper_early_settles_at_exit_price tests/test_paper.py::test_close_paper_early_raises_on_unknown_id -v
```

Expected: FAIL

- [ ] **Step 3: Add entry_hour to place_paper_order in paper.py**

Find `place_paper_order` in `paper.py`. Inside the function, where the trade dict is built (look for `"ticker": ticker`), add `"entry_hour"` to the dict:

```python
"entry_hour": datetime.now(UTC).hour,
```

This should go alongside `"entry_time"` or similar existing timestamp fields.

- [ ] **Step 4: Add close_paper_early to paper.py**

Add this function immediately after `settle_paper_trade` (after line ~483):

```python
def close_paper_early(trade_id: int, exit_price: float) -> dict:
    """
    Close an open paper trade at current market price instead of waiting for settlement.
    Used when a model-cycle update shifts our probability against the position.

    P&L = (exit_price - entry_price) * quantity  (same formula for YES and NO,
    because entry_price is always the price paid per contract for our side).
    Updates balance with proceeds (exit_price * quantity).
    """
    data = _load()
    for t in data["trades"]:
        if t["id"] == trade_id and not t["settled"]:
            qty = t["quantity"]
            entry_price = t["entry_price"]
            proceeds = round(exit_price * qty, 4)
            cost = t["cost"]  # entry_price * qty, already stored
            pnl = round(proceeds - cost, 4)
            t["settled"] = True
            t["outcome"] = "early_exit"
            t["exit_price"] = round(exit_price, 4)
            t["pnl"] = pnl
            data["balance"] += proceeds
            data["peak_balance"] = max(
                data.get("peak_balance", STARTING_BALANCE), data["balance"]
            )
            _save(data)
            return t
    raise ValueError(f"Trade {trade_id} not found or already settled.")
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_paper.py -v
```

Expected: All PASS

- [ ] **Step 6: Commit**

```
git add paper.py tests/test_paper.py
git commit -m "feat(paper): add close_paper_early() and entry_hour field"
```

---

## Task 4: Add model_consensus and near_threshold to analyze_trade()

**Files:**
- Modify: `weather_markets.py` — `analyze_trade()` and new `_get_consensus_probs()` helper
- Test: `tests/test_weather_markets.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_weather_markets.py`:

```python
def test_analyze_trade_includes_model_consensus_field(sample_enriched_market):
    """analyze_trade result should always include model_consensus bool."""
    from weather_markets import analyze_trade
    result = analyze_trade(sample_enriched_market)
    if result is not None:
        assert "model_consensus" in result
        assert isinstance(result["model_consensus"], bool)


def test_analyze_trade_includes_near_threshold_field(sample_enriched_market):
    """analyze_trade result should include near_threshold bool."""
    from weather_markets import analyze_trade
    result = analyze_trade(sample_enriched_market)
    if result is not None:
        assert "near_threshold" in result
        assert isinstance(result["near_threshold"], bool)


def test_near_threshold_true_when_forecast_within_3f(monkeypatch):
    """near_threshold is True when forecast is within 3°F of strike."""
    # This test constructs a minimal enriched market where we can control forecast_temp
    # and threshold. Verify near_threshold=True when |forecast - threshold| <= 3.
    from weather_markets import analyze_trade
    import weather_markets as wm

    # Monkeypatch get_ensemble_temps to return a tight cluster near 72°F
    monkeypatch.setattr(wm, "get_ensemble_temps", lambda *a, **kw: [71.0] * 20)

    enriched = {
        "_forecast": {"high_f": 72.0, "low_f": 55.0},
        "_date": __import__("datetime").date.today(),
        "_city": "NYC",
        "_hour": None,
        "ticker": "KXHIGH-NYC-72-ABOVE",
        "series_ticker": "KXHIGH-NYC",
        "yes_ask": 52,
        "yes_bid": 48,
        "volume": 500,
        "open_interest": 200,
        "close_time": (__import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                       + __import__("datetime").timedelta(hours=4)).isoformat(),
    }
    result = analyze_trade(enriched)
    if result is not None:
        # forecast=72, threshold=72 → distance=0 → near_threshold=True
        assert result["near_threshold"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_weather_markets.py::test_analyze_trade_includes_model_consensus_field tests/test_weather_markets.py::test_analyze_trade_includes_near_threshold_field tests/test_weather_markets.py::test_near_threshold_true_when_forecast_within_3f -v
```

Expected: FAIL (KeyError or AssertionError)

- [ ] **Step 3: Add _get_consensus_probs helper to weather_markets.py**

Add this helper near `edge_confidence` (around line 1554):

```python
def _get_consensus_probs(
    city: str,
    target_date,
    condition: dict,
    hour: int | None = None,
    var: str = "max",
) -> tuple[float | None, float | None]:
    """Fetch per-model ensemble probabilities for ICON and GFS separately.

    Returns (icon_prob, gfs_prob). Either may be None if that model returned
    fewer than 5 members. Used for model_consensus check in analyze_trade().
    """
    def _model_prob(model_name: str) -> float | None:
        try:
            # Fetch temps for a single model by temporarily restricting ENSEMBLE_MODELS
            coords = CITY_COORDS.get(city)
            if not coords:
                return None
            # Use existing ensemble cache infrastructure with model-specific key
            from datetime import date as _date
            cache_key = (model_name, city, target_date.isoformat(), var, hour)
            if cache_key in _ENSEMBLE_CACHE:
                cached_temps, ts = _ENSEMBLE_CACHE[cache_key]
                if time.time() - ts < _ENSEMBLE_CACHE_TTL:
                    temps = cached_temps
                else:
                    temps = None
            else:
                temps = None

            if temps is None:
                # Fetch directly using the single-model path
                lat, lon = coords[0], coords[1]
                tz = coords[2] if len(coords) > 2 else "UTC"
                var_field = f"temperature_2m_{'max' if var == 'max' else 'min'}"
                params = {
                    "latitude": lat,
                    "longitude": lon,
                    "timezone": tz,
                    "daily": [var_field],
                    "temperature_unit": "fahrenheit",
                    "models": model_name,
                    "start_date": target_date.isoformat(),
                    "end_date": target_date.isoformat(),
                    "forecast_days": 7,
                }
                resp = _request_with_retry(ENSEMBLE_BASE, params=params)
                if not resp:
                    return None
                daily = resp.get("daily", {})
                # Ensemble returns member columns: temperature_2m_max_member01, etc.
                members = [
                    v[0]
                    for k, v in daily.items()
                    if k.startswith(var_field) and v and v[0] is not None
                ]
                # Convert Celsius to Fahrenheit if needed (open-meteo returns °F when requested)
                temps = [float(t) for t in members]
                _ENSEMBLE_CACHE[cache_key] = (temps, time.time())

            if len(temps) < 5:
                return None

            thresh = condition.get("threshold")
            if condition["type"] == "above" and thresh is not None:
                return sum(1 for t in temps if t > thresh) / len(temps)
            elif condition["type"] == "below" and thresh is not None:
                return sum(1 for t in temps if t < thresh) / len(temps)
            elif condition["type"] == "range":
                lo, hi = condition.get("lower", 0), condition.get("upper", 999)
                return sum(1 for t in temps if lo <= t <= hi) / len(temps)
            return None
        except Exception:
            return None

    icon_prob = _model_prob("icon_seamless")
    gfs_prob = _model_prob("gfs_seamless")
    return icon_prob, gfs_prob
```

- [ ] **Step 4: Add model_consensus and near_threshold to analyze_trade() return value**

In `analyze_trade()`, find the section after `ens_prob` is computed (around line 2055). Add the consensus check:

```python
    # ── Model consensus check ────────────────────────────────────────────────
    model_consensus = True
    if ens_prob is not None and len(temps) >= 10:
        try:
            icon_p, gfs_p = _get_consensus_probs(city, target_date, condition, hour=hour, var=var)
            if icon_p is not None and gfs_p is not None:
                if abs(icon_p - gfs_p) > 0.08:
                    model_consensus = False
        except Exception:
            pass  # default to True (tradeable)
```

Then find the `near_threshold` logic. Add after `forecast_temp` is determined:

```python
    # ── Near-threshold detection ─────────────────────────────────────────────
    threshold_val = condition.get("threshold")
    near_threshold = (
        threshold_val is not None
        and abs(forecast_temp - threshold_val) <= 3.0
    )
```

Then in the final return dict of `analyze_trade()`, add both fields:

```python
        "model_consensus": model_consensus,
        "near_threshold": near_threshold,
```

Note: `analyze_trade` has multiple return paths (precip fast-path, snow fast-path, main path). Add `model_consensus` and `near_threshold` to ALL return paths. For precip/snow fast-paths, set `model_consensus=True` and `near_threshold=False` as defaults (consensus split not implemented for those condition types yet).

In `_analyze_precip_trade()` and `_analyze_snow_trade()`, the result dict returned should include:
```python
        "model_consensus": True,
        "near_threshold": False,
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_weather_markets.py -v
```

Expected: All PASS (new tests pass, existing tests unaffected)

- [ ] **Step 6: Commit**

```
git add weather_markets.py tests/test_weather_markets.py
git commit -m "feat(signals): add model_consensus and near_threshold to analyze_trade"
```

---

## Task 5: Tiered auto-trade in cmd_cron and _auto_place_trades()

**Files:**
- Modify: `main.py` — `_auto_place_trades()` and `cmd_cron()`
- Test: `tests/test_trading.py` (or `tests/test_paper.py` if no trading test exists)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_trading.py` (or create if needed):

```python
def test_auto_place_trades_respects_cap_parameter(monkeypatch):
    """_auto_place_trades should pass cap to kelly_bet_dollars."""
    import main
    placed_caps = []

    def fake_kelly_quantity(kf, price, min_dollars=1.0, cap=None):
        placed_caps.append(cap)
        return 1

    monkeypatch.setattr(main, "place_paper_order", lambda *a, **kw: {"id": 1})
    # Build a minimal strong opp
    enriched = {"ticker": "TEST", "_city": "NYC", "_date": None}
    analysis = {
        "net_signal": "STRONG BUY",
        "time_risk": "LOW",
        "recommended_side": "yes",
        "market_prob": 0.40,
        "forecast_prob": 0.65,
        "net_edge": 0.28,
        "ci_adjusted_kelly": 0.05,
        "model_consensus": True,
        "method": "ensemble",
    }
    from main import _auto_place_trades
    _auto_place_trades([(enriched, analysis)], cap=20.0)
    # Verify cap was forwarded — check via placed order or monkeypatched call
```

Note: the test structure here will need to fit the actual mocking approach used in existing `test_trading.py`. Check the file first and match the pattern.

- [ ] **Step 2: Modify _auto_place_trades() signature**

In `main.py`, change the signature of `_auto_place_trades`:

```python
def _auto_place_trades(
    opps: list,
    client=None,
    live: bool = False,
    live_config: dict | None = None,
    cap: float | None = None,  # NEW: per-trade dollar cap (None = dynamic Brier cap)
) -> int:
```

Inside `_auto_place_trades`, find the `kelly_quantity` call:
```python
        qty = kelly_quantity(adj_kelly, entry_price)
```

Replace with:
```python
        method = a.get("method")
        # Apply consensus half-sizing when models disagree
        consensus_mult = 0.5 if not a.get("model_consensus", True) else 1.0
        adj_kelly_final = adj_kelly * consensus_mult
        qty = kelly_quantity(adj_kelly_final, entry_price, cap=cap)
```

Also update `kelly_quantity` import at the top of `_auto_place_trades` to include it, and update `place_paper_order` call to pass `method`:

```python
                trade = place_paper_order(
                    ticker,
                    rec_side,
                    qty,
                    entry_price,
                    entry_prob=a.get("forecast_prob"),
                    net_edge=a.get("net_edge"),
                    city=city,
                    target_date=target_date_str,
                    method=a.get("method"),  # NEW: for condition Brier scaling
                )
```

Note: `kelly_quantity` calls `kelly_bet_dollars` internally. You need to also pass `cap` and `method` through `kelly_quantity`. Check `kelly_quantity`'s signature in `paper.py` and update it to accept and forward `cap` and `method`:

```python
def kelly_quantity(
    kelly_fraction: float,
    price: float,
    min_dollars: float = 1.0,
    cap: float | None = None,
    method: str | None = None,
) -> int:
    if price <= 0:
        return 0
    dollars = kelly_bet_dollars(kelly_fraction, cap=cap, method=method)
    if dollars < min_dollars:
        return 0
    return int(dollars / price)
```

Also add `method` to `place_paper_order` in `paper.py` — store it in the trade dict for analytics:
```python
"method": method,  # analysis method used for this trade
```

- [ ] **Step 3: Remove hard "STRONG" signal filter from _auto_place_trades**

The current code has:
```python
        if "STRONG" not in a.get("net_signal", ""):
            continue
```

Remove this line. The caller (`cmd_cron`) is now responsible for building the correct opp list. The function should place whatever it's given (as long as it passes the other guards: ticker not already held, adj_kelly >= 0.005, qty >= 1).

Also remove:
```python
        if a.get("time_risk") == "HIGH":
            continue
```

The caller manages time risk filtering per tier.

- [ ] **Step 4: Update cmd_cron to build MED and STRONG opp lists**

In `cmd_cron`, find where `strong_opps` is built:

```python
    strong_opps: list = []
```

Change to:

```python
    med_opps: list = []    # edge 15–24%, LOW or MEDIUM risk
    strong_opps: list = []  # edge 25%+, any time risk
```

Find the section inside the loop that builds `strong_opps`:
```python
            if abs(net_edge) >= STRONG_EDGE:
                strong_opps.append((enriched, analysis))
```

Replace with:

```python
            from utils import MED_EDGE, STRONG_EDGE
            time_risk = analysis.get("time_risk", "HIGH")
            if abs(net_edge) >= STRONG_EDGE:
                strong_opps.append((enriched, analysis))
            elif abs(net_edge) >= MED_EDGE and time_risk in ("LOW", "MEDIUM"):
                med_opps.append((enriched, analysis))
```

Find where `_auto_place_trades` is called:
```python
    if strong_opps:
        ...
        placed_count = _auto_place_trades(strong_opps, client=client) or 0
```

Replace with:

```python
    placed_count = 0
    if strong_opps:
        from paper import _dynamic_kelly_cap
        strong_cap = _dynamic_kelly_cap()
        print(bold(f"\n  !! {len(strong_opps)} STRONG SIGNAL(S) — placing paper trades (cap=${strong_cap:.0f}) !!"))
        placed_count += _auto_place_trades(strong_opps, client=client, cap=strong_cap) or 0
    if med_opps:
        print(bold(f"\n  !! {len(med_opps)} MED SIGNAL(S) — placing paper trades (cap=$20) !!"))
        placed_count += _auto_place_trades(med_opps, client=client, cap=20.0) or 0
```

Also update the signals_cache `stars` field to include near_threshold:

```python
                "stars": stars,
                "near_threshold": analysis.get("near_threshold", False),  # NEW
```

- [ ] **Step 5: Run full test suite**

```
pytest tests/ -v --tb=short
```

Expected: All PASS

- [ ] **Step 6: Commit**

```
git add main.py paper.py tests/test_trading.py
git commit -m "feat(trading): tiered auto-trade — MED ($20) and STRONG (dynamic cap) tiers"
```

---

## Task 6: Daily spend cap in _auto_place_trades()

**Files:**
- Modify: `main.py` — `_auto_place_trades()`
- Test: `tests/test_trading.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_trading.py`:

```python
def test_auto_place_trades_stops_at_daily_spend_cap(monkeypatch):
    """Should stop placing trades once MAX_DAILY_SPEND is reached for today."""
    import main
    import utils
    monkeypatch.setattr(utils, "MAX_DAILY_SPEND", 0.01)  # effectively $0 cap

    placed = 0
    def fake_place(*a, **kw):
        nonlocal placed
        placed += 1
        return {"id": placed, "cost": 10.0}
    monkeypatch.setattr(main, "place_paper_order", fake_place)

    enriched = {"ticker": "TEST", "_city": "NYC", "_date": None}
    analysis = {
        "net_signal": "STRONG BUY",
        "time_risk": "LOW",
        "recommended_side": "yes",
        "market_prob": 0.40,
        "forecast_prob": 0.65,
        "net_edge": 0.28,
        "ci_adjusted_kelly": 0.05,
        "model_consensus": True,
        "method": "ensemble",
    }
    from main import _auto_place_trades
    result = _auto_place_trades([(enriched, analysis)], cap=50.0)
    assert result == 0  # cap already exceeded, no trades placed
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_trading.py::test_auto_place_trades_stops_at_daily_spend_cap -v
```

Expected: FAIL

- [ ] **Step 3: Add daily spend check to _auto_place_trades()**

Add a helper function in `main.py` (near `_auto_place_trades`):

```python
def _daily_paper_spend() -> float:
    """Sum of paper trade costs placed today (UTC date). Used for daily spend cap."""
    from paper import _load
    today = datetime.now(UTC).date().isoformat()
    data = _load()
    return sum(
        t.get("cost", 0.0)
        for t in data["trades"]
        if t.get("entry_time", "")[:10] == today
    )
```

Inside `_auto_place_trades`, before the `for item in opps` loop, add:

```python
    from utils import MAX_DAILY_SPEND
    daily_spent = _daily_paper_spend()
    if daily_spent >= MAX_DAILY_SPEND:
        print(yellow(f"  [Auto] Daily spend cap reached (${daily_spent:.2f}/${MAX_DAILY_SPEND:.0f}) — no auto-trades."))
        return 0
```

Also add a per-trade spend check inside the loop, after `qty` is determined:

```python
        trade_cost = round(entry_price * qty, 2)
        if daily_spent + trade_cost > MAX_DAILY_SPEND:
            print(yellow(f"  [Auto] Skipping {ticker}: would exceed daily cap (${daily_spent:.2f}/${MAX_DAILY_SPEND:.0f})"))
            continue
```

And after a successful paper trade is placed, update `daily_spent`:
```python
                daily_spent += trade.get("cost", 0.0)
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_trading.py tests/test_paper.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```
git add main.py tests/test_trading.py
git commit -m "feat(trading): add daily spend cap to _auto_place_trades"
```

---

## Task 7: Early exit loop in cmd_cron

**Files:**
- Modify: `main.py` — `cmd_cron()`
- Test: `tests/test_trading.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_trading.py`:

```python
def test_early_exit_closes_position_when_prob_flips(monkeypatch, mock_balance_1000):
    """If updated prob shifts >15pp against position, close_paper_early is called."""
    import main
    import paper
    from paper import place_paper_order, get_open_trades

    # Place an open YES trade at 70% prob
    place_paper_order("TEST-TICKER", "yes", 5, 0.70, entry_prob=0.70)
    trade_id = get_open_trades()[0]["id"]

    closed = []
    def fake_close(tid, exit_price):
        closed.append((tid, exit_price))
        return {"id": tid, "outcome": "early_exit", "pnl": -1.0}

    # Updated analysis shows prob dropped to 50% — 20pp shift against YES
    fake_analysis = {
        "forecast_prob": 0.50,
        "market_prob": 0.65,
        "recommended_side": "yes",
    }
    fake_market = {"ticker": "TEST-TICKER", "yes_bid": 48, "yes_ask": 52}

    # Patch at the module where each name is resolved inside _check_early_exits
    monkeypatch.setattr(paper, "close_paper_early", fake_close)
    monkeypatch.setattr(main, "analyze_trade", lambda e: fake_analysis)
    monkeypatch.setattr(main, "enrich_with_forecast", lambda m: m)
    monkeypatch.setattr(main, "get_weather_markets", lambda client: [fake_market])

    from main import _check_early_exits
    _check_early_exits(client=None)

    assert len(closed) == 1
    assert closed[0][0] == trade_id
```

- [ ] **Step 2: Extract _check_early_exits() from cmd_cron**

Add a new function to `main.py`:

```python
def _check_early_exits(client=None) -> int:
    """
    Re-analyze all open paper positions. If the updated model probability has
    shifted >15 percentage points against the entry direction, close the position
    early at the current market mid-price.

    Returns the number of positions closed.
    """
    import paper as _paper
    from paper import get_open_trades

    open_trades = get_open_trades()
    if not open_trades:
        return 0

    closed = 0
    for trade in open_trades:
        ticker = trade.get("ticker", "")
        entry_prob = trade.get("entry_prob")
        side = trade.get("side", "yes")
        if entry_prob is None:
            continue  # cannot assess shift without entry probability

        # Re-fetch market and re-analyze
        try:
            if client is None:
                continue  # cannot fetch live market prices without a client
            markets = get_weather_markets(client)
            market = next((m for m in markets if m.get("ticker") == ticker), None)
            if not market:
                continue  # market may have closed already
            enriched = enrich_with_forecast(market)
            analysis = analyze_trade(enriched)
            if not analysis:
                continue
            current_prob = analysis.get("forecast_prob", entry_prob)

            # Shift direction check
            if side == "yes":
                # Entered YES: bad if prob fell significantly
                shift = entry_prob - current_prob
            else:
                # Entered NO: bad if prob rose significantly
                shift = current_prob - entry_prob

            if shift > 0.15:
                # Prob moved >15pp against us — close early at current mid
                exit_price = _midpoint_price(market, side)
                result = _paper.close_paper_early(trade["id"], exit_price)
                _log.info(
                    f"[EarlyExit] #{trade['id']} {ticker} {side.upper()} closed: "
                    f"entry_prob={entry_prob:.2f} current={current_prob:.2f} "
                    f"pnl=${result['pnl']:.2f}"
                )
                closed += 1
        except Exception as exc:
            _log.warning(f"[EarlyExit] Error checking {ticker}: {exc}")
            continue

    return closed
```

- [ ] **Step 3: Call _check_early_exits from cmd_cron**

In `cmd_cron`, after `sync_outcomes` is called, add:

```python
    # Check open positions for early exit opportunities
    try:
        exits = _check_early_exits(client=client)
        if exits > 0:
            print(green(f"  [EarlyExit] Closed {exits} position(s) on model update."))
    except Exception:
        pass  # never crash the scheduler
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_trading.py::test_early_exit_closes_position_when_prob_flips -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite**

```
pytest tests/ -v --tb=short
```

Expected: All PASS

- [ ] **Step 6: Commit**

```
git add main.py tests/test_trading.py
git commit -m "feat(trading): add early exit on model cycle update"
```

---

## Task 8: Add cmd_schedule_cycles() for NWP-aligned scanning

**Files:**
- Modify: `main.py` — add `cmd_schedule_cycles()`

No automated test for this (it prints shell commands). Manual verification.

- [ ] **Step 1: Add cmd_schedule_cycles to main.py**

Add this function to `main.py` (near other `cmd_*` functions):

```python
def cmd_schedule_cycles() -> None:
    """
    Print Windows Task Scheduler commands to run the cron scan at NWP model
    cycle availability times: 02:15, 08:15, 14:15, 20:15 UTC.

    NWP models initialize at 00/06/12/18 UTC; data is available ~2h later.
    Scanning immediately after availability captures maximum market inefficiency.

    Run each printed command once in an elevated PowerShell to register the tasks.
    """
    import pytz  # type: ignore[import-untyped]
    from datetime import datetime, timezone, timedelta

    python_exe = sys.executable
    script_path = Path(__file__).resolve()

    utc_times = [2, 8, 14, 20]
    try:
        local_tz = datetime.now().astimezone().tzinfo
    except Exception:
        local_tz = timezone.utc

    print(bold("\nNWP Cycle-Aligned Scan Schedule"))
    print(dim("Run these commands once in an elevated PowerShell:\n"))

    for utc_hour in utc_times:
        utc_dt = datetime.now(timezone.utc).replace(
            hour=utc_hour, minute=15, second=0, microsecond=0
        )
        local_dt = utc_dt.astimezone(local_tz)
        local_time_str = local_dt.strftime("%H:%M")
        task_name = f"KalshiCron_{utc_hour:02d}UTC"
        cmd = (
            f'schtasks /Create /TN "{task_name}" /TR '
            f'"{python_exe} {script_path} cron" '
            f'/SC DAILY /ST {local_time_str} /F /RL HIGHEST'
        )
        print(f"# {utc_hour:02d}:15 UTC ({local_time_str} local)")
        print(cmd)
        print()

    print(dim("To verify tasks were created:"))
    print("schtasks /Query /FO LIST /V | findstr Kalshi")
```

- [ ] **Step 2: Register cmd_schedule_cycles in the CLI dispatch**

In `main.py`, find the CLI dispatch section (the large `if/elif` chain near the bottom). Add:

```python
    elif cmd == "schedule-cycles":
        cmd_schedule_cycles()
```

- [ ] **Step 3: Manual verification**

Run:
```
python main.py schedule-cycles
```

Expected output: 4 `schtasks /Create` commands with correct UTC → local time conversion.

- [ ] **Step 4: Commit**

```
git add main.py
git commit -m "feat(cron): add cmd_schedule_cycles for NWP cycle-aligned scanning"
```

---

## Task 9: Final integration — run full test suite and verify

- [ ] **Step 1: Run full test suite**

```
pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests pass (or only pre-existing failures if any).

- [ ] **Step 2: Run a manual cron scan to verify signals include new fields**

```
python main.py cron
```

Check `data/signals_cache.json` — each signal entry should have `near_threshold` field.
Check `data/cron.log` — should show tiered trade placement if any signals exist.

- [ ] **Step 3: Verify dynamic Brier cap is active**

```python
python -c "from paper import _dynamic_kelly_cap; print(_dynamic_kelly_cap())"
```

Expected: `125.0` (current Brier is 0.0064, which is ≤ 0.05)

- [ ] **Step 4: Final commit (if any cleanup needed)**

```
git add -p
git commit -m "chore: post-integration cleanup"
```

---

## Quick Reference: What Each Change Does to Trade Frequency and P&L

| Change | Effect |
|--------|--------|
| MED tier (15–24% edge) | ~3× more auto-trades |
| MEDIUM-risk markets | Next-day markets now tradeable |
| Dynamic Brier cap ($125 now) | 2.5× larger STRONG-tier positions |
| Condition Brier scaling | Down-weights poor-method trades by 25% |
| Model consensus 0.5× | Halves size when ICON/GFS disagree |
| Daily spend cap ($100) | Prevents runaway on bad-forecast days |
| Early exit | Recovers capital from flipped positions |
| NWP cycle alignment | More edge from freshest data |
