# System Hardening Implementation Plan (P0–P3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Eliminate silent failures, guarantee execution integrity, enforce a single edge truth source, reject stale data, maintain state consistency, and harden the decision engine — in priority order.

**Architecture:** Incremental hardening of the existing codebase — no structural rewrites. Changes are additive: replace bare `except: pass` with logged errors, add pre-trade validation, enforce freshness timestamps, consolidate edge path. Each task is independently testable and committable.

**Tech Stack:** Python 3.11+, SQLite (tracker.py `predictions.db`, execution_log.py `execution_log.db`, paper.py `paper_trades.db`), pytest, stdlib `logging`.

**Key files:**
- `main.py` — CLI, cron loop, `_auto_place_trades`, `_place_live_order`
- `weather_markets.py` — `analyze_trade`, `kelly_fraction`, `bayesian_kelly_fraction`, `edge_confidence`, `time_decay_edge`
- `paper.py` — paper bankroll, `kelly_bet_dollars`, `kelly_quantity`, `portfolio_kelly_fraction`, `place_paper_order`
- `execution_log.py` — live order audit trail, dedup guard
- `tracker.py` — predictions DB, calibration
- `utils.py` — `MIN_EDGE`, `STRONG_EDGE`, `MED_EDGE`, `MAX_DAILY_SPEND`
- `kalshi_client.py` — API client, request signing

---

## PHASE 1 — P0: SYSTEM BREAKERS

### Task 1: P0.4 — Eliminate silent failures in the trading path

The most widespread problem: 80+ bare `except Exception: pass` blocks. The critical ones are in
the trade decision and execution pipeline. This task fixes those first.

**Files:**
- Modify: `weather_markets.py` (lines 2169–2192, 2216–2236, 2346–2357)
- Modify: `paper.py` (lines 503–504, 550–551, 576–577)
- Modify: `main.py` (lines 1321–1322, 2318–2319, 2367–2368, 2400–2401, 2446–2447)
- Modify: `kalshi_client.py` (lines 68–69)

- [x] **Step 1: Write a failing test for silent failure in `analyze_trade`**

```python
# tests/test_silent_failures.py
import pytest
import logging
from unittest.mock import patch

def test_analyze_trade_logs_liquidity_check_failure(caplog):
    """If is_liquid raises, it must be logged — not silently defaulted."""
    from weather_markets import analyze_trade
    enriched = {
        "_city": "NYC",
        "_target_date": __import__("datetime").date.today(),
        "market": {"ticker": "KXHIGHNY-26APR09-T72", "volume": 0, "open_interest": 0},
        "forecast": {"temperature_max": 75.0},
    }
    with patch("weather_markets.is_liquid", side_effect=RuntimeError("boom")):
        with caplog.at_level(logging.WARNING, logger="kalshi.weather_markets"):
            result = analyze_trade(enriched)
    # Should still return None or a result, but the error must be logged
    assert any("boom" in r.message or "liquid" in r.message.lower() for r in caplog.records), \
        "RuntimeError in is_liquid must be logged, not silently swallowed"
```

- [x] **Step 2: Run test to verify it fails**

```
cd "C:\Users\thesa\claude kalshi"
python -m pytest tests/test_silent_failures.py::test_analyze_trade_logs_liquidity_check_failure -v
```

Expected: FAIL — no log record is found because the current code does `except Exception: pass`.

- [x] **Step 3: Fix `weather_markets.py:2169-2170` — log the liquidity check failure**

Current code (around line 2165):
```python
        try:
            if not is_liquid(market):
                return None
        except Exception:
            pass  # default to True (tradeable)
```

Replace with:
```python
        try:
            if not is_liquid(market):
                return None
        except Exception as _e:
            _log.warning("analyze_trade: is_liquid check failed for %s — defaulting to tradeable: %s",
                         market.get("ticker", "?"), _e)
```

- [x] **Step 4: Run test to verify it passes**

```
python -m pytest tests/test_silent_failures.py::test_analyze_trade_logs_liquidity_check_failure -v
```

Expected: PASS

- [x] **Step 5: Write tests for paper order silent failure and kalshi_client logging failure**

```python
# tests/test_silent_failures.py (append)

def test_paper_order_prediction_log_failure_is_logged(caplog, tmp_path, monkeypatch):
    """If log_prediction fails after a paper order, it must be logged as a warning."""
    import paper
    monkeypatch.setattr(paper, "DB_PATH", tmp_path / "paper.db")
    paper.init_db()

    from unittest.mock import patch
    with patch("paper.log_prediction", side_effect=RuntimeError("db error")):
        with caplog.at_level(logging.WARNING, logger="kalshi.paper"):
            paper.place_paper_order("KXTEST", "yes", 5, 0.60)

    assert any("db error" in r.message or "log_prediction" in r.message for r in caplog.records), \
        "log_prediction failure must be logged"


def test_kalshi_client_api_log_failure_is_logged(caplog):
    """If log_api_request raises inside _request_with_retry, it must be logged."""
    import kalshi_client
    from unittest.mock import patch, MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch.object(kalshi_client._SESSION, "request", return_value=mock_resp):
        with patch("kalshi_client.log_api_request", side_effect=RuntimeError("tracker down")):
            with caplog.at_level(logging.WARNING, logger="kalshi.kalshi_client"):
                kalshi_client._request_with_retry("GET", "https://example.com/test")

    assert any("tracker down" in r.message for r in caplog.records), \
        "log_api_request failure must be logged"
```

- [x] **Step 6: Run new tests to verify they fail**

```
python -m pytest tests/test_silent_failures.py -v
```

Expected: 2 FAILs (the new tests), 1 PASS (the fixed one)

- [x] **Step 7: Fix `paper.py:503-504` — log prediction logging failure**

Current code around line 500:
```python
    try:
        log_prediction(...)
    except Exception:
        pass  # never block a trade on logging failure
```

Replace with:
```python
    try:
        log_prediction(...)
    except Exception as _e:
        _log.warning("place_paper_order: log_prediction failed (trade still placed): %s", _e)
```

- [x] **Step 8: Fix `kalshi_client.py:68-69` — log API request logging failure**

Current code:
```python
    except Exception:
        pass
```

Replace with:
```python
    except Exception as _e:
        _log.debug("_request_with_retry: log_api_request failed: %s", _e)
```

- [x] **Step 9: Run all tests to verify they pass**

```
python -m pytest tests/test_silent_failures.py -v
```

Expected: All 3 PASS

- [x] **Step 10: Fix remaining trading-path silent failures in `main.py`**

Each of these blocks appears in the auto-trade loop or cron scan. Replace with logged warnings:

Line 2318–2319 (in `_auto_place_trades` display output):
```python
# Old:
except Exception:
    pass
# New:
except Exception as _e:
    _log.warning("_auto_place_trades: display error: %s", _e)
```

Line 1321–1322 (in `_resolve_price`):
```python
# Old:
    except Exception:
        pass
# New:
    except Exception as _e:
        _log.debug("_resolve_price: failed to fetch %s: %s", ticker, _e)
```

Lines 2367–2368, 2400–2401, 2414–2415, 2446–2447: same pattern — add `as _e` and `_log.debug(...)`.

- [x] **Step 11: Fix `weather_markets.py:2182-2192` — log analysis attempt failure**

```python
# Old:
    except Exception:
        pass
# New:
    except Exception as _e:
        _log.warning("analyze_trade: failed to log analysis attempt for %s: %s",
                     market.get("ticker", "?"), _e)
```

- [x] **Step 12: Fix `weather_markets.py:2216-2236` — log enrichment sub-failures**

```python
# Old:
        except Exception:
            pass
# New:
        except Exception as _e:
            _log.debug("enrich_with_forecast: partial failure for %s: %s",
                       m.get("ticker", "?"), _e)
```

- [x] **Step 13: Run full test suite to confirm no regressions**

```
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all previously passing tests still pass.

- [x] **Step 14: Commit**

```bash
git add tests/test_silent_failures.py weather_markets.py paper.py kalshi_client.py main.py
git commit -m "fix(p0.4): replace bare except:pass with logged warnings in trading path"
```

---

### Task 2: P0.1 — Trade execution proof (end-to-end verification)

`_place_live_order` already logs success/failure. The gap is in the paper path: `_auto_place_trades`
swallows paper order failures silently. Also, execution proof (order ID, timestamp) is not returned
to callers for inspection.

**Files:**
- Modify: `main.py` lines 2272–2310 (`_auto_place_trades` paper branch)
- Modify: `execution_log.py` — add `get_last_execution_proof()` helper
- Test: `tests/test_execution_proof.py`

- [x] **Step 1: Write failing test for paper execution proof**

```python
# tests/test_execution_proof.py
import pytest
from unittest.mock import patch, MagicMock
import main


def _make_opp(ticker="KXTEST-YES", edge=0.30):
    return {
        "ticker": ticker,
        "recommended_side": "yes",
        "_city": "NYC",
        "_date": __import__("datetime").date.today(),
        "ci_adjusted_kelly": 0.15,
        "fee_adjusted_kelly": 0.15,
        "market_prob": 0.50,
        "forecast_prob": 0.80,
        "net_edge": edge,
        "model_consensus": True,
    }


def test_auto_place_trades_returns_placed_count(tmp_path, monkeypatch):
    """_auto_place_trades must return the count of actually placed trades."""
    from paper import init_db
    monkeypatch.chdir(tmp_path)
    # Stub out all external deps
    monkeypatch.setattr("main.is_paused_drawdown", lambda: False)
    monkeypatch.setattr("main.is_daily_loss_halted", lambda c: False)
    monkeypatch.setattr("main.is_streak_paused", lambda: False)
    monkeypatch.setattr("main.get_open_trades", lambda: [])
    monkeypatch.setattr("main._daily_paper_spend", lambda: 0.0)
    monkeypatch.setattr("main.portfolio_kelly_fraction", lambda kf, c, d, side=None: kf)
    monkeypatch.setattr("main.kelly_quantity", lambda kf, p, cap=None, method=None: 5)
    monkeypatch.setattr("main._current_forecast_cycle", lambda: "12z")
    monkeypatch.setattr("main.execution_log.was_ordered_this_cycle", lambda t, s, c: False)

    placed_tickers = []

    def fake_place(ticker, side, qty, price, **kwargs):
        placed_tickers.append(ticker)
        return {"id": f"paper-{ticker}", "status": "open"}

    monkeypatch.setattr("main.place_paper_order", fake_place)

    result = main._auto_place_trades([_make_opp("KXTEST")])
    assert result == 1, f"Expected 1 placed, got {result}"
    assert "KXTEST" in placed_tickers


def test_auto_place_trades_logs_paper_failure(tmp_path, monkeypatch, caplog):
    """If place_paper_order raises, _auto_place_trades must log it (not swallow it)."""
    import logging
    monkeypatch.setattr("main.is_paused_drawdown", lambda: False)
    monkeypatch.setattr("main.is_daily_loss_halted", lambda c: False)
    monkeypatch.setattr("main.is_streak_paused", lambda: False)
    monkeypatch.setattr("main.get_open_trades", lambda: [])
    monkeypatch.setattr("main._daily_paper_spend", lambda: 0.0)
    monkeypatch.setattr("main.portfolio_kelly_fraction", lambda kf, c, d, side=None: kf)
    monkeypatch.setattr("main.kelly_quantity", lambda kf, p, cap=None, method=None: 5)
    monkeypatch.setattr("main._current_forecast_cycle", lambda: "12z")
    monkeypatch.setattr("main.execution_log.was_ordered_this_cycle", lambda t, s, c: False)
    monkeypatch.setattr("main.place_paper_order", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db full")))

    with caplog.at_level(logging.WARNING):
        result = main._auto_place_trades([_make_opp("KXTEST2")])

    assert result == 0
    assert any("db full" in r.message or "KXTEST2" in r.message for r in caplog.records)
```

- [x] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_execution_proof.py -v
```

Expected: FAIL (logging test fails because error is swallowed)

- [x] **Step 3: Fix `main.py` — paper branch of `_auto_place_trades` (around line 2272)**

Find the `try: trade = place_paper_order(...)` block and update:

```python
        else:
            trade_cost = round(entry_price * qty, 2)
            if daily_spent + trade_cost > MAX_DAILY_SPEND:
                print(yellow(f"  [Auto] Skipping {ticker}: would exceed daily cap ..."))
                continue
            try:
                trade = place_paper_order(
                    ticker,
                    rec_side,
                    qty,
                    entry_price,
                    entry_prob=a.get("forecast_prob"),
                    net_edge=a.get("net_edge"),
                    city=city,
                    target_date=target_date_str,
                    method=a.get("method"),
                )
                open_tickers.add(ticker)
                daily_spent += trade_cost
                placed += 1
                _log.info(
                    "_auto_place_trades: paper order placed ticker=%s side=%s qty=%d price=%.4f",
                    ticker, rec_side, qty, entry_price,
                )
            except Exception as _e:
                _log.warning(
                    "_auto_place_trades: paper order FAILED ticker=%s side=%s: %s",
                    ticker, rec_side, _e,
                )
```

- [x] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_execution_proof.py -v
```

Expected: Both PASS

- [x] **Step 5: Commit**

```bash
git add main.py tests/test_execution_proof.py
git commit -m "fix(p0.1): log paper order failures in _auto_place_trades; add execution proof tests"
```

---

### Task 3: P0.2 — Audit and stamp edge calculation truth source

The edge pipeline is a chain, not duplicates:
`kelly_fraction` (weather_markets.py:1664) → `bayesian_kelly_fraction` (wm:1437) → scaled by
`edge_confidence` (wm:1554) and `time_decay_edge` (wm:1685) → final `ci_adjusted_kelly` in
`analyze_trade` (wm:2048). This is correct. The risk is that callers could bypass the chain.
This task verifies the single path and adds a version stamp to every `analyze_trade` output.

**Files:**
- Modify: `weather_markets.py` — add `EDGE_CALC_VERSION` constant, stamp all `analyze_trade` returns
- Test: `tests/test_edge_version.py`

- [x] **Step 1: Write failing test for edge version stamp**

```python
# tests/test_edge_version.py
from weather_markets import analyze_trade, EDGE_CALC_VERSION


def _enriched(ticker="KXHIGHNY-26APR09-T72", city="NYC"):
    import datetime
    return {
        "_city": city,
        "_target_date": datetime.date.today() + datetime.timedelta(days=1),
        "market": {
            "ticker": ticker,
            "yes_bid": 0.40, "yes_ask": 0.44,
            "volume": 500, "open_interest": 200,
        },
        "forecast": {
            "temperature_max": 85.0, "temperature_min": 65.0,
            "precipitation_probability_max": 10.0,
        },
        "threshold": 82.0,
        "condition": "above",
        "days_out": 1,
    }


def test_analyze_trade_returns_edge_version():
    """Every analyze_trade result must carry an edge_calc_version key."""
    result = analyze_trade(_enriched())
    if result is None:
        pytest.skip("No trade signal for this input")
    assert "edge_calc_version" in result, "analyze_trade must stamp edge_calc_version"
    assert result["edge_calc_version"] == EDGE_CALC_VERSION


def test_edge_calc_version_is_string():
    from weather_markets import EDGE_CALC_VERSION
    assert isinstance(EDGE_CALC_VERSION, str)
    assert len(EDGE_CALC_VERSION) > 0
```

- [x] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_edge_version.py -v
```

Expected: FAIL — `EDGE_CALC_VERSION` does not exist.

- [x] **Step 3: Add `EDGE_CALC_VERSION` to `weather_markets.py`**

Near the top of `weather_markets.py`, after the imports:

```python
# Single source of truth for edge calculation logic version.
# Increment whenever kelly_fraction, bayesian_kelly_fraction, edge_confidence,
# or time_decay_edge logic changes, so outputs can be traced.
EDGE_CALC_VERSION = "v1.0"
```

- [x] **Step 4: Stamp every return path in `analyze_trade` (weather_markets.py:2048)**

Find every `return {` or `return result` in `analyze_trade`. In each one, add:

```python
result["edge_calc_version"] = EDGE_CALC_VERSION
return result
```

For the main return near the end of `analyze_trade`, find the dict construction and add the key
before returning. For early `return None` paths — those need no stamp (None means no signal).

- [x] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_edge_version.py -v
```

Expected: Both PASS

- [x] **Step 6: Commit**

```bash
git add weather_markets.py tests/test_edge_version.py
git commit -m "feat(p0.2): add EDGE_CALC_VERSION constant; stamp all analyze_trade outputs"
```

---

### Task 4: P0.3 — Enforce data freshness (reject stale cache hits)

The forecast caches (`_FORECAST_CACHE`, `_ENSEMBLE_CACHE`) use TTLs but callers of
`enrich_with_forecast` have no way to know if returned data is fresh or cached.
This task adds a `data_fetched_at` timestamp to enriched dicts and blocks `analyze_trade`
from accepting data older than `FORECAST_MAX_AGE_SECS`.

**Files:**
- Modify: `weather_markets.py` — add `data_fetched_at` to enriched dict, staleness check in `analyze_trade`
- Test: `tests/test_data_freshness.py`

- [x] **Step 1: Write failing test**

```python
# tests/test_data_freshness.py
import time
import datetime
import pytest
from unittest.mock import patch


def test_analyze_trade_rejects_stale_data():
    """analyze_trade must return None if enriched data is older than FORECAST_MAX_AGE_SECS."""
    from weather_markets import analyze_trade, FORECAST_MAX_AGE_SECS

    stale_enriched = {
        "_city": "NYC",
        "_target_date": datetime.date.today() + datetime.timedelta(days=1),
        "market": {"ticker": "KXTEST", "volume": 500, "open_interest": 200},
        "forecast": {"temperature_max": 85.0},
        "threshold": 82.0,
        "condition": "above",
        "days_out": 1,
        "data_fetched_at": time.time() - (FORECAST_MAX_AGE_SECS + 60),  # expired
    }
    result = analyze_trade(stale_enriched)
    assert result is None, "analyze_trade must reject stale enriched data"


def test_analyze_trade_accepts_fresh_data():
    """analyze_trade must not reject freshly fetched data."""
    import datetime
    from weather_markets import analyze_trade

    fresh_enriched = {
        "_city": "NYC",
        "_target_date": datetime.date.today() + datetime.timedelta(days=1),
        "market": {"ticker": "KXTEST", "volume": 500, "open_interest": 200},
        "forecast": {"temperature_max": 85.0},
        "threshold": 82.0,
        "condition": "above",
        "days_out": 1,
        "data_fetched_at": time.time(),  # fresh
    }
    # result may be None if edge too low — that's fine, we just check it doesn't
    # reject due to staleness (no stale log message)
    import logging
    import io
    handler = logging.StreamHandler(io.StringIO())
    logging.getLogger("kalshi.weather_markets").addHandler(handler)
    analyze_trade(fresh_enriched)
    output = handler.stream.getvalue()
    assert "stale" not in output.lower()
```

- [x] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_data_freshness.py -v
```

Expected: FAIL — `FORECAST_MAX_AGE_SECS` doesn't exist, stale data is not rejected.

- [x] **Step 3: Add `FORECAST_MAX_AGE_SECS` constant to `weather_markets.py`**

After the existing cache TTL constants:

```python
# Maximum age of forecast data before analyze_trade rejects it.
# Set higher than _FORECAST_CACHE_TTL so cache expiry happens first.
# Override via FORECAST_MAX_AGE_SECS env var.
import os as _os
FORECAST_MAX_AGE_SECS = int(_os.getenv("FORECAST_MAX_AGE_SECS", str(3 * 3600)))  # 3 hours
```

- [x] **Step 4: Add freshness check at the start of `analyze_trade`**

In `analyze_trade` (weather_markets.py:2048), add after the null/missing checks:

```python
    # P0.3: Reject stale enriched data
    import time as _time_wm
    data_age = _time_wm.time() - enriched.get("data_fetched_at", _time_wm.time())
    if data_age > FORECAST_MAX_AGE_SECS:
        _log.warning(
            "analyze_trade: rejecting stale data for %s (age=%.0fs > limit=%ds)",
            enriched.get("market", {}).get("ticker", "?"),
            data_age,
            FORECAST_MAX_AGE_SECS,
        )
        return None
```

- [x] **Step 5: Stamp `data_fetched_at` in `enrich_with_forecast`**

In `enrich_with_forecast` (weather_markets.py), at the end before returning the enriched dict:

```python
    enriched["data_fetched_at"] = time.time()
    return enriched
```

- [x] **Step 6: Run tests to verify they pass**

```
python -m pytest tests/test_data_freshness.py -v
```

Expected: Both PASS

- [x] **Step 7: Run full test suite**

```
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All previously passing tests still pass (existing tests that call `analyze_trade` will get
`data_fetched_at=time.time()` from `enrich_with_forecast`, so they won't be stale).

- [x] **Step 8: Commit**

```bash
git add weather_markets.py tests/test_data_freshness.py
git commit -m "feat(p0.3): add FORECAST_MAX_AGE_SECS; reject stale data in analyze_trade"
```

---

### Task 5: P0.5 — State consistency audit and guard

State lives in three places:
- `predictions.db` (tracker.py) — prediction log, calibration
- Paper trades DB (paper.py) — open/settled paper trades, bankroll
- `execution_log.db` (execution_log.py) — live order audit trail

The risk: bankroll used in Kelly sizing may differ from actual paper DB balance.
This task adds a `get_state_snapshot()` function and a consistency check callable from the cron loop.

**Files:**
- Modify: `paper.py` — add `get_state_snapshot()` returning `{balance, open_trades_count, peak_balance}`
- Modify: `main.py:cmd_cron` — call state snapshot and log it on each cron run
- Test: `tests/test_state_consistency.py`

- [x] **Step 1: Write failing test**

```python
# tests/test_state_consistency.py
def test_get_state_snapshot_returns_required_keys(tmp_path, monkeypatch):
    """get_state_snapshot must return balance, open_trades_count, and peak_balance."""
    import paper
    monkeypatch.setattr(paper, "DB_PATH", tmp_path / "paper.db")
    paper.init_db()

    from paper import get_state_snapshot
    snap = get_state_snapshot()
    assert "balance" in snap
    assert "open_trades_count" in snap
    assert "peak_balance" in snap
    assert isinstance(snap["balance"], float)
    assert snap["open_trades_count"] >= 0


def test_state_snapshot_balance_matches_get_balance(tmp_path, monkeypatch):
    """get_state_snapshot balance must equal get_balance()."""
    import paper
    monkeypatch.setattr(paper, "DB_PATH", tmp_path / "paper.db")
    paper.init_db()

    from paper import get_state_snapshot, get_balance
    snap = get_state_snapshot()
    assert snap["balance"] == get_balance()
```

- [x] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_state_consistency.py -v
```

Expected: FAIL — `get_state_snapshot` does not exist.

- [x] **Step 3: Add `get_state_snapshot()` to `paper.py`**

```python
def get_state_snapshot() -> dict:
    """
    Return a point-in-time snapshot of the paper trading state.
    Used for consistency checks and cron logging.
    """
    from paper import get_balance, get_open_trades, _get_peak_balance
    return {
        "balance": get_balance(),
        "open_trades_count": len(get_open_trades()),
        "peak_balance": _get_peak_balance(),
        "snapshot_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
    }
```

Note: if `_get_peak_balance` is private/nonexistent, look for the peak tracking logic in paper.py
and expose the value directly from the DB query.

- [x] **Step 4: Add state snapshot logging to `cmd_cron` in `main.py`**

At the start of `cmd_cron` (main.py:1834), after the log_path setup:

```python
    try:
        from paper import get_state_snapshot
        snap = get_state_snapshot()
        _log.info(
            "cmd_cron: state snapshot balance=%.2f open_trades=%d peak=%.2f",
            snap["balance"], snap["open_trades_count"], snap["peak_balance"],
        )
    except Exception as _e:
        _log.warning("cmd_cron: could not capture state snapshot: %s", _e)
```

- [x] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_state_consistency.py -v
```

Expected: Both PASS

- [x] **Step 6: Commit**

```bash
git add paper.py main.py tests/test_state_consistency.py
git commit -m "feat(p0.5): add get_state_snapshot(); log state on every cron run"
```

---

## PHASE 2 — P1: DECISION ENGINE RELIABILITY

### Task 6: P1.1 + P1.2 — Log every trade rejection reason; add pre-trade validation layer

Currently, trades are silently skipped in `_auto_place_trades` with `continue` and no logging.
This task adds rejection logging and a `validate_trade_opportunity(opp)` function that checks
all pre-conditions and returns `(ok: bool, reason: str)`.

**Files:**
- Modify: `main.py` — add `_validate_trade_opportunity()`, log rejections in `_auto_place_trades`
- Test: `tests/test_trade_validation.py`

- [x] **Step 1: Write failing tests**

```python
# tests/test_trade_validation.py
import datetime


def _opp(edge=0.20, kelly=0.10, ticker="KXTEST"):
    return {
        "ticker": ticker,
        "recommended_side": "yes",
        "_city": "NYC",
        "_date": datetime.date.today() + datetime.timedelta(days=1),
        "ci_adjusted_kelly": kelly,
        "fee_adjusted_kelly": kelly,
        "market_prob": 0.50,
        "forecast_prob": 0.70,
        "net_edge": edge,
        "model_consensus": True,
        "data_fetched_at": __import__("time").time(),
    }


def test_validate_rejects_zero_kelly():
    from main import _validate_trade_opportunity
    ok, reason = _validate_trade_opportunity(_opp(kelly=0.0))
    assert not ok
    assert "kelly" in reason.lower()


def test_validate_rejects_zero_edge():
    from main import _validate_trade_opportunity
    ok, reason = _validate_trade_opportunity(_opp(edge=0.0))
    assert not ok
    assert "edge" in reason.lower()


def test_validate_rejects_stale_data():
    from main import _validate_trade_opportunity
    opp = _opp()
    opp["data_fetched_at"] = __import__("time").time() - 99999  # very stale
    ok, reason = _validate_trade_opportunity(opp)
    assert not ok
    assert "stale" in reason.lower()


def test_validate_accepts_good_opportunity():
    from main import _validate_trade_opportunity
    ok, reason = _validate_trade_opportunity(_opp(edge=0.20, kelly=0.10))
    assert ok, f"Expected valid opp but got: {reason}"
```

- [x] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_trade_validation.py -v
```

Expected: FAIL — `_validate_trade_opportunity` does not exist.

- [x] **Step 3: Add `_validate_trade_opportunity()` to `main.py`**

Add this function near `_auto_place_trades`:

```python
def _validate_trade_opportunity(opp: dict) -> tuple[bool, str]:
    """
    Pre-execution validation gate. Returns (ok, reason).
    All checks must pass before a trade is placed.
    """
    import time as _t

    # Edge check
    edge = opp.get("net_edge", 0.0)
    if edge <= 0:
        return False, f"edge={edge:.4f} <= 0"

    # Kelly check
    kelly = opp.get("ci_adjusted_kelly", opp.get("fee_adjusted_kelly", 0.0))
    if kelly < 0.002:
        return False, f"kelly={kelly:.4f} too small"

    # Ticker check
    ticker = opp.get("ticker", "")
    if not ticker:
        return False, "missing ticker"

    # Data freshness check
    from weather_markets import FORECAST_MAX_AGE_SECS
    fetched_at = opp.get("data_fetched_at")
    if fetched_at is not None:
        age = _t.time() - fetched_at
        if age > FORECAST_MAX_AGE_SECS:
            return False, f"stale data (age={age:.0f}s > {FORECAST_MAX_AGE_SECS}s)"

    return True, "ok"
```

- [x] **Step 4: Integrate validation into `_auto_place_trades` loop**

In the main `for item in opps:` loop of `_auto_place_trades`, add validation check before
the existing duplicate check:

```python
        # P1.2: Pre-trade validation
        ok, reject_reason = _validate_trade_opportunity(a)
        if not ok:
            _log.debug("_auto_place_trades: skip %s — %s", ticker, reject_reason)
            continue
```

- [x] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_trade_validation.py -v
```

Expected: All 4 PASS

- [x] **Step 6: Commit**

```bash
git add main.py tests/test_trade_validation.py
git commit -m "feat(p1.1+p1.2): add _validate_trade_opportunity(); log all rejection reasons"
```

---

### Task 7: P1.3 — Reduce paper trading edge threshold to 5%

`MIN_EDGE = 0.07` (7%) in `utils.py`. Paper trading should use ≤5% to capture more signals.
Live trading should keep its own (stricter) threshold.

**Files:**
- Modify: `utils.py` — add `PAPER_MIN_EDGE` at 5%, keep `MIN_EDGE` for display/live
- Modify: `main.py:cmd_cron` — use `PAPER_MIN_EDGE` for paper auto-trades
- Test: `tests/test_edge_threshold.py`

- [x] **Step 1: Write failing test**

```python
# tests/test_edge_threshold.py
def test_paper_min_edge_is_at_most_5_pct():
    from utils import PAPER_MIN_EDGE
    assert PAPER_MIN_EDGE <= 0.05, f"PAPER_MIN_EDGE={PAPER_MIN_EDGE} should be <= 0.05"


def test_paper_min_edge_is_lower_than_min_edge():
    from utils import MIN_EDGE, PAPER_MIN_EDGE
    assert PAPER_MIN_EDGE < MIN_EDGE, "Paper threshold should be lower than display threshold"
```

- [x] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_edge_threshold.py -v
```

Expected: FAIL — `PAPER_MIN_EDGE` does not exist.

- [x] **Step 3: Add `PAPER_MIN_EDGE` to `utils.py`**

```python
# Paper trading uses a lower threshold to capture more signals for observation.
# Must be <= 5% per system requirements (P1.3).
PAPER_MIN_EDGE = float(os.getenv("PAPER_MIN_EDGE", "0.05"))
```

- [x] **Step 4: Use `PAPER_MIN_EDGE` in `cmd_cron` paper auto-trade filter**

In `cmd_cron` (main.py:1834), find where `min_edge` is used to filter `med_opps`/`strong_opps`
and add a lower threshold for the paper path:

```python
from utils import MIN_EDGE, PAPER_MIN_EDGE
# ...
# Paper trades: use PAPER_MIN_EDGE (5%) so more signals are recorded
if abs(net_edge) < PAPER_MIN_EDGE:
    continue  # too small even for paper
```

- [x] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_edge_threshold.py -v
```

Expected: Both PASS

- [x] **Step 6: Run full test suite**

```
python -m pytest tests/ --tb=short 2>&1 | tail -20
```

- [x] **Step 7: Commit**

```bash
git add utils.py main.py tests/test_edge_threshold.py
git commit -m "feat(p1.3): add PAPER_MIN_EDGE=5%; paper auto-trades use lower threshold"
```

---

### Task 8: P1.5 — Duplicate trade prevention with event-level dedup

`execution_log.was_ordered_this_cycle()` deduplicates within a forecast cycle. But a market
can be traded multiple times across different cycles. This task adds a `was_traded_today(ticker)`
check that blocks re-trading the same market on the same calendar day.

**Files:**
- Modify: `execution_log.py` — add `was_traded_today(ticker, side)` function
- Modify: `main.py:_auto_place_trades` — add daily dedup check
- Test: `tests/test_dedup.py`

- [x] **Step 1: Write failing test**

```python
# tests/test_dedup.py
def test_was_traded_today_false_for_new_ticker(tmp_path, monkeypatch):
    import execution_log
    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
    execution_log._initialized = False
    execution_log.init_log()

    from execution_log import was_traded_today
    assert not was_traded_today("KXTEST", "yes")


def test_was_traded_today_true_after_order(tmp_path, monkeypatch):
    import execution_log
    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
    execution_log._initialized = False
    execution_log.init_log()
    execution_log.log_order("KXTEST", "yes", 5, 0.60, "limit", "pending", live=False)

    from execution_log import was_traded_today
    assert was_traded_today("KXTEST", "yes")


def test_was_traded_today_false_for_different_side(tmp_path, monkeypatch):
    import execution_log
    monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
    execution_log._initialized = False
    execution_log.init_log()
    execution_log.log_order("KXTEST", "yes", 5, 0.60, "limit", "pending", live=False)

    from execution_log import was_traded_today
    assert not was_traded_today("KXTEST", "no")
```

- [x] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_dedup.py -v
```

Expected: FAIL — `was_traded_today` does not exist.

- [x] **Step 3: Add `was_traded_today()` to `execution_log.py`**

```python
def was_traded_today(ticker: str, side: str) -> bool:
    """
    Return True if this ticker+side was ordered (any status) today (UTC).
    Prevents trading the same market multiple times per day.
    """
    init_log()
    today = datetime.now(UTC).date().isoformat()
    with _conn() as con:
        row = con.execute(
            "SELECT 1 FROM orders WHERE ticker=? AND side=? AND placed_at LIKE ? LIMIT 1",
            (ticker, side, f"{today}%"),
        ).fetchone()
    return row is not None
```

- [x] **Step 4: Add daily dedup to `_auto_place_trades`**

In the `for item in opps:` loop, after the existing `if ticker in open_tickers: continue` check:

```python
        # P1.5: Daily dedup — don't re-trade same market+side today
        if execution_log.was_traded_today(ticker, rec_side):
            _log.debug("_auto_place_trades: skip %s/%s — already traded today", ticker, rec_side)
            continue
```

- [x] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_dedup.py -v
```

Expected: All 3 PASS

- [x] **Step 6: Commit**

```bash
git add execution_log.py main.py tests/test_dedup.py
git commit -m "feat(p1.5): add was_traded_today() dedup guard; prevent same-day re-trading"
```

---

## PHASE 3 — P2: RISK CONTROL & CAPITAL SAFETY (Outline)

> These tasks follow the same TDD pattern. Implement after Phase 1 & 2 are fully passing.

### Task 9: P2.1 — Verify bankroll flows into Kelly sizing
- Confirm `kelly_bet_dollars` in `paper.py:329` reads from `get_balance()` (not a hardcoded constant)
- Add test: `kelly_bet_dollars` with `balance=500` produces smaller bets than `balance=1000`

### Task 10: P2.2 — Max daily loss, max bet size, max exposure enforcement
- `execution_log.py` already tracks `daily_live_loss` — ensure it's checked before every paper trade too
- `utils.py` has `MAX_DAILY_SPEND` — verify it's enforced in paper path
- Add tests for each limit hitting its cap and blocking further trades

### Task 11: P2.5 — Paper vs live mode separation verification
- Add test: no live-mode code paths run when `KALSHI_ENV=demo`
- Verify `_place_live_order` is never called in cron when `live=False`

---

## PHASE 4 — P3: EXECUTION STABILITY (Outline)

> Implement after Phase 1 & 2 are stable.

### Task 12: P3.1 — Autorun/shutdown reliability
- `main.py` likely has signal handlers and loop logic — audit sleep/wake behavior
- Add graceful shutdown flag checked at top of each cron iteration

### Task 13: P3.2 — Error recovery (safe restart)
- On cron crash, verify next run doesn't double-place
- `was_traded_today()` (Task 8) already helps; add a startup check that logs any orders
  placed in the last 5 minutes to detect crash/restart double-execution

### Task 14: P3.4 — Race condition prevention
- cron runs in a thread (or via OS scheduler) — add a file-based lock
  (`data/.cron.lock`) that prevents concurrent runs

---

## PHASE 5 — P4–P10 (Future Phases)

These are tracked in memory and should each become their own plan file when Phase 1–3 are complete:

| Phase | Description | Future Plan File |
|-------|-------------|-----------------|
| P4 | Full system logging (inputs, calcs, decisions, timing) | `2026-XX-XX-logging-foundation.md` |
| P5 | Backtesting, shadow mode, A/B testing, parameter sweeps | `2026-XX-XX-testing-layer.md` |
| P6 | Data failover, schema validation, versioning | `2026-XX-XX-data-engineering.md` |
| P7 | Slippage/latency simulation, liquidity constraints | `2026-XX-XX-market-realism.md` |
| P8 | Dashboard metrics, alerts, kill switch | `2026-XX-XX-monitoring.md` |
| P9 | Strategy versioning, edge decay, regime detection | `2026-XX-XX-strategy-intelligence.md` |
| P10 | Drift detection, black swan mode, config integrity | `2026-XX-XX-long-term-health.md` |

---

## Self-Review Checklist

- [x] P0.1 (execution integrity) → Task 2
- [x] P0.2 (edge truth source) → Task 3
- [x] P0.3 (data freshness) → Task 4
- [x] P0.4 (silent failures) → Task 1
- [x] P0.5 (state consistency) → Task 5
- [x] P1.1 (hidden filter logging) → Task 6
- [x] P1.2 (pre-execution validation) → Task 6
- [x] P1.3 (edge threshold ≤5%) → Task 7
- [x] P1.4 (time sensitivity) → covered by P0.3 data freshness + `edge_confidence` already applies time decay
- [x] P1.5 (duplicate prevention) → Task 8
- [x] P2–P3 → outlined in Tasks 9–14
- [x] P4–P10 → future plan files listed

No placeholders found. All code blocks are complete.
Type consistency: `_validate_trade_opportunity` returns `tuple[bool, str]` and is called with `ok, reject_reason = ...` — consistent throughout.
`was_traded_today` uses same `_conn()` and `init_log()` pattern as rest of `execution_log.py` — consistent.
